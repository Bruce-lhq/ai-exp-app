"""Confirmed deletion limited to experiment output directories, never code/data."""
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import time
from .state import AgentError
from .config import settings

ACTIVE = {'queued', 'starting', 'running', 'stopping'}


def inspect(path, state):
    supplied = Path(path)
    if not supplied.is_absolute() or supplied.is_symlink():
        raise AgentError('DELETE_PATH', '删除目标必须为非符号链接的绝对目录')
    target = supplied.resolve(strict=True)
    if not target.is_dir():
        raise AgentError('DELETE_PATH', '删除目标不是实验目录')
    runs = list(state['runs'].values())
    matched = [r for r in runs if Path(r.get('remote_path', '/nonexistent')).resolve() == target]
    configured = [settings()['remote_runs_root']] + [r.get('project', {}).get('runs_root') for r in runs]
    roots = {Path(value).resolve() for value in configured if value and Path(value).is_absolute() and Path(value).resolve() != Path('/')}
    if not roots and not matched:
        raise AgentError('DELETE_SCOPE', '没有已配置的实验根目录，禁止删除未登记目录')
    if not matched and not any(target.is_relative_to(root) and target != root for root in roots):
        raise AgentError('DELETE_SCOPE', '只能删除已登记实验或实验根目录中的输出目录')
    if any(target == root or root.is_relative_to(target) for root in roots):
        raise AgentError('DELETE_SCOPE', '不能删除实验根目录或其父目录')
    for run in runs:
        output = Path(run.get('remote_path', '/nonexistent')).resolve()
        if run.get('status') in ACTIVE and (target == output or target.is_relative_to(output) or output.is_relative_to(target)):
            raise AgentError('DELETE_ACTIVE', '目标涉及正在运行或排队的实验')
        project = run.get('project', {})
        protected = [project.get('path'), project.get('remote_path'), run.get('snapshot', {}).get('path')]
        training = run.get('parameters', {}).get('training', {})
        protected.extend(training.get(k) for k in ('data_root', 'train_data', 'val_data'))
        for value in filter(None, protected):
            other = Path(value).resolve()
            if target == other or target.is_relative_to(other) or other.is_relative_to(target):
                raise AgentError('DELETE_PROTECTED', '删除目标涉及代码、快照或数据目录')
    if any((target / name).exists() for name in ('train.py', '.git', 'data.py')):
        raise AgentError('DELETE_PROTECTED', '目录中存在源码标记，不能作为实验产物删除')
    signatures = []
    total = 0
    for child in sorted(target.rglob('*')):
        if child.is_symlink():
            raise AgentError('DELETE_SYMLINK', '目录内存在符号链接，拒绝递归删除')
        stat = child.stat()
        signatures.append((str(child.relative_to(target)), stat.st_size, stat.st_mtime_ns, stat.st_ino))
        if child.is_file():
            total += stat.st_size
    stat = target.stat()
    digest = hashlib.sha256(json.dumps([stat.st_ino, signatures]).encode()).hexdigest()
    return target, digest, total, matched


def preview(payload, state):
    target, digest, total, _ = inspect(payload['path'], state)
    token = secrets.token_urlsafe(32)
    expires = time.time() + 120
    state.setdefault('delete_previews', {})[token] = {'path': str(target), 'digest': digest, 'expires_at': expires}
    return {'confirmation_token': token, 'targets': [str(target)], 'bytes': total, 'expires_at': expires}


def confirm(payload, state):
    token = payload.get('confirmation_token', '')
    entry = state.get('delete_previews', {}).get(token)
    if not entry or entry['expires_at'] < time.time():
        raise AgentError('DELETE_EXPIRED', '删除确认已失效')
    target, digest, _, matched = inspect(entry['path'], state)
    if digest != entry['digest']:
        raise AgentError('DELETE_CHANGED', '文件发生变化，请重新预览')
    quarantine = target.parent / ('.ai-exp-trash-' + secrets.token_hex(12))
    target.rename(quarantine)
    try:
        shutil.rmtree(quarantine)
    except OSError:
        if quarantine.exists() and not target.exists():
            quarantine.rename(target)
        raise
    for run in matched:
        run['files_deleted_at'] = time.time()
    del state['delete_previews'][token]
    return {'deleted': True, 'targets': [str(target)]}
