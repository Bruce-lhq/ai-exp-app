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


def test_parameter_cell_saved_to_cache_and_preserved_after_refresh(setup):
    store, cache, source, client = setup
    record = import_history(store, {'kind': 'local', 'path': str(source)}, cache)
    endpoint = f"/api/history/{record['id']}/parameters"
    response = client.patch(endpoint, json={'field': 'lr', 'value': '  arbitrary | 字符串  '})
    assert response.status_code == 200
    assert json.loads((Path(record['cache_dir']) / 'args.json').read_text())['lr'] == 'arbitrary | 字符串'
    assert json.loads((source / 'args.json').read_text())['lr'] == .001
    assert client.post('/api/history/refresh').status_code == 200
    assert json.loads((Path(record['cache_dir']) / 'args.json').read_text())['lr'] == 'arbitrary | 字符串'
    table = client.post('/api/analysis/table', json={'history_ids': [record['id']], 'columns': [
        {'id': 'lr', 'kind': 'parameter', 'field': 'lr', 'title': '学习率'}]}).json()
    assert table['rows'][0][0] == 'arbitrary | 字符串'


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
