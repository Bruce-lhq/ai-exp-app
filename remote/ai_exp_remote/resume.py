"""Strict resume validation. Never unpickle arbitrary imported local history."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from .state import AgentError

METADATA = r'''
import json, math, sys, torch
c = torch.load(sys.argv[1], map_location='cpu', weights_only=False)
required = ('model_state','optimizer_state','rng_states','train_sample_cursors','tokens_seen','optimizer_step','args','model_config','data_config','tokenizer_config')
missing = [k for k in required if k not in c]
if missing: raise ValueError('缺少严格续跑状态：' + ', '.join(missing))
n = c.get('world_size', 0)
if not n or any(len(c[k]) != n for k in ('rng_states','train_sample_cursors')): raise ValueError('缺少每张卡的完整状态')
a = dict(c['args'])
# Training deliberately omits inactive CA arguments from persisted_args.
if 'ca_lambda' not in a: a['ca_lambda'] = c['model_config'].get('ca_lambda', 0.0)
def safe(v):
 if isinstance(v,float) and not math.isfinite(v): return None
 if isinstance(v,dict): return {k:safe(x) for k,x in v.items()}
 return v
print(json.dumps(safe(dict(training=a, runtime=dict(gpu_count=n), tokens_seen=c['tokens_seen']))))
'''

def checkpoint_identity(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise AgentError('CHECKPOINT_MISSING', '云端没有可用的 latest.pt')
    stat = path.stat()
    return dict(size=stat.st_size, mtime_ns=stat.st_mtime_ns, inode=stat.st_ino)

def preview(payload):
    from .projects import PYTHON
    path = Path(payload['path']) / 'latest.pt'
    before = checkpoint_identity(path)
    result = subprocess.run([payload.get('python') or PYTHON, '-c', METADATA, str(path)],
        capture_output=True, text=True, timeout=90, env=dict(os.environ, CUDA_VISIBLE_DEVICES=''))
    if result.returncode:
        raise AgentError('CHECKPOINT_INVALID', 'checkpoint 无法严格续跑', result.stderr[-2000:])
    if before != checkpoint_identity(path):
        raise AgentError('CHECKPOINT_CHANGED', 'checkpoint 正在更新，请重新载入')
    return dict(json.loads(result.stdout), path=str(path), identity=before)

def pin(source, destination):
    path = Path(source['path'])
    if checkpoint_identity(path) != source['identity']:
        raise AgentError('CHECKPOINT_CHANGED', 'checkpoint 已更新，请从历史重新载入续跑')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(path, destination)
        if checkpoint_identity(path) != source['identity']:
            raise AgentError('CHECKPOINT_CHANGED', '复制时 checkpoint 已更新，请重新载入')
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return str(destination)

def validate_resume_metadata(checkpoint,expected):
    errors=[]
    for key in ('model_state','optimizer_state','rng_states','train_sample_cursors'):
        if key not in checkpoint:errors.append('缺少 '+key)
    if expected.get('requires_scaler') and not checkpoint.get('grad_scaler_state'):errors.append('缺少 scaler_state')
    for key in ('rng_states','train_sample_cursors'):
        if key in checkpoint and len(checkpoint[key])!=expected['world_size']:errors.append(key+' 的 rank 数量不匹配')
    for key in ('world_size','manifest_fingerprint','args','model_config'):
        if key in expected and checkpoint.get(key)!=expected[key]:errors.append(key+' 不匹配')
    if checkpoint.get('allow_nonexact_resume') or checkpoint.get('allow_world_size_change'):errors.append('不允许非严格续跑')
    return errors
