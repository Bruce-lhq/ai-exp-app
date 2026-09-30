import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ai_exp_app.analysis.api import create_router
from ai_exp_app.db import Store
from ai_exp_remote.files import metric_series
from ai_exp_app.history.importer import import_history
from ai_exp_app.history.worker import sync_once


def test_metric_projection_batches_runs_and_preserves_points(tmp_path):
    path = tmp_path / 'experiment'
    path.mkdir()
    rows = [{'event': 'validation', 'tokens_seen': 100, 'perplexity': 42, 'other': 123},
            {'event': 'train', 'tokens_seen': 100, 'perplexity': 99},
            {'event': 'validation', 'tokens_seen': 200, 'perplexity': 35}]
    (path / 'metrics.jsonl').write_text('\n'.join(map(json.dumps, rows)) + '\n{partial')
    result = metric_series({'runs': [{'id': 'a', 'path': str(path)}, {'id': 'b', 'path': str(path)}], 'metric': 'val_ppl'})
    assert result['a']['points'] == result['b']['points'] == [{'x': 100, 'y': 42}, {'x': 200, 'y': 35}]
    assert 'train_ppl' in result['a']['metrics']
    assert 'records' not in result['a']


def test_live_series_uses_one_remote_request_and_offline_keeps_cached_data(tmp_path, monkeypatch):
    import ai_exp_app.analysis.api as analysis
    analysis._external_cache.clear()
    store = Store(tmp_path / 'db')
    for identity in ['a', 'b']:
        store.put('runs', identity, {'id': identity, 'external': True, 'remote_path': '/runs/' + identity})
    calls = []
    def remote(alias, operation, payload):
        calls.append((operation, payload))
        return {r['id']: {'points': [{'x': 100, 'y': 42}], 'metrics': ['val_ppl'], 'warnings': []} for r in payload['runs']}
    monkeypatch.setattr(analysis, 'remote', remote)
    app = FastAPI(); app.include_router(create_router(store)); client = TestClient(app)
    body = {'history_ids': ['a', 'b'], 'live_ids': ['a', 'b']}
    assert len(client.post('/api/analysis/series', json=body).json()['series']) == 2
    assert len(calls) == 1 and calls[0][0] == 'metric_series'
    client.post('/api/analysis/series', json=body)
    assert len(calls) == 1
    for key, (_, data) in list(analysis._external_cache.items()): analysis._external_cache[key] = (0, data)
    def offline(*args):
        from fastapi import HTTPException
        raise HTTPException(502, 'offline')
    monkeypatch.setattr(analysis, 'remote', offline)
    response = client.post('/api/analysis/series', json=body).json()
    assert len(response['series']) == 2 and response['warnings']
    analysis._external_cache.clear()


def test_synced_imports_are_not_downloaded_on_every_background_tick(tmp_path, monkeypatch):
    store = Store(tmp_path / 'db')
    source = tmp_path / 'source'; source.mkdir()
    (source / 'args.json').write_text('{}')
    record = import_history(store, {'kind': 'local', 'path': str(source)}, tmp_path / 'cache')
    def unexpected(*args): raise AssertionError('Already synchronized')
    monkeypatch.setattr('ai_exp_app.history.worker.sync_history', unexpected)
    sync_once(store, tmp_path / 'cache')
    assert store.get('history', record['id'])['sync_status'] == 'synced'


def test_managed_live_run_does_not_wait_for_history_download(tmp_path, monkeypatch):
    import ai_exp_app.analysis.api as analysis
    analysis._external_cache.clear()
    store = Store(tmp_path / 'db')
    store.put('runs', 'managed', {'id': 'managed', 'display_name': 'Small run',
                               'status': 'running', 'remote_path': '/runs/managed'})
    monkeypatch.setattr(analysis, 'remote', lambda *args: {
        'managed': {'points': [{'x': 1024, 'y': 42}], 'metrics': ['val_ppl'], 'warnings': []}})
    app = FastAPI(); app.include_router(create_router(store))
    result = TestClient(app).post('/api/analysis/series', json={
        'history_ids': ['managed'], 'live_ids': ['managed']}).json()
    assert result['series'][0]['points'] == [{'x': 1024, 'y': 42}]
    analysis._external_cache.clear()


def test_unstarted_dequeued_run_does_not_create_unsyncable_history(tmp_path, monkeypatch):
    store = Store(tmp_path / 'db')
    store.put('runs', 'cancelled', {'id': 'cancelled', 'status': 'stopped',
                                  'remote_path': '/runs/not-created', 'mode': 'queue'})
    def unexpected(*args):
        raise AssertionError('An unstarted queue item has no experiment files')
    monkeypatch.setattr('ai_exp_app.history.worker.sync_history', unexpected)
    sync_once(store, tmp_path / 'cache')
    assert store.get('history', 'cancelled') is None
