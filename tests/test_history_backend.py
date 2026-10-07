import json
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ai_exp_app.db import Store
from ai_exp_app.history.api import create_router
from ai_exp_app.history.importer import import_history
from ai_exp_app.history.sync import replace_complete_file, sync_history
from ai_exp_app.history.worker import sync_once


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / 'db.sqlite')
    cache = tmp_path / 'gpu_downloads'
    source = tmp_path / 'original'
    source.mkdir()
    (source / 'args.json').write_text('{"lr":0.001}')
    (source / 'metrics.jsonl').write_text('{"event":"validation","tokens_seen":100,"perplexity":42}\n')
    (source / 'latest.pt').write_bytes(b'checkpoint must not be copied')
    app = FastAPI()
    app.include_router(create_router(store, cache))
    return store, cache, source, TestClient(app)


def test_import_identity_rename_export_and_tombstone(setup):
    store, cache, source, client = setup
    record = client.post('/api/history/import', json={'source':'local', 'path':str(source), 'name':'experiment'}).json()
    identity = record['id']
    assert record['parameters']['lr'] == .001
    assert not (Path(record['cache_dir']) / 'latest.pt').exists()
    renamed = client.patch('/api/history/' + identity, json={'name':'新名称'}).json()
    assert Path(renamed['cache_dir']).name == '新名称'
    assert source.exists()
    import io, zipfile
    archive = zipfile.ZipFile(io.BytesIO(client.get(f'/api/history/{identity}/export').content))
    assert '新名称/args.json' in archive.namelist()
    client.delete('/api/history/' + identity)
    assert client.get('/api/history').json() == []
    restored = client.post('/api/history/import', json={'source':'local', 'path':str(source)}).json()
    assert restored['id'] == identity


def test_atomic_interrupt_preserves_old(tmp_path):
    file = tmp_path / 'metrics.jsonl'
    file.write_bytes(b'old')
    def chunks():
        yield b'new'
        raise ConnectionError('offline')
    with pytest.raises(ConnectionError):
        replace_complete_file(file, chunks())
    assert file.read_bytes() == b'old'
    assert not list(tmp_path.glob('.download-*'))


def test_same_name_no_overwrite_and_symlink_rejected(setup):
    store, cache, source, client = setup
    a = import_history(store, {'kind':'local','path':str(source)}, cache, 'same')
    other = source.parent / 'other'
    other.mkdir()
    (other / 'metrics.jsonl').symlink_to(source / 'metrics.jsonl')
    b = import_history(store, {'kind':'local','path':str(other)}, cache, 'same')
    assert a['cache_dir'] != b['cache_dir']
    assert not (Path(b['cache_dir']) / 'metrics.jsonl').exists()


def test_deletion_requires_unchanged_preview_and_only_cache(setup):
    store, cache, source, client = setup
    record = import_history(store, {'kind':'local','path':str(source)}, cache)
    endpoint = f"/api/history/{record['id']}"
    preview = client.post(endpoint + '/delete-preview', json={'scope':'local'}).json()
    (Path(record['cache_dir']) / 'args.json').write_text('{}')
    assert client.post(endpoint + '/delete-confirm', json=preview).status_code == 409
    preview = client.post(endpoint + '/delete-preview', json={'scope':'local'}).json()
    assert client.post(endpoint + '/delete-confirm', json=preview).status_code == 200
    assert source.exists()
    assert not Path(record['cache_dir']).exists()


def test_removed_terminal_not_readded(setup):
    store, cache, source, client = setup
    record = import_history(store, {'kind':'local','path':str(source)}, cache, run_id='run1')
    client.delete('/api/history/run1')
    store.put('runs','run1',{'id':'run1','status':'completed','run_dir':'/unused'})
    sync_once(store, cache)
    assert store.get('history','run1')['visibility'] == 'removed'


def test_unchanged_sync_does_not_replace_files(setup):
    store, cache, source, client = setup
    record = import_history(store, {'kind':'local','path':str(source)}, cache)
    target = Path(record['cache_dir']) / 'metrics.jsonl'
    inode, mtime = target.stat().st_ino, target.stat().st_mtime_ns
    sync_history(record, cache)
    assert (target.stat().st_ino, target.stat().st_mtime_ns) == (inode, mtime)
    (source / 'metrics.jsonl').write_text('{}\n')
    record.update(sync_history(record, cache))
    assert target.read_text() == '{}\n'


def test_sync_retry_keeps_cache_and_archive(setup, monkeypatch):
    store, cache, source, client = setup
    record = import_history(store, {'kind':'local','path':str(source)}, cache)
    record['visibility'] = 'archived'
    record['sync_status'] = 'pending'
    store.put('history',record['id'],record)
    import ai_exp_app.history.worker as worker
    real_sync = worker.sync_history
    def offline(*args):
        raise ConnectionError('offline')
    monkeypatch.setattr(worker, 'sync_history', offline)
    worker.sync_once(store, cache)
    failed = store.get('history',record['id'])
    assert failed['sync_status'] == 'pending' and failed['next_retry_at'] > 0
    assert failed['visibility'] == 'archived'
    assert (Path(record['cache_dir']) / 'args.json').exists()
    failed['next_retry_at'] = 0
    store.put('history',failed['id'],failed)
    monkeypatch.setattr(worker, 'sync_history', real_sync)
    worker.sync_once(store, cache)
    assert store.get('history',record['id'])['sync_status'] == 'synced'


def test_missing_selection_does_not_break_series_and_switch_restores(setup):
    store, cache, source, client = setup
    record = import_history(store, {'kind':'local','path':str(source)}, cache)
    payload = {'history_ids':[record['id'],'missing'], 'metric':'train_ppl'}
    missing = client.post('/api/analysis/series',json=payload).json()
    assert missing['series'] == [] and missing['warnings']
    payload['metric'] = 'val_ppl'
    result = client.post('/api/analysis/series',json=payload).json()
    assert result['series'][0]['id'] == record['id']
    assert payload['history_ids'] == [record['id'],'missing']
    table = client.post('/api/analysis/table',json={'history_ids':[record['id'],'missing']})
    assert table.status_code == 200 and table.json()['warnings']


def test_progress_regression_breaks_unknown_curve(setup):
    store, cache, source, client = setup
    (source/'metrics.jsonl').write_text(''.join(json.dumps({'event':'validation','tokens_seen':n,'perplexity':v})+'\n' for n,v in [(100,50),(200,40),(150,45)]))
    record = import_history(store, {'kind':'local','path':str(source)}, cache)
    result = client.post('/api/analysis/series',json={'history_ids':[record['id']]}).json()
    assert result['series'][0]['points'][2]['y'] is None
    assert any('回退' in w for w in result['warnings'])


def test_analysis_prefers_cached_history_for_external_run(setup, monkeypatch):
    store, cache, source, client = setup
    record = import_history(store, {'kind': 'local', 'path': str(source)}, cache, name='备注实验')
    store.put('runs', record['id'], {
        'id': record['id'], 'external': True, 'remote_path': '/remote/run',
        'ssh_alias': 'gpu', 'display_name': '远端原始名',
    })
    import ai_exp_app.analysis.api as analysis_api
    monkeypatch.setattr(analysis_api, 'remote', lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError('offline')))
    result = client.post('/api/analysis/series', json={
        'history_ids': [record['id']], 'metric': 'val_ppl',
    }).json()
    assert result['series'][0]['name'] == '备注实验'
    assert result['series'][0]['points'][0]['y'] == 42


def test_existing_parameter_is_readonly_and_missing_annotation_persists(setup):
    store, cache, source, client = setup
    record = import_history(store, {'kind': 'local', 'path': str(source)}, cache)
    endpoint = f"/api/history/{record['id']}/parameters"
    original = (Path(record['cache_dir']) / 'args.json').read_bytes()
    response = client.patch(endpoint, json={'field': 'lr', 'value': 'tampered'})
    assert response.status_code == 409
    response = client.patch(endpoint, json={'field': 'missing', 'value': '  arbitrary | 字符串  '})
    assert response.status_code == 200
    assert response.json()['parameters']['missing'] == 'arbitrary | 字符串'
    assert 'missing' not in response.json()['original_parameters']
    assert (Path(record['cache_dir']) / 'args.json').read_bytes() == original
    assert client.patch(endpoint, json={'field': 'missing', 'value': '  changed  '}).status_code == 200
    assert client.post('/api/history/refresh').status_code == 200
    fresh = client.get('/api/history').json()[0]
    assert fresh['parameters']['missing'] == 'changed'
    assert fresh['parameter_original_fields'] == ['lr']
    table = client.post('/api/analysis/table', json={'history_ids': [record['id']], 'columns': [
        {'id': 'missing', 'kind': 'parameter', 'field': 'missing', 'title': '补充'}]}).json()
    assert table['rows'][0][0] == 'changed'
    # If the source later supplies this field, the recorded value takes priority.
    (source / 'args.json').write_text('{"lr":0.001,"missing":null}')
    assert client.post('/api/history/refresh').status_code == 200
    fresh = client.get('/api/history').json()[0]
    assert fresh['parameters']['missing'] is None
    assert client.patch(endpoint, json={'field': 'missing', 'value': 'no'}).status_code == 409


def test_legacy_overrides_migrate_only_missing_values_and_restore_original(setup):
    store, cache, source, client = setup
    record = import_history(store, {'kind': 'local', 'path': str(source)}, cache)
    record['parameter_overrides'] = {'lr': 'wrong', 'missing': '  display only  '}
    (Path(record['cache_dir']) / 'args.json').write_text('{"lr":"wrong","missing":"display only"}')
    store.put('history', record['id'], record)
    client.post('/api/history/refresh')
    updated = store.get('history', record['id'])
    assert not updated.get('parameter_overrides')
    assert updated['parameter_annotations'] == {'missing': 'display only'}
    assert json.loads((Path(record['cache_dir']) / 'args.json').read_text()) == {'lr': .001}
    assert client.get('/api/history').json()[0]['parameters']['missing'] == 'display only'
    import io, zipfile
    archive = zipfile.ZipFile(io.BytesIO(client.get(f"/api/history/{record['id']}/export").content))
    assert json.loads(archive.read(f"{record['name']}/args.json")) == {'lr': .001}
    assert json.loads(archive.read(f"{record['name']}/parameter_annotations.json")) == {'missing': 'display only'}


def test_analysis_missing_cache_never_reads_remote(setup, monkeypatch):
    store, cache, source, client = setup
    store.put('runs', 'uncached', {'id': 'uncached', 'external': True})
    import ai_exp_app.analysis.api as analysis_api
    def offline(*args, **kwargs):
        raise AssertionError('分析页不应访问云端')
    monkeypatch.setattr(analysis_api, 'remote', offline)
    response = client.post('/api/analysis/series', json={'history_ids': ['uncached']})
    assert response.status_code == 200
    assert response.json()['series'] == []
    assert response.json()['warnings']


def test_parsed_cache_reused_and_invalidated_by_local_refresh(setup, monkeypatch):
    store, cache, source, client = setup
    record = import_history(store, {'kind': 'local', 'path': str(source)}, cache)
    import ai_exp_app.analysis.api as analysis_api
    original = analysis_api.read_metrics
    reads = []
    def counted(*args):
        reads.append(args[0])
        return original(*args)
    monkeypatch.setattr(analysis_api, 'read_metrics', counted)
    payload = {'history_ids': [record['id']], 'metric': 'val_ppl'}
    first = client.post('/api/analysis/series', json=payload).json()
    assert 'val_ppl' in first['metrics']
    client.post('/api/analysis/series', json=payload)
    assert len(reads) == 1
    (source / 'metrics.jsonl').write_text('{"event":"validation","tokens_seen":200,"perplexity":35}\n')
    client.post('/api/history/refresh')
    updated = client.post('/api/analysis/series', json=payload).json()
    assert updated['series'][0]['points'][0]['y'] == 35
    assert len(reads) == 2


def test_imported_parameters_do_not_infer_project_specific_defaults(tmp_path):
    from ai_exp_app.history.importer import enrich
    (tmp_path/'args.json').write_text(json.dumps({'width': 16}))
    (tmp_path/'model_config.json').write_text(json.dumps({'width': 16, 'custom_switch': 0}))
    record = enrich({'cache_dir': str(tmp_path)})
    assert record['parameters'] == {'width': 16}
    assert record['parameter_original_fields'] == ['width']


def test_notes_are_trimmed_and_persisted(setup):
    store, cache, source, client = setup
    record = import_history(store, {'kind': 'local', 'path': str(source)}, cache)
    response = client.patch('/api/history/' + record['id'], json={'notes': '  arbitrary 2e-4 文本  '})
    assert response.status_code == 200
    assert store.get('history', record['id'])['notes'] == 'arbitrary 2e-4 文本'
    assert client.get('/api/history').json()[0]['notes'] == 'arbitrary 2e-4 文本'


def test_running_import_includes_managed_and_refresh_invalidates_analysis_cache(setup, monkeypatch):
    from ai_exp_app.analysis.api import create_router as analysis_router
    from ai_exp_remote.files import file_manifest, read_file_chunk, read_file, sync_files
    store, cache, source, client = setup
    current = source.parent / 'current'; current.mkdir()
    (current / 'args.json').write_text('{}')
    (current / 'run.json').write_text('{"status":"running"}')
    metrics = current / 'metrics.jsonl'
    metrics.write_text('{"event":"validation","tokens_seen":4000000000,"perplexity":30}\n')
    old = import_history(store, {'kind': 'local', 'path': str(source)}, cache, name='same name')
    remote_path = '/runs/current'
    store.put('runs', 'live', {'id': 'live', 'status': 'running', 'remote_path': remote_path, 'display_name': 'same name'})
    hidden = import_history(store, {'kind': 'remote', 'path': remote_path}, cache, name='same name', run_id='live', synchronize=False, visibility='tracking')
    def rpc(alias, operation, payload):
        assert payload['path'] == remote_path
        payload = {**payload, 'path': str(current)}
        if operation == 'file_manifest':
            result = file_manifest(payload)
            (current / 'run.json').write_text('{"status":"running","tick":2}')
            return result
        return {'read_file_chunk': read_file_chunk, 'read_file': read_file, 'sync_files': sync_files}[operation](payload)
    monkeypatch.setattr('ai_exp_app.history.sync.rpc', rpc)
    client.app.include_router(analysis_router(store))
    response = client.post('/api/history/sync-running').json()
    assert response['count'] == 1
    assert store.get('history', 'live')['visibility'] == 'visible'
    assert store.get('history', 'live')['status'] == 'running'
    assert store.get('history', old['id'])['source']['path'] == str(source)
    body = {'history_ids': ['live'], 'metric': 'val_ppl'}
    assert client.post('/api/analysis/series', json=body).json()['series'][0]['points'][-1] == {'x': 4e9, 'y': 30}
    revision = next(r for r in client.get('/api/history').json() if r['id'] == 'live')['content_revision']
    with metrics.open('a') as stream: stream.write('{"event":"validation","tokens_seen":6000000000,"perplexity":25}\n')
    client.post('/api/history/import', json={'source': hidden['source']})
    assert client.post('/api/analysis/series', json=body).json()['series'][0]['points'][-1] == {'x': 6e9, 'y': 25}
    assert next(r for r in client.get('/api/history').json() if r['id'] == 'live')['content_revision'] != revision
    table = client.post('/api/analysis/table', json={'history_ids': ['live'], 'columns': [{'kind': 'metric', 'field': 'val_ppl', 'aggregate': 'final'}]}).json()
    assert table['rows'] == [['25.00 @6.00B']]


def test_nested_original_parameters_and_annotation_export_roundtrip(setup):
    import io, zipfile
    store, cache, source, client = setup
    (source / 'args.json').write_text('{"training":{"lr":0,"nullable":null},"runtime":{"gpu_count":1}}')
    record = import_history(store, {'kind': 'local', 'path': str(source)}, cache)
    endpoint = f"/api/history/{record['id']}/parameters"
    for field in ('lr', 'nullable', 'gpu_count', 'training', 'runtime'):
        assert client.patch(endpoint, json={'field': field, 'value': 'overwrite'}).status_code == 409
    assert client.patch(endpoint, json={'field': 'missing', 'value': '  10B  '}).status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(client.get(f"/api/history/{record['id']}/export").content))
    source2 = source.parent / 'exported'
    source2.mkdir()
    for name in ('args.json', 'parameter_annotations.json'):
        (source2 / name).write_bytes(archive.read(record['name'] + '/' + name))
    restored = import_history(store, {'kind': 'local', 'path': str(source2)}, cache)
    assert restored['parameters']['missing'] == '10B'
    assert 'missing' not in restored['parameter_original_fields']
    assert restored['original_parameters']['training']['lr'] == 0
    endpoint2 = f"/api/history/{restored['id']}/parameters"
    assert client.patch(endpoint2, json={'field': 'missing', 'value': '8B'}).status_code == 200
    assert json.loads((Path(restored['cache_dir']) / 'args.json').read_text())['training']['lr'] == 0


def test_local_import_uses_native_absolute_paths_and_remote_uses_posix(tmp_path):
    from pathlib import PurePosixPath
    store = Store(tmp_path / 'state.sqlite3')
    source = tmp_path / 'native-source'
    source.mkdir()
    (source / 'args.json').write_text('{}')
    record = import_history(store, {'kind': 'local', 'path': str(source)}, tmp_path / 'cache')
    assert Path(record['source']['path']).is_absolute()
    assert Path(record['cache_dir']).joinpath('args.json').read_text() == '{}'
    remote = import_history(store, {'kind': 'remote', 'path': '/srv/runs/remote-run/'},
                            tmp_path / 'cache', synchronize=False)
    assert remote['source']['path'] == '/srv/runs/remote-run'
    assert remote['name'] == 'remote-run'
    assert PurePosixPath(remote['source']['path']).is_absolute()
    for path in ('C:\\runs\\experiment', 'C:/runs/experiment', '\\\\server\\share\\experiment', 'relative/run'):
        with pytest.raises(ValueError, match='绝对路径'):
            import_history(store, {'kind': 'remote', 'path': path}, tmp_path / 'cache', synchronize=False)
    with pytest.raises(ValueError, match='来源'):
        import_history(store, {'kind': 'unexpected', 'path': '/srv/runs/a'}, tmp_path / 'cache', synchronize=False)


@pytest.mark.parametrize('name,expected', [
    ('result<1>?*"|', 'result_1_____'), ('trial. ', 'trial'),
    ('CON', '_CON'), ('aux.json', '_aux.json'), ('LPT9', '_LPT9'),
    ('comparison', 'comparison'),
])
def test_export_names_are_portable_across_windows_and_posix(name, expected):
    from ai_exp_app.history.paths import export_basename
    assert export_basename(name, 'identity', set()) == expected
    assert export_basename(name, 'identity', {expected}) != expected


@pytest.mark.parametrize('source_path', [r'C:\runs\example', r'\\server\share\example'])
def test_windows_drive_and_unc_validation_without_windows_filesystem(tmp_path, monkeypatch, source_path):
    from pathlib import PureWindowsPath
    import ai_exp_app.history.importer as importer

    class WindowsSource(PureWindowsPath):
        def expanduser(self):
            return self

        def resolve(self):
            return self

    # Only the source uses Windows syntax; caches and SQLite remain real temporary files.
    native_path = importer.Path
    monkeypatch.setattr(importer, 'Path', lambda value:
                        WindowsSource(value) if str(value) == source_path else native_path(value))
    store = Store(tmp_path / 'state.sqlite3')
    record = importer.import_history(store, {'kind': 'local', 'path': source_path},
                                     tmp_path / 'cache', synchronize=False)
    assert record['source']['path'] == source_path
    assert record['name'] == 'example'


def test_running_refresh_does_not_wait_for_other_existing_cache(setup, monkeypatch):
    import threading
    import ai_exp_app.history.api as history_api
    store, cache, source, client = setup
    second_entered = threading.Event()
    for identity in ('first', 'second'):
        store.put('runs', identity, {'id': identity, 'status': 'running', 'remote_path': '/runs/' + identity})
        store.put('history', identity, {'id': identity, 'name': identity, 'visibility': 'visible',
            'source': {'kind': 'remote', 'path': '/runs/' + identity, 'ssh_alias': 'gpu'},
            'cache_dir': str(cache / identity), 'sync_status': 'pending'})
    def independent_pull(store, source, cache_root, name, run_id, **kwargs):
        if run_id == 'first':
            assert second_entered.wait(3), 'one cache blocked all other running experiments'
        else:
            second_entered.set()
        return store.get('history', run_id)
    monkeypatch.setattr(history_api, 'import_history', independent_pull)
    result = client.post('/api/history/sync-running', json={}).json()
    assert result['count'] == 2
    assert [r['id'] for r in result['items']] == ['first', 'second']
    assert all(r['status'] == 'running' for r in result['items'])


def test_file_refresh_preserves_metadata_arriving_during_transfer(setup, monkeypatch):
    import ai_exp_app.history.importer as importer
    store, cache, source, client = setup
    source_info = {'kind': 'remote', 'path': '/runs/shared', 'ssh_alias': 'gpu'}
    store.put('history', 'shared', {'id': 'shared', 'run_id': 'shared', 'name': 'original',
        'source': source_info, 'cache_dir': str(cache / 'shared'), 'visibility': 'visible', 'notes': ''})
    def transfer(record, cache_root):
        incoming = store.get('history', 'shared')
        incoming.update(name='cloud name', notes='cloud edit', visibility='archived')
        store.put('history', 'shared', incoming)
        return {'files': ['args.json'], 'sync_status': 'synced'}
    monkeypatch.setattr(importer, 'sync_history', transfer)
    result = importer.import_history(store, source_info, cache, run_id='shared')
    assert result['name'] == 'cloud name' and result['notes'] == 'cloud edit'
    assert result['visibility'] == 'archived' and result['sync_status'] == 'synced'
