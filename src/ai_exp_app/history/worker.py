import time
import os
import tempfile
from pathlib import Path
from .importer import import_history, save_cache_update
from .repository import TERMINAL
from .sync import download_checkpoint, replace_complete_file, run_lock, sync_history


def sync_once(store, cache_root):
    for run in store.list('runs'):
        if run.get('external') and not run.get('adopted'):
            continue
        if run.get('status') == 'stopped' and run.get('mode') == 'queue' and not run.get('attempt_id'):
            continue
        identity = run['id']
        with run_lock(identity):
            existing = store.get('history', identity) or next((h for h in store.list('history')
                if h.get('source', {}).get('kind') == 'remote'
                and h['source'].get('path') == (run.get('run_dir') or run.get('remote_path'))
                and h['source'].get('ssh_alias', 'gpu') == run.get('ssh_alias', 'gpu')), None)
            path = run.get('run_dir') or run.get('remote_path') or run.get('output_dir') or run.get('path')
            if not path or (existing and existing.get('visibility') == 'removed'):
                continue
            if not existing and run.get('status') in TERMINAL | {'running', 'stopping'}:
                try:
                    existing = import_history(store, {'kind': 'remote', 'path': path,
                        'ssh_alias': run.get('ssh_alias', run.get('alias', 'gpu'))}, cache_root,
                        run.get('display_name', run.get('name', identity)), identity, synchronize=False,
                        visibility='visible' if run.get('status') in TERMINAL else 'tracking')
                except (OSError, ValueError):
                    continue
            if existing:
                with store.lock:
                    existing = store.get("history", existing["id"])
                    if not existing or existing.get("visibility") == "removed":
                        continue
                    if existing.get('status') != run.get('status'):
                        existing['sync_status'] = 'pending'
                    existing['status'] = run.get('status', existing['status'])
                    existing['attempts'] = run.get('attempts', [])
                    existing['stop_tokens'] = run.get('stop_tokens')
                    if run.get('project_id'):
                        display = store.get('preferences', f"parameters:{run['project_id']}") or {}
                        existing['parameter_labels'] = display.get('aliases', {})
                    if existing.get('visibility') == 'tracking' and run.get('status') in TERMINAL:
                        existing['visibility'] = 'visible'
                    store.put('history', existing['id'], existing)
    failed_aliases = set()
    for candidate in store.list('history'):
        with run_lock(candidate['id']):
            record = store.get('history', candidate['id'])
            if not record or record.get('visibility') == 'removed' or record.get('remote_deleted'):
                continue
            needs_checkpoint_state = (record.get('status') in TERMINAL and not record.get('checkpoint_sync_status')
                                      and 'latest.pt' not in record.get('files', [])
                                      and not any('没有 latest.pt' in w for w in record.get('warnings', [])))
            if record.get('sync_status') == 'synced' and record.get('status') not in {'running', 'stopping', 'starting'} and not needs_checkpoint_state:
                continue
            alias = record['source'].get('ssh_alias', 'gpu') if record['source']['kind'] == 'remote' else None
            if record.get('next_retry_at', 0) > time.time() or (alias and alias in failed_aliases):
                continue
            try:
                update = {**sync_history(record, cache_root, include_checkpoint=False), 'sync_failures': 0, 'next_retry_at': 0}
            except Exception as exc:
                failures = record.get('sync_failures', 0) + 1
                update = dict(sync_status='pending', sync_error=str(exc), sync_failures=failures,
                              next_retry_at=time.time() + min(300, 2 ** min(failures, 8)))
                if alias:
                    failed_aliases.add(alias)
            save_cache_update(store, record['id'], update)


def sync_checkpoints(store, cache_root, stop_event=None):
    # Large transfers must not hold the history lock or block small-file refreshes.
    for record in store.list('history'):
        if stop_event is not None and stop_event.is_set():
            return
        if (record.get('status') not in TERMINAL or record.get('visibility') == 'removed'
                or record.get('remote_deleted') or record.get('checkpoint_sync_status') != 'pending'
                or record.get('checkpoint_retry_at', 0) > time.time()):
            continue
        entry = next((item for item in record.get('manifest', []) if item['name'] == 'latest.pt'), None)
        if entry is None:
            continue
        try:
            with tempfile.TemporaryDirectory(prefix='.checkpoint-', dir=cache_root) as temporary:
                staged = Path(temporary) / 'latest.pt'
                source = record['source']
                if source['kind'] == 'remote':
                    if stop_event is None:
                        download_checkpoint(source, entry, staged)
                    else:
                        download_checkpoint(source, entry, staged, stop_event=stop_event)
                else:
                    origin = Path(source['path']) / 'latest.pt'
                    if origin.is_symlink():
                        raise ValueError('拒绝读取符号链接')
                    with origin.open('rb') as stream:
                        replace_complete_file(staged, iter(lambda: stream.read(1024 * 1024), b''))
                    stat = origin.stat()
                    if (stat.st_size, stat.st_mtime_ns) != (entry['size'], entry['mtime_ns']):
                        raise OSError('checkpoint 在同步中发生变化')
                with run_lock(record['id']):
                    current = store.get('history', record['id'])
                    if (not current or current.get('source') != source or current.get('visibility') == 'removed'
                            or current.get('remote_deleted') or current.get('status') not in TERMINAL
                            or entry not in current.get('manifest', [])):
                        continue
                    target = Path(current['cache_dir']) / 'latest.pt'
                    if target.is_symlink() or not target.resolve().is_relative_to(Path(cache_root).resolve()):
                        raise ValueError('checkpoint 缓存路径异常')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged, target)
                    save_cache_update(store, record['id'], {
                        'files': sorted(set(current.get('files', [])) | {'latest.pt'}),
                        'checkpoint_manifest': entry, 'checkpoint_sync_status': 'synced',
                        'checkpoint_sync_error': None, 'checkpoint_retry_at': 0})
        except Exception as exc:
            if stop_event is not None and stop_event.is_set():
                return
            with run_lock(record['id']):
                if store.get('history', record['id']):
                    save_cache_update(store, record['id'], {
                        'checkpoint_sync_error': str(exc), 'checkpoint_retry_at': time.time() + 60})
