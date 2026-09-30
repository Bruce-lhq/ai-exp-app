import json
import uuid
import math
from datetime import datetime, timezone
from pathlib import Path

from .paths import export_basename
from .sync import sync_history, run_lock


def parameter_fields(parameters):
    fields = set(parameters) - {'training', 'runtime'}
    for group in ('training', 'runtime'):
        if isinstance(parameters.get(group), dict):
            fields.update(parameters[group])
    return fields


def enrich(record):
    root = Path(record['cache_dir'])
    try:
        parameters = json.loads((root / 'args.json').read_text())
    except (OSError, ValueError):
        parameters = {}
    # launcher training omits inactive CA fields from args/model_config.
    # Restore the disabled switch before editor validation fills current defaults.
    if isinstance(parameters, dict) and parameters.get('backbone') in {'wonn', 'llt', 's1llt'} and 'ca_lambda' not in parameters:
        try:
            model = json.loads((root / 'model_config.json').read_text())
        except (OSError, ValueError):
            model = None
        if isinstance(model, dict):
            parameters['ca_lambda'] = model.get('ca_lambda', 0.0)
    def safe(value):
        if isinstance(value, float) and not math.isfinite(value): return None
        if isinstance(value, dict): return {k: safe(v) for k, v in value.items()}
        if isinstance(value, list): return [safe(v) for v in value]
        return value
    record['content_revision'] = [(name, (root / name).stat().st_mtime_ns, (root / name).stat().st_size)
                                  for name in ('args.json', 'metrics.jsonl', 'train.log') if (root / name).is_file()]
    parameters = safe(parameters) if isinstance(parameters, dict) else {}
    record['original_parameters'] = parameters
    record['parameter_original_fields'] = sorted(parameter_fields(parameters))
    try:
        imported = json.loads((root / 'parameter_annotations.json').read_text())
    except (OSError, ValueError):
        imported = {}
    annotations = {**(imported if isinstance(imported, dict) else {}), **record.get('parameter_annotations', {})}
    record['parameter_annotations'] = {k: v.strip() for k, v in annotations.items()
                                       if isinstance(v, str) and k not in record['parameter_original_fields']}
    record['parameters'] = {**parameters, **record['parameter_annotations']}
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
        with run_lock(existing['id']):
            existing = store.get('history', existing['id'])
            existing['visibility'] = 'visible'
            if synchronize:
                existing.update(sync_history(existing, cache_root))
                existing.update(sync_failures=0, next_retry_at=0)
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
