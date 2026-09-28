import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException
from .metrics import read_metrics
from .tables import render_table
from .templates import ensure_default, normalize_columns
from ai_exp_app.history.importer import enrich


def create_router(store):
    router = APIRouter()
    ensure_default(store)

    def load(identity):
        record = store.get('history', identity)
        if not record:
            raise HTTPException(404, f'实验不存在：{identity}')
        record = enrich(record)
        metrics = read_metrics(Path(record['cache_dir']) / 'metrics.jsonl', identity, record.get('attempts'))
        record.update(metrics)
        return record

    @router.get('/api/history/{identity}/metrics')
    def metrics(identity: str):
        record = load(identity)
        return {k: record[k] for k in ('records', 'metadata', 'warnings', 'parameter_count')}

    @router.post('/api/analysis/series')
    def series(body: dict):
        metric, axis = body.get('metric', 'val_ppl'), body.get('x_axis', body.get('axis', 'tokens'))
        if axis not in {'tokens', 'step', 'elapsed_s'}:
            raise HTTPException(422, '无效横轴')
        result, warnings = [], []
        for identity in body.get('history_ids', []):
            try:
                record = load(identity)
            except HTTPException as exc:
                warnings.append(str(exc.detail))
                continue
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
            result.append({'id': identity, 'name': record['name'], 'points': points})
        return {'series': result, 'warnings': warnings}

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
