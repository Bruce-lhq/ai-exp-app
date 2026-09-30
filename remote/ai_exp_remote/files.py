from pathlib import Path
import json
import math
from .projects import directory
from .state import AgentError

ALLOWED = {'args.json','metrics.jsonl','train.log','launch.log','environment.json','run.json','meta.json','model_config.json','final_ca_stats.json','final_ca_stats_eval.log'}

def ca_window_metrics(values):
    # Same window mean as the local reader and plot_metric.py.
    result = {}
    for name, suffixes in {'R_min': ('Rmin', 'R_min'), 'R_mean': ('Rmean', 'R_mean'),
                           'update_rms': ('update_rms',)}.items():
        if name in values: continue
        direct = next((values[key] for key in suffixes if key in values), None)
        samples = [value for key, value in values.items()
                   if key.startswith('ca/') and key.rsplit('/', 1)[-1] in suffixes
                   and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)]
        if isinstance(direct, (int, float)) and not isinstance(direct, bool) and math.isfinite(direct):
            result[name] = direct
        elif samples:
            result[name] = sum(samples) / len(samples)
    return result

def run_progress(run):
    """Mirror gpu-dashboard's progress text and post-warmup windowed ETA.

    Reads only args.json and metrics.jsonl; remaining is computed from
    precise elapsed_s events anchored at the warmup boundary, like the
    dashboard, so both views agree."""
    root = Path(run['remote_path'])
    try:
        args = json.loads((root/'args.json').read_text())
    except (OSError, ValueError):
        return {}
    target = args.get('max_tokens')
    if not isinstance(target, (int, float)) or target <= 0:
        return {}
    target = int(target)
    warmup = args.get('warmup_tokens')
    anchor_tokens = int(warmup) if isinstance(warmup, (int, float)) and warmup > 0 else int(0.02*target)
    events, val_acc, tokens = [], 0, None
    try:
        with (root/'metrics.jsonl').open(errors='replace') as stream:
            for line in stream:
                try: item = json.loads(line)
                except ValueError: continue
                seen = item.get('tokens_seen')
                elapsed = item.get('elapsed_s')
                if not isinstance(seen, (int, float)) or not isinstance(elapsed, (int, float)) or elapsed < 0: continue
                tokens = int(seen)
                if item.get('event') == 'validation':
                    step = item.get('tokens')
                    if isinstance(step, (int, float)): val_acc += int(step)
                events.append((tokens, tokens + val_acc, float(elapsed)))
    except OSError:
        return {}
    if tokens is None:
        return {}
    def billions(value):
        if value < 1e7:
            scale, suffix = (1e6, 'M') if value >= 1e6 else (1e3, 'K') if value >= 1e3 else (1, '')
            return f'{value / scale:.2f}'.rstrip('0').rstrip('.') + suffix
        return f'{int(value/1e9)}B' if value >= 1e9 and value % 1e9 == 0 else f'{value/1e9:.2f}B'
    result = {'progress': f'{billions(tokens)}/{billions(target)}'}
    anchored = [e for e in events if e[0] >= anchor_tokens]
    if run['status'] in ('starting','running','stopping') and len(anchored) >= 2:
        window_tokens = events[-1][1] - anchored[0][1]
        window_elapsed = events[-1][2] - anchored[0][2]
        if window_tokens > 0 and window_elapsed > 0:
            remaining = 0.0 if tokens >= target else (target - tokens)/(window_tokens/window_elapsed)
            minutes = max(1, int(round(remaining/60)))
            result['remaining'] = f'{minutes//60}h{minutes%60:02d}m' if minutes >= 60 else f'{minutes}m'
    return result

def metric_series(payload):
    metric, axis = payload.get('metric', 'val_ppl'), payload.get('axis', 'tokens')
    if axis not in {'tokens', 'step', 'elapsed_s'}:
        raise AgentError('AXIS', '无效横轴')
    result = {}
    for run in payload.get('runs', []):
        points, available, axes, warnings = [], set(), set(), []
        try:
            path = directory(run['path']) / 'metrics.jsonl'
            if path.is_symlink():
                raise AgentError('FILE_NOT_ALLOWED', '拒绝读取符号链接')
            with path.open(errors='replace') as stream:
                for line in stream:
                    try: item = json.loads(line)
                    except ValueError: continue
                    if not isinstance(item, dict): continue
                    event = str(item.get('event', item.get('type', ''))).lower()
                    values = dict(item)
                    if isinstance(item.get('metrics'), dict): values.update(item['metrics'])
                    if event in {'train', 'training'}: values.update(ca_window_metrics(values))
                    axis_keys = {'tokens': ('tokens_seen', 'total_tokens', 'global_tokens', 'tokens'),
                                 'step': ('step', 'global_step', 'optimizer_step'),
                                 'elapsed_s': ('elapsed_s', 'elapsed_seconds')}
                    axes.update(name for name,keys in axis_keys.items() if any(isinstance(item.get(key),(int,float)) and not isinstance(item.get(key),bool) and math.isfinite(item[key]) for key in keys))
                    x_keys = {'tokens': ('tokens_seen', 'total_tokens', 'global_tokens', 'tokens'),
                              'step': ('step', 'global_step', 'optimizer_step'),
                              'elapsed_s': ('elapsed_s', 'elapsed_seconds')}[axis]
                    x = next((item[k] for k in x_keys if isinstance(item.get(k), (int, float))), None)
                    for key, value in values.items():
                        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value): continue
                        name = key
                        if key in {'perplexity', 'ppl', 'loss'}:
                            prefix = 'val' if event in {'validation', 'val', 'eval', 'evaluation'} else 'train' if event in {'train', 'training'} else None
                            if prefix: name = prefix + '_' + ('ppl' if key in {'perplexity', 'ppl'} else key)
                        available.add(name)
                        if name == metric and isinstance(x, (int, float)) and math.isfinite(x):
                            points.append({'x': x, 'y': value})
        except (OSError, AgentError) as exc:
            warnings.append(str(exc))
        result[run['id']] = {'points': points, 'metrics': sorted(available), 'axes': sorted(axes), 'warnings': warnings}
    return result

def list_directory(payload):
    path=directory(payload['path'])
    entries=[]
    for child in sorted(path.iterdir(),key=lambda x:x.name.lower()):
        try:
            if child.is_dir():
                entries.append(dict(name=child.name,path=str(child),can_enter=True,is_symlink=child.is_symlink()))
        except PermissionError:
            pass
    return dict(path=str(path),parent=str(path.parent),entries=entries)

def inspect_files(payload):
    path=directory(payload['path'])
    return {'files':[{'name':p.name,'size':p.stat().st_size} for p in sorted(path.iterdir()) if p.name in ALLOWED and p.is_file() and not p.is_symlink()]}

def read_file(payload):
    root=directory(payload['path']);name=payload['name']
    if name not in ALLOWED:
        raise AgentError('FILE_NOT_ALLOWED','只能读取实验日志、指标和参数文件')
    path=root/name
    if path.is_symlink() or not path.is_file():
        raise AgentError('FILE_MISSING','文件不存在或是符号链接')
    offset=max(0,int(payload.get('offset',0)));limit=min(32*1024*1024,max(1,int(payload.get('limit',32*1024*1024))))
    with path.open('rb') as stream:
        stream.seek(offset);data=stream.read(limit)
    return dict(content=data.decode('utf-8',errors='replace'),offset=offset,next_offset=offset+len(data),size=path.stat().st_size)

def file_manifest(payload):
    result=inspect_files(payload)
    root=directory(payload['path'])
    checkpoint=root/'latest.pt'
    if payload.get('checkpoint') and checkpoint.is_file() and not checkpoint.is_symlink():
        result['files'].append({'name':'latest.pt','size':checkpoint.stat().st_size})
    for item in result['files']:
        stat = (root/item['name']).stat()
        item.update(size=stat.st_size, mtime_ns=stat.st_mtime_ns, inode=stat.st_ino)
    return result

def read_file_chunk(payload):
    import base64
    root=directory(payload['path']);name=payload['name']
    if name not in ALLOWED or (root/name).is_symlink():raise AgentError('FILE_NOT_ALLOWED','不允许读取此文件')
    path=root/name
    before=path.stat()
    snapshot = payload.get('snapshot_size')
    append_only = name in {'metrics.jsonl', 'train.log', 'launch.log'} and snapshot is not None
    def unchanged(stat):
        if append_only:
            return stat.st_ino == payload.get('inode') and stat.st_size >= snapshot
        return payload.get('mtime_ns') is None or stat.st_mtime_ns == payload['mtime_ns']
    if not unchanged(before): raise AgentError('FILE_CHANGED','文件发生变化，请重新同步')
    offset = max(0, int(payload.get('offset', 0)))
    length = min(1024*1024, max(1, int(payload.get('length', 1024*1024))))
    if append_only: length = min(length, max(0, snapshot - offset))
    with path.open('rb') as stream:
        stream.seek(offset)
        data=stream.read(length)
    after = path.stat()
    if not unchanged(after) or after.st_ino != before.st_ino or (not append_only and after.st_mtime_ns != before.st_mtime_ns):
        raise AgentError('FILE_CHANGED','文件发生变化，请重新同步')
    return {'data':base64.b64encode(data).decode()}
