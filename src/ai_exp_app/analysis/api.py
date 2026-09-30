import uuid
import json
import time
import threading
from collections import OrderedDict
from ai_exp_app.projects.api import remote
from pathlib import Path
from fastapi import APIRouter, HTTPException
from .metrics import read_metrics
from .logs import read_log_metrics
from .tables import render_table
from .templates import ensure_default, normalize_columns
from ai_exp_app.history.importer import enrich

_external_cache = {}


def create_router(store):
    router = APIRouter()
    ensure_default(store)
    parsed_cache = OrderedDict()
    log_cache = OrderedDict()
    cache_lock = threading.Lock()

    def load(identity):
        record = store.get('history', identity)
        if not record:
            raise HTTPException(404, f'实验不存在：{identity}')
        record = enrich(record)
        path = Path(record['cache_dir']) / 'metrics.jsonl'
        stat = path.stat() if path.exists() else None
        signature = (str(path), (stat.st_ino, stat.st_size, stat.st_mtime_ns) if stat else None,
                     json.dumps(record.get('attempts'), sort_keys=True))
        with cache_lock:
            cached = parsed_cache.get(identity)
            if cached and cached[0] == signature:
                metrics = cached[1]
            else:
                metrics = read_metrics(path, identity, record.get('attempts'))
                parsed_cache[identity] = (signature, metrics)
            parsed_cache.move_to_end(identity)
            while len(parsed_cache) > 16:
                parsed_cache.popitem(last=False)
            log_path = Path(record['cache_dir']) / 'train.log'
            log_stat = log_path.stat() if log_path.exists() else None
            log_signature = (str(log_path), (log_stat.st_ino, log_stat.st_size, log_stat.st_mtime_ns) if log_stat else None)
            cached_log = log_cache.get(identity)
            if cached_log and cached_log[0] == log_signature:
                logs = cached_log[1]
            else:
                logs = read_log_metrics(log_path, identity)
                log_cache[identity] = (log_signature, logs)
            log_cache.move_to_end(identity)
            while len(log_cache) > 16:
                log_cache.popitem(last=False)
        record.update(metrics)
        if logs['records']:
            record['records'] = [r for r in metrics['records'] if r['metric'] != 'tokens_per_second'] + logs['records']
            record['metadata'] = {**metrics['metadata'], **logs['metadata']}
        return record

    def load_live(identities, metric, axis):
        groups, result = {}, {}
        for identity in dict.fromkeys(identities):
            run = store.get('runs', identity)
            if run and run.get('remote_path'):
                groups.setdefault(run.get('ssh_alias', 'gpu'), []).append(run)
        for alias, runs in groups.items():
            paths = [{'id': run['id'], 'path': run['remote_path']} for run in runs]
            key = (alias, metric, axis, json.dumps(paths, sort_keys=True))
            cached = _external_cache.get(key)
            error = None
            try:
                if cached and time.monotonic() - cached[0] < 3:
                    values = cached[1]
                else:
                    values = remote(alias, 'metric_series', {'runs': paths, 'metric': metric, 'axis': axis})
                    _external_cache[key] = (time.monotonic(), values)
                    if len(_external_cache) > 16:
                        del _external_cache[next(iter(_external_cache))]
            except HTTPException as exc:
                error = str(exc.detail)
                values = cached[1] if cached else {}
            for run in runs:
                identity = run['id']
                if error and not cached:
                    try:
                        result[identity] = load(identity)
                        result[identity]['warnings'] = [*result[identity]['warnings'], '更新失败，显示本地缓存：' + error]
                        continue
                    except HTTPException:
                        pass
                value = values.get(identity, {})
                result[identity] = {'name': run.get('display_name') or identity,
                    'records': [{'metric': metric, axis: p['x'], 'value': p['y']} for p in value.get('points', [])],
                    'metadata': {m: {'name': m} for m in value.get('metrics', [])},
                    'axes': value.get('axes', []),
                    'warnings': [*value.get('warnings', []), *(['更新失败，保留上次曲线：' + error] if error else [])]}
        return result

    @router.get('/api/history/{identity}/metrics')
    def metrics(identity: str):
        record = load(identity)
        return {k: record[k] for k in ('records', 'metadata', 'warnings', 'parameter_count')}

    @router.post('/api/analysis/series')
    def series(body: dict):
        metric, axis = body.get('metric', 'val_ppl'), body.get('x_axis', body.get('axis', 'tokens'))
        if axis not in {'tokens', 'step', 'elapsed_s'}:
            raise HTTPException(422, '无效横轴')
        result, warnings, available_metrics, available_axes = [], [], set(), set()
        live_records = load_live([identity for identity in body.get('live_ids', []) if identity in body.get('history_ids', [])], metric, axis)
        for identity in body.get('history_ids', []):
            try:
                record = live_records[identity] if identity in live_records else load(identity)
                history = store.get('history', identity)
                if history:
                    record = {**record, 'name': history.get('name'), 'display_name': history.get('display_name')}
            except HTTPException as exc:
                warnings.append(str(exc.detail))
                continue
            available_metrics.update(record['metadata'])
            available_axes.update(record.get('axes', []))
            available_axes.update(key for row in record['records'] for key in ('tokens', 'step', 'elapsed_s')
                                  if isinstance(row.get(key), (int, float)))
            points = [{'x': r[axis], 'y': r['value']} for r in record['records'] if r['metric'] == metric and isinstance(r.get(axis), (int, float))]
            if points:
                partitioned = [points[0]]
                for point in points[1:]:
                    if point['x'] < partitioned[-1]['x']:
                        partitioned.append({'x': point['x'], 'y': None})
                        warnings.append(f"{record['name']}：进度回退且缺少可靠阶段边界，曲线在此断开")
                    partitioned.append(point)
                points = partitioned
            warnings.extend(f"{record['name']}：{w}" for w in record['warnings'])
            if not points:
                warnings.append(f"{record['name']}：缺少 {metric} 或 {axis}，跳过此曲线，保留选择")
                continue
            # 图例默认采用用户可见的备注名；旧记录没有 display_name 时回退到原始名称。
            result.append({'id': identity,
                           'name': record.get('display_name') or record.get('name') or identity,
                           'points': points})
        return {'series': result, 'warnings': warnings, 'metrics': sorted(available_metrics), 'axes': sorted(available_axes)}

    @router.get('/api/templates')
    @router.get('/api/analysis/templates')
    def templates():
        return store.list('templates')

    def save(body, identity):
        try:
            columns = normalize_columns(body.get('columns', []))
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
        if not columns or not str(body.get('name', '')).strip():
            raise HTTPException(422, '模板名称和列不能为空')
        return store.put('templates', identity, {'id': identity, 'name': body['name'].strip(), 'columns': columns})

    @router.post('/api/templates')
    @router.post('/api/analysis/templates')
    def new_template(body: dict):
        return save(body, str(uuid.uuid4()))

    @router.put('/api/templates/{identity}')
    @router.put('/api/analysis/templates/{identity}')
    def update_template(identity: str, body: dict):
        if not store.get('templates', identity):
            raise HTTPException(404, '模板不存在')
        return save(body, identity)

    @router.post('/api/analysis/table')
    def table(body: dict):
        template = store.get('templates', body.get('template_id', 'default'))
        columns = body.get('columns', (template or {}).get('columns', []))
        try:
            runs, warnings = [], []
            for identity in body.get('history_ids', []):
                try:
                    runs.append(load(identity))
                except HTTPException as exc:
                    warnings.append(str(exc.detail))
            baseline = None
            if body.get('baseline_id'):
                try:
                    baseline = load(body['baseline_id'])
                except HTTPException as exc:
                    warnings.append(str(exc.detail))
            result = render_table(runs, columns, baseline)
            result['warnings'] = warnings + result['warnings']
            return result
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
    return router
