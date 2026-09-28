import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .paths import export_basename
from .sync import sync_history


def enrich(record):
    root = Path(record['cache_dir'])
    try:
        parameters = json.loads((root / 'args.json').read_text())
    except (OSError, ValueError):
        parameters = {}
    record['parameters'] = parameters if isinstance(parameters, dict) else {}
    return record


def import_history(store, source, cache_root, name=None, run_id=None, synchronize=True, visibility='visible'):
    source = dict(source)
    source['kind'] = source.get('kind', source.get('source', 'local'))
    source['path'] = str(Path(source['path']).expanduser().resolve()) if source['kind'] == 'local' else source['path'].rstrip('/')
    if not source['path'].startswith('/'):
        raise ValueError('实验目录必须为绝对路径')
    source['ssh_alias'] = source.get('ssh_alias', source.get('alias', 'gpu'))
    source_key = json.dumps(source, sort_keys=True)
    existing = next((r for r in store.list('history') if r.get('source_key') == source_key or (run_id and r.get('run_id') == run_id)), None)
    if existing:
        existing['visibility'] = 'visible'
        return store.put('history', existing['id'], enrich(existing))
    identity = run_id or str(uuid.uuid4())
    name = name or Path(source['path']).name
    cache_root = Path(cache_root).resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    directory = export_basename(name, identity, {p.name for p in cache_root.iterdir()})
    record = {'id': identity, 'run_id': run_id, 'source': source, 'source_key': source_key,
              'name': name, 'display_name': name, 'visibility': visibility, 'notes': '', 'tags': [],
              'cache_dir': str(cache_root / directory), 'sync_status': 'pending', 'status': 'imported',
              'created_at': datetime.now(timezone.utc).isoformat()}
    try:
        if synchronize:
            record.update(sync_history(record, cache_root))
    except (OSError, ValueError, RuntimeError) as exc:
        if source['kind'] == 'local':
            raise ValueError(str(exc)) from exc
        record.update(sync_status='pending', sync_error=str(exc), warnings=[str(exc)])
    return store.put('history', identity, enrich(record))
