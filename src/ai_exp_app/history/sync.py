import base64
import os
import tempfile
import threading
from pathlib import Path

ALLOWED_FILES = {'args.json', 'model_config.json', 'metrics.jsonl', 'train.log', 'launch.log',
                 'final_ca_stats.json', 'final_ca_stats_eval.log', 'environment.json', 'run.json', 'meta.json'}
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def run_lock(identity):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(identity, threading.RLock())


def replace_complete_file(target: Path, chunks) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.download-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            for chunk in chunks:
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def local_manifest(path):
    root = Path(path).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('请选择实验目录')
    files = []
    for name in sorted(ALLOWED_FILES):
        file = root / name
        if file.is_file() and not file.is_symlink():
            stat = file.stat()
            files.append({'name': name, 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns})
    return files


def rpc(alias, operation, payload):
    from ai_exp_app.transport.ssh import call_remote
    import uuid
    return call_remote(alias, {'version': 1, 'request_id': str(uuid.uuid4()),
                              'operation': operation, 'payload': payload})


def sync_history(record, cache_root):
    source = record['source']
    target = Path(record['cache_dir'])
    if not target.resolve().is_relative_to(Path(cache_root).resolve()):
        raise ValueError('缓存目录超出允许范围')
    with run_lock(record['id']):
        if source['kind'] == 'local':
            files = local_manifest(source['path'])
        else:
            files = rpc(source.get('ssh_alias', 'gpu'), 'file_manifest', {'path': source['path']})['files']
        copied = []
        previous = {f['name']: f for f in record.get('manifest', [])}
        for entry in files:
            name = entry['name']
            if name not in ALLOWED_FILES:
                continue
            dest = target / name
            if dest.is_symlink():
                raise ValueError('拒绝写入符号链接')
            if previous.get(name) == entry and dest.is_file() and dest.stat().st_size == entry['size']:
                copied.append(name)
                continue
            if source['kind'] == 'local':
                origin = Path(source['path']) / name
                if origin.resolve() == dest.resolve():
                    copied.append(name)
                    continue
                def chunks():
                    remaining = entry['size']
                    with origin.open('rb') as stream:
                        while remaining:
                            chunk = stream.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise OSError('源文件在同步中发生变化')
                            remaining -= len(chunk)
                            yield chunk
            else:
                def chunks():
                    offset = 0
                    while offset < entry['size']:
                        result = rpc(source.get('ssh_alias', 'gpu'), 'read_file_chunk', {
                            'path': source['path'], 'name': name, 'offset': offset,
                            'length': min(1024 * 1024, entry['size'] - offset),
                            'mtime_ns': entry.get('mtime_ns')})
                        chunk = base64.b64decode(result['data'])
                        if not chunk:
                            raise OSError('源文件在同步中发生变化')
                        offset += len(chunk)
                        yield chunk
            replace_complete_file(dest, chunks())
            copied.append(name)
        if source['kind'] == 'local':
            after = local_manifest(source['path'])
        else:
            after = rpc(source.get('ssh_alias', 'gpu'), 'file_manifest', {'path': source['path']})['files']
        warnings = []
        if 'args.json' not in copied:
            warnings.append('缺少 args.json，超参数信息不可用')
        if 'metrics.jsonl' not in copied:
            warnings.append('缺少 metrics.jsonl，曲线不可用')
        return {'sync_status': 'synced' if after == files else 'pending', 'files': copied,
                'warnings': warnings, 'sync_error': None, 'manifest': files if after == files else []}
