import base64
import json
import os
import tempfile
import threading
import shlex
import subprocess
from pathlib import Path

ALLOWED_FILES = {'args.json', 'model_config.json', 'metrics.jsonl', 'train.log', 'launch.log',
                 'final_ca_stats.json', 'final_ca_stats_eval.log', 'environment.json', 'run.json', 'meta.json',
                 'parameter_annotations.json'}
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


def local_manifest(path, checkpoint=False):
    root = Path(path).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('请选择实验目录')
    files = []
    for name in sorted(ALLOWED_FILES | ({'latest.pt'} if checkpoint else set())):
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


def download_checkpoint(source, entry, target):
    """One SSH stream, with an atomic local replacement; never buffer a GB in RAM."""
    from ai_exp_app.transport.ssh import build_ssh_argv, DEFAULT_AGENT
    wrapper = Path.home() / '.local/bin/ssh'
    argv = build_ssh_argv(str(wrapper) if wrapper.exists() else 'ssh', source.get('ssh_alias', 'gpu'), DEFAULT_AGENT)
    script = "\n".join([
        'from pathlib import Path', 'import sys, shutil',
        'p=Path(' + repr(source['path']) + ')/"latest.pt"',
        'assert not p.is_symlink()',
        's=p.stat()',
        'assert (s.st_size,s.st_mtime_ns)=='+repr((entry['size'],entry['mtime_ns'])),
        'with p.open("rb") as f: shutil.copyfileobj(f,sys.stdout.buffer,1024*1024)',
        's2=p.stat()', 'assert (s.st_ino,s.st_size,s.st_mtime_ns)==(s2.st_ino,s2.st_size,s2.st_mtime_ns)',
    ])
    argv[-1] = 'python3 -c ' + shlex.quote(script)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.checkpoint-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            result = subprocess.run(argv, stdout=output, stderr=subprocess.PIPE, timeout=600)
            output.flush()
            os.fsync(output.fileno())
        if result.returncode or Path(temporary).stat().st_size != entry['size']:
            raise OSError('checkpoint 下载未完成或源文件变化，将自动重试')
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def sync_history(record, cache_root):
    source = record['source']
    target = Path(record['cache_dir'])
    if not target.resolve().is_relative_to(Path(cache_root).resolve()):
        raise ValueError('缓存目录超出允许范围')
    with run_lock(record['id']):
        checkpoint = record.get('status') in {'paused', 'stopped', 'completed', 'failed', 'external_exited'}
        payload = {'path': source['path'], 'checkpoint': checkpoint}
        if source['kind'] == 'local':
            files = local_manifest(source['path'], checkpoint)
        else:
            files = rpc(source.get('ssh_alias', 'gpu'), 'file_manifest', payload)['files']
        copied = []
        previous = {f['name']: f for f in record.get('manifest', [])}
        for entry in files:
            name = entry['name']
            if name not in ALLOWED_FILES and not (checkpoint and name == 'latest.pt'):
                continue
            dest = target / name
            if dest.is_symlink():
                raise ValueError('拒绝写入符号链接')
            if previous.get(name) == entry and dest.is_file() and dest.stat().st_size == entry['size'] and not (name == 'args.json' and record.get('parameter_overrides')):
                copied.append(name)
                continue
            if name == 'run.json' and source['kind'] == 'remote':
                # The daemon atomically rewrites this live status file every tick.
                # Read one complete version rather than insisting on an old manifest's mtime.
                snapshot = rpc(source.get('ssh_alias', 'gpu'), 'read_file', {'path': source['path'], 'name': name})
                if snapshot['next_offset'] < snapshot['size']:
                    raise OSError('状态文件未完整读取')
                json.loads(snapshot['content'])
                replace_complete_file(dest, [snapshot['content'].encode('utf-8')])
                copied.append(name)
                continue
            if name == 'latest.pt' and source['kind'] == 'remote':
                download_checkpoint(source, entry, dest)
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
                            'mtime_ns': entry.get('mtime_ns'),
                            **({'snapshot_size': entry['size'], 'inode': entry['inode']}
                               if name in {'metrics.jsonl', 'train.log', 'launch.log'} and 'inode' in entry else {})})
                        chunk = base64.b64decode(result['data'])
                        if not chunk:
                            raise OSError('源文件在同步中发生变化')
                        offset += len(chunk)
                        yield chunk
            replace_complete_file(dest, chunks())
            copied.append(name)
        migrated = {}
        if record.get('parameter_overrides') and 'args.json' in copied:
            from .importer import parameter_fields
            parameters = json.loads((target / 'args.json').read_text())
            fields = parameter_fields(parameters) if isinstance(parameters, dict) else set()
            annotations = {**record.get('parameter_annotations', {}),
                           **{key: value.strip() for key, value in record['parameter_overrides'].items()
                              if key not in fields and isinstance(value, str)}}
            migrated = {'parameter_annotations': annotations, 'parameter_overrides': {}}
        if source['kind'] == 'local':
            after = local_manifest(source['path'], checkpoint)
        else:
            after = rpc(source.get('ssh_alias', 'gpu'), 'file_manifest', payload)['files']
        warnings = []
        if checkpoint and 'latest.pt' not in copied:
            warnings.append('没有 latest.pt，无法缓存 checkpoint 或严格续跑')
        if 'args.json' not in copied:
            warnings.append('缺少 args.json，超参数信息不可用')
        if 'metrics.jsonl' not in copied:
            warnings.append('缺少 metrics.jsonl，曲线不可用')
        return {'sync_status': 'synced' if after == files else 'pending', 'files': copied,
                'warnings': warnings, 'sync_error': None, 'manifest': files if after == files else [], **migrated}
