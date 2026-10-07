from ai_exp_app.db import Store
from ai_exp_app.workspace_sync import SyncEngine


def pair(tmp_path):
    hub_store = Store(tmp_path / 'hub.sqlite')
    client_store = Store(tmp_path / 'client.sqlite')
    def history_factory(data):
        return {'cache_dir': str(tmp_path / 'cache'), 'source': {**data['source'], 'ssh_alias': 'my-gpu'}, 'sync_status': 'pending'}
    def project_factory(data):
        return {'ssh_alias': 'my-gpu', 'config': {'python': '/device/python'}}
    hub = SyncEngine(hub_store, history_factory=history_factory, project_factory=project_factory)
    client = SyncEngine(client_store, history_factory=history_factory, project_factory=project_factory)
    return hub_store, client_store, hub, client


def test_remote_history_dedupes_preserving_each_cache_and_local_id(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    for store, identity, cache, alias in [(hs, 'phone', '/gpu/cache', 'local'), (cs, 'mac', '/mac/cache', 'gpu')]:
        store.put('history', identity, {'id': identity, 'name': 'experiment', 'notes': '', 'visibility': 'visible', 'source': {'kind': 'remote', 'path': '/runs/a/', 'ssh_alias': alias}, 'cache_dir': cache, 'parameters': {'secret_derived': 42}})
    assert not client.reconcile(hub.exchange)['conflicts']
    row = cs.get('history', 'mac'); row['notes'] = 'changed on Mac'; cs.put('history', 'mac', row)
    client.reconcile(hub.exchange)
    assert hs.get('history', 'phone')['notes'] == 'changed on Mac'
    assert hs.get('history', 'phone')['cache_dir'] == '/gpu/cache'
    assert hs.get('history', 'phone')['source']['ssh_alias'] == 'local'
    assert len(cs.list('history')) == 1
    assert 'parameters' not in hub.exchange({'changes': []})['records'][0]['data']


def test_initial_preset_conflicts_preserve_both_and_project_references(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    for store, project, value in [(hs, 'p1', .01), (cs, 'p2', .02)]:
        store.put('projects', project, {'id': project, 'name': 'project', 'remote_path': '/code', 'ssh_alias': 'gpu'})
        store.put('presets', 'same', {'id': 'same', 'project_id': project, 'name': 'base', 'parameters': {'training': {'lr': value}, 'runtime': {'gpu_count': 1}}})
    client.reconcile(hub.exchange)
    assert len(cs.list('projects')) == 1
    assert len(cs.list('presets')) == 2
    assert {p['parameters']['training']['lr'] for p in cs.list('presets')} == {.01, .02}
    assert all(p['project_id'] == 'p2' for p in cs.list('presets'))


def test_simultaneous_edit_reports_conflict_and_explicit_remote_resolution(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    hs.put('templates', 'default', {'id': 'default', 'name': 'initial', 'columns': []})
    client.reconcile(hub.exchange)
    hs.put('templates', 'default', {'id': 'default', 'name': 'phone', 'columns': []})
    cs.put('templates', 'default', {'id': 'default', 'name': 'mac', 'columns': []})
    result = client.reconcile(hub.exchange)
    assert len(result['conflicts']) == 1
    assert cs.get('templates', 'default')['name'] == 'mac'
    client.resolve(result['conflicts'][0]['id'], 'remote')
    assert cs.get('templates', 'default')['name'] == 'phone'
    assert not client.reconcile(hub.exchange)['conflicts']


def test_delete_does_not_resurrect_when_reconnecting(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    hs.put('templates', 'default', {'id': 'default', 'name': 'default', 'columns': []})
    client.reconcile(hub.exchange)
    cs.delete('templates', 'default')
    client.reconcile(hub.exchange)
    assert hs.get('templates', 'default') is None
    assert cs.get('templates', 'default') is None
    client.reconcile(hub.exchange)
    assert not cs.list('templates')


def test_only_shared_preferences_and_last_run_parameters_are_transmitted(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    cs.put('projects', 'p', {'id': 'p', 'name': 'project', 'remote_path': '/code', 'ssh_alias': 'private', 'config': {'password': 'secret'}})
    cs.put('preferences', 'parameters:p', {'aliases': {'lr': 'learning rate'}, 'stars': ['lr'], 'theme': 'dark', 'ssh_alias': 'private'})
    cs.put('preferences', 'theme', {'value': 'dark'})
    cs.put('preferences', 'workspace', {'default_project_id': 'p', 'local_path': '/my/mac'})
    cs.put('last_runs', 'p', {'parameters': {'training': {'lr': .01}, 'runtime': {'gpu_count': 2}}, 'run_id': 'local-run', 'started_seq': 54})
    client.reconcile(hub.exchange)
    project = hs.list('projects')[0]
    assert project['ssh_alias'] == 'my-gpu'
    assert project['config'] == {'python': '/device/python'}
    assert hs.get('preferences', 'parameters:' + project['id']) == {'aliases': {'lr': 'learning rate'}, 'stars': ['lr']}
    assert hs.get('preferences', 'theme') is None
    assert hs.get('preferences', 'workspace') == {'default_project_id': project['id']}
    assert hs.get('last_runs', project['id']) == {'parameters': {'training': {'lr': .01}, 'runtime': {'gpu_count': 2}}}


def test_network_failure_keeps_pending_and_local_import_is_reported(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    cs.put('history', 'local', {'id': 'local', 'source': {'kind': 'local', 'path': '/mac/secret'}, 'cache_dir': '/mac/secret'})
    cs.put('templates', 'default', {'id': 'default', 'name': 'offline', 'columns': []})
    def fail(request):
        raise OSError('offline')
    try:
        client.reconcile(fail)
    except OSError:
        pass
    assert client.status()['pending'] == 1
    assert client.status()['local_only_count'] == 1
    assert not hs.list('history')
    assert not client.reconcile(hub.exchange)['pending']


def test_edit_during_exchange_is_not_overwritten(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    cs.put('templates', 'default', {'id': 'default', 'name': 'before', 'columns': []})
    def exchange(request):
        result = hub.exchange(request)
        cs.put('templates', 'default', {'id': 'default', 'name': 'during', 'columns': []})
        return result
    assert client.reconcile(exchange)['pending'] == 1
    assert cs.get('templates', 'default')['name'] == 'during'
    client.reconcile(hub.exchange)
    assert hs.get('templates', 'default')['name'] == 'during'


def test_shared_chart_appearance_maps_history_ids_without_sharing_theme(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    for store, identity in [(hs, 'phone'), (cs, 'mac')]:
        store.put('history', identity, {'id': identity, 'name': 'experiment', 'source': {'kind': 'remote', 'path': '/runs/a'}, 'cache_dir': '/cache/' + identity})
    cs.put('preferences', 'shared_view:analysis', {'settings': {'metric': 'val_ppl', 'title': 'Comparison', 'theme': 'dark'}, 'appearance': {'mac': {'name': 'my legend', 'color': '#ff0000', 'order': 1}}})
    client.reconcile(hub.exchange)
    view = hs.get('preferences', 'shared_view:analysis')
    assert view['appearance'] == {'phone': {'name': 'my legend', 'color': '#ff0000', 'order': 1}}
    assert 'theme' not in view['settings']
    assert not client.status()['pending']


def test_local_choice_uses_new_revision_and_survives_restart(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    hs.put('templates', 'default', {'id': 'default', 'name': 'initial', 'columns': []})
    client.reconcile(hub.exchange)
    hs.put('templates', 'default', {'id': 'default', 'name': 'phone', 'columns': []})
    cs.put('templates', 'default', {'id': 'default', 'name': 'mac', 'columns': []})
    conflict = client.reconcile(hub.exchange)['conflicts'][0]
    client = SyncEngine(cs)
    client.resolve(conflict['id'], 'local')
    assert not client.reconcile(hub.exchange)['pending']
    assert hs.get('templates', 'default')['name'] == 'mac'


def test_hub_transaction_rejects_unsafe_request_without_partial_write(tmp_path):
    import pytest
    hs, cs, hub, client = pair(tmp_path)
    cs.put('templates', 'default', {'id': 'default', 'name': 'initial', 'columns': []})
    def bad(request):
        first = request['changes'][0]
        return hub.exchange({'changes': [first, {**first, 'data': {**first['data'], 'cache_dir': '/my/private/path'}}]})
    with pytest.raises(ValueError, match='unsupported fields'):
        client.reconcile(bad)
    assert not hs.list('templates')
    assert not hs.list('_workspace_shared')


def test_remote_project_configuration_syncs_without_overwriting_device_credentials(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    for store, identity in [(hs, 'phone'), (cs, 'mac')]:
        store.put('projects', identity, {'id': identity, 'name': 'project', 'remote_path': '/code', 'config': {'python': '/remote/python', 'integration': {'command': ['train.py'], 'environment': {'PASSWORD': identity}}}})
    client.reconcile(hub.exchange)
    assert not client.status()['conflicts']
    record = cs.get('projects', 'mac')
    record['config']['python'] = '/remote/new-python'
    cs.put('projects', 'mac', record)
    client.reconcile(hub.exchange)
    remote = hs.get('projects', 'phone')
    assert remote['config']['python'] == '/remote/new-python'
    assert remote['config']['integration']['environment'] == {'PASSWORD': 'phone'}
    assert 'PASSWORD' not in str(hub.exchange({'changes': []}))


def test_initial_history_name_disagreement_is_explicit_and_not_overwritten(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    for store, identity, name in [(hs, 'phone', 'phone name'), (cs, 'mac', 'mac name')]:
        store.put('history', identity, {'id': identity, 'name': name, 'source': {'kind': 'remote', 'path': '/runs/a'}, 'cache_dir': '/cache/' + identity})
    result = client.reconcile(hub.exchange)
    assert len(result['conflicts']) == 1
    assert hs.get('history', 'phone')['name'] == 'phone name'
    assert cs.get('history', 'mac')['name'] == 'mac name'


def test_deleted_history_keeps_device_cache_but_syncs_hidden_state(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    hs.put('history', 'phone', {'id': 'phone', 'name': 'experiment', 'source': {'kind': 'remote', 'path': '/runs/a'}, 'cache_dir': '/gpu/cache'})
    client.reconcile(hub.exchange)
    local = cs.list('history')[0]
    local['visibility'] = 'removed'
    cs.put('history', local['id'], local)
    client.reconcile(hub.exchange)
    assert hs.get('history', 'phone')['visibility'] == 'removed'
    assert hs.get('history', 'phone')['cache_dir'] == '/gpu/cache'
    assert not client.reconcile(hub.exchange)['pending']


def test_history_tombstone_stays_stable_and_explicit_reimport_restores(tmp_path):
    hs, cs, hub, client = pair(tmp_path)
    hs.put('history', 'phone', {'id': 'phone', 'name': 'experiment', 'source': {'kind': 'remote', 'path': '/runs/a'}, 'cache_dir': '/gpu/cache'})
    client.reconcile(hub.exchange)
    local = cs.list('history')[0]
    local.update(name='renamed before removal', visibility='removed')
    cs.put('history', local['id'], local)
    client.reconcile(hub.exchange)
    revisions = [hub.status()['revision'], client.status()['revision']]
    for _ in range(3):
        assert client.reconcile(hub.exchange)['pending'] == 0
        assert [hub.status()['revision'], client.status()['revision']] == revisions
    assert hs.get('history', 'phone')['name'] == 'renamed before removal'
    local = cs.get('history', local['id']);local['visibility'] = 'visible';cs.put('history', local['id'], local)
    assert not client.reconcile(hub.exchange)['pending']
    assert hs.get('history', 'phone')['visibility'] == 'visible'


def test_other_hosts_with_same_paths_remain_local(tmp_path):
    from ai_exp_app.config import Config
    hs, cs, hub, client = pair(tmp_path)
    for store, identity, alias in [(hs, 'phone', 'primary'), (cs, 'mac', 'primary')]:
        store.config = Config.load(tmp_path / identity)
        store.config.save_local_settings({'ssh_alias': alias})
        store.put('projects', identity, {'id': identity, 'name': 'primary project', 'remote_path': '/code', 'ssh_alias': alias})
    cs.put('projects', 'other', {'id': 'other', 'name': 'different GPU', 'remote_path': '/code', 'ssh_alias': 'other'})
    cs.put('history', 'other', {'id': 'other', 'name': 'different experiment', 'source': {'kind': 'remote', 'path': '/runs/a', 'ssh_alias': 'other'}, 'cache_dir': '/other/cache'})
    assert not client.reconcile(hub.exchange)['conflicts']
    assert len(hs.list('projects')) == 1 and not hs.list('history')
    assert cs.get('projects', 'other')['name'] == 'different GPU'
    assert client.status()['other_host_count'] == 2
