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

def metric_series(payload):
    metric, axis = payload.get('metric', 'val_ppl'), payload.get('axis', 'tokens')
    if axis not in {'tokens', 'step', 'elapsed_s'}:
        raise AgentError('AXIS', '无效横轴')
    result = {}
    for run in payload.get('runs', []):
        points, available, warnings = [], set(), []
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
        result[run['id']] = {'points': points, 'metrics': sorted(available), 'warnings': warnings}
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
    for item in result['files']:item['mtime_ns']=(root/item['name']).stat().st_mtime_ns
    return result

def read_file_chunk(payload):
    import base64
    root=directory(payload['path']);name=payload['name']
    if name not in ALLOWED or (root/name).is_symlink():raise AgentError('FILE_NOT_ALLOWED','不允许读取此文件')
    path=root/name
    before=path.stat()
    if payload.get('mtime_ns') is not None and before.st_mtime_ns!=payload['mtime_ns']:raise AgentError('FILE_CHANGED','文件发生变化，请重新同步')
    with path.open('rb') as stream:
        stream.seek(max(0,int(payload.get('offset',0))))
        data=stream.read(min(1024*1024,max(1,int(payload.get('length',1024*1024)))))
    if path.stat().st_mtime_ns!=before.st_mtime_ns:raise AgentError('FILE_CHANGED','文件发生变化，请重新同步')
    return {'data':base64.b64encode(data).decode()}
