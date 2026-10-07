"""Revisioned workspace metadata exchange. Experiment files and device settings stay local."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import uuid


KINDS = ('projects', 'history', 'presets', 'templates', 'preferences', 'last_runs', 'shared_view')
PROJECT_CONFIG = ('python', 'runs_root', 'data_root', 'integration', 'exclusions')
CHART_SETTINGS = ('metric', 'xAxis', 'title', 'xLabel', 'yLabel', 'xScale', 'yScale', 'width', 'height', 'pixelRatio', 'xMin', 'xMax', 'yMin', 'yMax')


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _identity(kind, key):
    return hashlib.sha256((kind + ':' + key).encode()).hexdigest()


class _Documents:
    def __init__(self, db):
        self.db = db

    def rows(self, kind):
        return [(key, json.loads(data)) for key, data in self.db.execute('SELECT id,data FROM documents WHERE kind=? ORDER BY rowid', (kind,))]

    def get(self, kind, key):
        row = self.db.execute('SELECT data FROM documents WHERE kind=? AND id=?', (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, kind, key, data):
        self.db.execute('INSERT INTO documents VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data', (kind, key, _dump(data)))

    def delete(self, kind, key):
        self.db.execute('DELETE FROM documents WHERE kind=? AND id=?', (kind, key))


class SyncEngine:
    def __init__(self, store, history_factory=None, project_factory=None):
        self.store = store
        self.history_factory = history_factory
        self.project_factory = project_factory

    def _state(self, docs):
        return docs.get('_workspace_sync', 'state') or {'entries': {}, 'conflicts': {}, 'last_synced': None}

    def _project_id(self, state, local_id):
        entry = state['entries'].get('projects|' + str(local_id))
        return entry['id'] if entry else None

    def _view(self, data, state, incoming=False):
        value = {}
        if 'settings' in data:
            value['settings'] = {k: deepcopy(data['settings'][k]) for k in CHART_SETTINGS if k in data['settings']}
        if 'appearance' in data:
            mapping = {e['id'] if incoming else e['local_id']: e['local_id'] if incoming else e['id']
                       for e in state['entries'].values() if e['kind'] == 'history'}
            value['appearance'] = {mapping.get(key, key): {k: deepcopy(item[k]) for k in ('name', 'color', 'order') if k in item}
                                   for key, item in data['appearance'].items()}
        return value

    def _projection(self, kind, local_id, data, state):
        if kind == 'projects':
            if not data.get('remote_path'):
                return None
            key = data['remote_path'].rstrip('/')
            value = {k: deepcopy(data[k]) for k in ('name', 'favorite', 'code') if k in data}
            value['remote_path'] = key
            config = {k: deepcopy(data.get('config', {})[k]) for k in PROJECT_CONFIG if k in data.get('config', {})}
            if config:
                # Credentials supplied through the project environment remain device-local.
                if isinstance(config.get('integration'), dict):
                    config['integration'].pop('environment', None)
                value['config'] = config
        elif kind == 'history':
            source = data.get('source', {})
            if source.get('kind') != 'remote':
                return None
            key = source['path'].rstrip('/')
            value = {k: deepcopy(data[k]) for k in ('name', 'display_name', 'visibility', 'notes', 'tags', 'parameter_annotations') if k in data}
            value['source'] = {'kind': 'remote', 'path': key}
            # Redundant display_name/default fields must not create false initial conflicts.
            value['name'] = value.get('name', value.get('display_name', key.rsplit('/', 1)[-1]))
            value['display_name'] = value['name']
            value.setdefault('visibility', 'visible')
            value.setdefault('notes', '')
            value.setdefault('tags', [])
            value.setdefault('parameter_annotations', {})
        elif kind == 'presets':
            project = self._project_id(state, data.get('project_id'))
            if not project:
                return None
            value = {k: deepcopy(data[k]) for k in ('name', 'parameters')}
            value['project_id'] = project
            key = _dump(value)
        elif kind == 'templates':
            value = {k: deepcopy(data[k]) for k in ('name', 'columns') if k in data}
            key = 'default' if local_id == 'default' else _dump(value)
        elif kind == 'last_runs':
            key = self._project_id(state, local_id)
            if not key:
                return None
            value = {'parameters': deepcopy(data.get('parameters', {}))}
        elif kind == 'preferences':
            if local_id.startswith('parameters:'):
                project = self._project_id(state, local_id.removeprefix('parameters:'))
                if not project:
                    return None
                key = 'parameters:' + project
                value = {k: deepcopy(data[k]) for k in ('aliases', 'stars', 'tags', 'order') if k in data}
            elif local_id == 'workspace':
                project = self._project_id(state, data.get('default_project_id'))
                if not project:
                    return None
                key, value = 'workspace', {'default_project_id': project}
            elif local_id.startswith('shared_view:'):
                key, value = local_id, self._view(data, state)
            else:
                return None
        elif kind == 'shared_view':
            key, value = local_id, self._view(data, state)
        else:
            return None
        return key, value

    def _scan(self, docs, state):
        current = {}
        excluded = set()
        config = getattr(self.store, 'config', None)
        alias = config.local_settings['ssh_alias'] if config else None
        for kind in KINDS:
            for local_id, data in docs.rows(kind):
                host = data.get('ssh_alias') if kind == 'projects' else data.get('source', {}).get('ssh_alias') if kind == 'history' else None
                if alias and host and host != alias:
                    excluded.add(kind + '|' + local_id)
                    continue
                projection = self._projection(kind, local_id, data, state)
                if projection is None:
                    continue
                key, value = projection
                local_key = kind + '|' + local_id
                entry = state['entries'].setdefault(local_key, {'id': _identity(kind, key), 'kind': kind, 'key': key,
                    'local_id': local_id, 'revision': 0, 'baseline': None, 'deleted': False})
                deleted = kind == 'history' and value.get('visibility') == 'removed'
                current[local_key] = {'id': entry['id'], 'kind': kind, 'key': entry['key'],
                    'data': value, 'deleted': deleted, 'base_revision': entry['revision']}
        for local_key, entry in state['entries'].items():
            if local_key not in current and local_key not in excluded:
                current[local_key] = {'id': entry['id'], 'kind': entry['kind'], 'key': entry['key'],
                    'data': None, 'deleted': True, 'base_revision': entry['revision']}
        return current

    def _changes(self, current, state):
        return [item for local_key, item in current.items()
                if not (item['deleted'] and state['entries'][local_key]['deleted'])
                and (item['data'] != state['entries'][local_key]['baseline'] or item['deleted'] != state['entries'][local_key]['deleted'])]

    def _local_project(self, state, shared_id):
        return next((e['local_id'] for e in state['entries'].values() if e['kind'] == 'projects' and e['id'] == shared_id), None)

    def _apply(self, docs, state, record):
        kind, shared_id = record['kind'], record['id']
        entries = [(key, entry) for key, entry in state['entries'].items() if entry['id'] == shared_id]
        if not entries:
            if record['deleted']:
                return
            key = record['key']
            if kind == 'last_runs':
                local_id = self._local_project(state, key)
            elif kind == 'preferences':
                local_id = ('parameters:' + str(self._local_project(state, key.removeprefix('parameters:')))) if key.startswith('parameters:') else key
            else:
                local_id = 'default' if kind == 'templates' and key == 'default' else str(uuid.uuid4())
            if not local_id:
                return
            entry = {'id': shared_id, 'kind': kind, 'key': key, 'local_id': local_id, 'revision': 0, 'baseline': None, 'deleted': False}
            local_key = kind + '|' + local_id
            state['entries'][local_key] = entry
            entries = [(local_key, entry)]
        for local_key, entry in entries:
            local_id = entry['local_id']
            if record['deleted']:
                if kind == 'history' and (old := docs.get(kind, local_id)):
                    data = deepcopy(record.get('data') or {})
                    if 'source' in data:
                        data['source'] = {**old.get('source', {}), **data['source']}
                        data['source_key'] = json.dumps(data['source'], sort_keys=True)
                    docs.put(kind, local_id, {**old, **data, 'visibility': 'removed'})
                else:
                    docs.delete(kind, local_id)
            else:
                data = deepcopy(record['data'])
                old = docs.get(kind, local_id)
                if old is None:
                    if kind == 'history':
                        if self.history_factory is None:
                            raise ValueError('A local history cache factory is required to receive new history')
                        old = self.history_factory({**deepcopy(data), 'id': local_id})
                    elif kind == 'projects':
                        old = self.project_factory({**deepcopy(data), 'id': local_id}) if self.project_factory else {'ssh_alias': 'gpu'}
                    else:
                        old = {}
                if kind == 'history':
                    data['source'] = {**old.get('source', {}), **data['source']}
                    data['source_key'] = json.dumps(data['source'], sort_keys=True)
                elif kind == 'presets':
                    data['project_id'] = self._local_project(state, data['project_id'])
                elif kind == 'preferences' and entry['key'] == 'workspace':
                    data['default_project_id'] = self._local_project(state, data['default_project_id'])
                elif kind == 'shared_view' or kind == 'preferences' and entry['key'].startswith('shared_view:'):
                    data = self._view(data, state, incoming=True)
                if kind == 'projects' and ('config' in data or 'config' in (entry['baseline'] or {})):
                    local_config = deepcopy(old.get('config', {}))
                    environment = local_config.get('integration', {}).get('environment') if isinstance(local_config.get('integration'), dict) else None
                    for field in (entry['baseline'] or {}).get('config', {}):
                        local_config.pop(field, None)
                    local_config.update(data.get('config', {}))
                    if environment is not None:
                        local_config.setdefault('integration', {})['environment'] = environment
                    data['config'] = local_config
                if kind in {'history', 'projects', 'presets', 'templates'}:
                    data['id'] = local_id
                # Remove shared keys omitted remotely, while preserving all device-only keys.
                previous = entry['baseline'] or {}
                for field in previous:
                    old.pop(field, None)
                docs.put(kind, local_id, {**old, **data})
            entry.update(revision=record['revision'], baseline=deepcopy(record['data']), deleted=record['deleted'])

    def exchange(self, request):
        """Hub endpoint: scan local edits and CAS-merge client metadata in one SQLite transaction."""
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            docs = _Documents(db)
            state = self._state(docs)
            for change in self._changes(self._scan(docs, state), state):
                existing = docs.get('_workspace_shared', change['id'])
                record = {**change, 'revision': (existing or {}).get('revision', 0) + 1}
                record.pop('base_revision')
                docs.put('_workspace_shared', record['id'], record)
                for entry in state['entries'].values():
                    if entry['id'] == record['id']:
                        entry.update(revision=record['revision'], baseline=deepcopy(record['data']), deleted=record['deleted'])
            conflicts = []
            for change in request.get('changes', []):
                if change.get('kind') not in KINDS or not isinstance(change.get('key'), str) or change.get('id') != _identity(change['kind'], change['key']):
                    raise ValueError('Invalid shared document identity')
                # Reject device-only fields even if a caller bypasses normal scan projection.
                probe = self._incoming_projection(change)
                if probe != change.get('data'):
                    raise ValueError('Shared document contains unsupported fields')
                existing = docs.get('_workspace_shared', change['id'])
                revision = (existing or {}).get('revision', 0)
                equivalent = existing is not None and existing['data'] == change['data'] and existing['deleted'] == change['deleted']
                if change.get('base_revision') != revision and not equivalent:
                    conflicts.append({'id': change['id'], 'kind': change['kind'], 'name': (change.get('data') or {}).get('name', change['key']),
                        'local': deepcopy(change), 'remote': deepcopy(existing)})
                    continue
                if not equivalent:
                    record = {**change, 'revision': revision + 1}
                    record.pop('base_revision')
                    docs.put('_workspace_shared', record['id'], record)
            records = [data for _, data in docs.rows('_workspace_shared')]
            for kind in KINDS:
                for record in records:
                    if record['kind'] == kind:
                        self._apply(docs, state, record)
            state['last_synced'] = datetime.now(timezone.utc).isoformat()
            docs.put('_workspace_sync', 'state', state)
            return {'records': records, 'conflicts': conflicts}

    def _incoming_projection(self, change):
        if change.get('deleted') and change.get('data') is None:
            return None
        # Foreign project identifiers are shared IDs, not local IDs.
        state = {'entries': {}}
        for project in [change.get('data', {}).get('project_id'), change.get('data', {}).get('default_project_id'), change['key'].removeprefix('parameters:')]:
            if project:
                state['entries']['projects|' + project] = {'id': project, 'kind': 'projects', 'local_id': project}
        projection = self._projection(change['kind'], change['key'], change['data'], state)
        return projection[1] if projection else None

    def reconcile(self, callback):
        """Client: exchange a snapshot, then preserve any edits made while the network was busy."""
        with self.store.connection() as db:
            docs = _Documents(db)
            state = self._state(docs)
            current = self._scan(docs, state)
            changes = self._changes(current, state)
            docs.put('_workspace_sync', 'state', state)
        response = callback({'changes': changes})
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            docs = _Documents(db)
            state = self._state(docs)
            now = self._scan(docs, state)
            conflicts = {c['id']: c for c in response.get('conflicts', [])}
            for kind in KINDS:
                for record in response['records']:
                    if record['kind'] != kind or record['id'] in conflicts:
                        continue
                    changed_during = [key for key, item in now.items() if item['id'] == record['id'] and item != current.get(key)]
                    if changed_during:
                        for key in changed_during:
                            state['entries'][key].update(revision=record['revision'], baseline=deepcopy(record['data']), deleted=record['deleted'])
                    else:
                        self._apply(docs, state, record)
            state['conflicts'] = conflicts
            state['last_synced'] = datetime.now(timezone.utc).isoformat()
            docs.put('_workspace_sync', 'state', state)
        return self.status()

    def status(self):
        with self.store.connection() as db:
            docs = _Documents(db)
            state = self._state(docs)
            pending = self._changes(self._scan(docs, state), state)
            local_only = sum(data.get('source', {}).get('kind') == 'local' for _, data in docs.rows('history'))
            config = getattr(self.store, 'config', None)
            alias = config.local_settings['ssh_alias'] if config else None
            other_hosts = sum(bool(alias and host and host != alias)
                              for kind in ('projects', 'history') for _, data in docs.rows(kind)
                              for host in [data.get('ssh_alias') if kind == 'projects' else data.get('source', {}).get('ssh_alias')])
            return {'conflicts': list(state['conflicts'].values()), 'pending': len(pending),
                    'last_synced': state['last_synced'], 'local_only_count': local_only, 'other_host_count': other_hosts,
                    'revision': sum(e['revision'] for e in state['entries'].values())}

    def resolve(self, shared_id, choice):
        if choice not in {'local', 'remote'}:
            raise ValueError('Resolution must choose local or remote')
        with self.store.connection() as db:
            docs = _Documents(db)
            state = self._state(docs)
            conflict = state['conflicts'].get(shared_id)
            if conflict is None:
                raise ValueError('Conflict no longer exists')
            remote = conflict['remote']
            if choice == 'remote' and remote is not None:
                self._apply(docs, state, remote)
            else:
                for entry in state['entries'].values():
                    if entry['id'] == shared_id:
                        entry['revision'] = (remote or {}).get('revision', 0)
            del state['conflicts'][shared_id]
            docs.put('_workspace_sync', 'state', state)
        return self.status()
