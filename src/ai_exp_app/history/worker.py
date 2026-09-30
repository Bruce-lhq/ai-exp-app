import time
from .importer import enrich, import_history
from .repository import TERMINAL
from .sync import run_lock, sync_history


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
            needs_checkpoint = record.get('status') in TERMINAL and 'latest.pt' not in record.get('files', []) and not any('没有 latest.pt' in w for w in record.get('warnings', []))
            if record.get('sync_status') == 'synced' and record.get('status') not in {'running', 'stopping', 'starting'} and not needs_checkpoint:
                continue
            alias = record['source'].get('ssh_alias', 'gpu') if record['source']['kind'] == 'remote' else None
            if record.get('next_retry_at', 0) > time.time() or (alias and alias in failed_aliases):
                continue
            try:
                record.update(sync_history(record, cache_root))
                record.update(sync_failures=0, next_retry_at=0)
                enrich(record)
            except Exception as exc:
                failures = record.get('sync_failures', 0) + 1
                record.update(sync_status='pending', sync_error=str(exc), sync_failures=failures,
                              next_retry_at=time.time() + min(300, 2 ** min(failures, 8)))
                if alias:
                    failed_aliases.add(alias)
            store.put('history', record['id'], record)
