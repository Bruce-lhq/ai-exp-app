from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_exp_app.db import Store
from ai_exp_app.runs.service import RunService


def test_remove_stopped_managed_run_survives_refresh_and_keeps_history(tmp_path, monkeypatch):
    store = Store(tmp_path / 'db.sqlite')
    service = RunService(store)
    run = {'id': 'two-b', 'status': 'stopped', 'remote_path': '/runs/two-b'}
    store.put('runs', run['id'], run)
    store.put('history', run['id'], {'id': run['id'], 'name': '2B'})
    app = FastAPI()
    app.include_router(service.create_router())
    client = TestClient(app)
    assert client.post('/api/runs/two-b/remove', json={}).status_code == 409
    assert client.post('/api/runs/two-b/remove', json={'confirmed': True}).status_code == 200
    monkeypatch.setattr('ai_exp_app.runs.service.remote', lambda *a, **k: {'runs': [run]})
    service.refresh()
    assert client.get('/api/runs').json() == []
    assert store.get('history', run['id'])['name'] == '2B'
    assert store.get('runs', run['id'])['remote_path'] == '/runs/two-b'
    store.put('runs', 'live', {'id': 'live', 'status': 'running'})
    assert client.post('/api/runs/live/remove', json={'confirmed': True}).status_code == 409


def test_monitor_uses_latest_history_name_without_overwriting_remote_name(tmp_path):
    store = Store(tmp_path / 'db.sqlite')
    service = RunService(store)
    run = {'id': 'run1', 'display_name': 'raw', 'external': True,
           'remote_path': '/runs/example', 'ssh_alias': 'gpu'}
    store.put('runs', 'run1', run)
    history = {'id': 'import1', 'display_name': '备注名', 'visibility': 'visible',
               'source': {'kind': 'remote', 'path': '/runs/example/', 'ssh_alias': 'gpu'}}
    store.put('history', history['id'], history)
    service.snapshot['queue'] = ['run1']
    app = FastAPI()
    app.include_router(service.create_router())
    client = TestClient(app)
    assert client.get('/api/runs').json()[0]['display_name'] == '备注名'
    assert client.get('/api/runs/run1').json()['display_name'] == '备注名'
    assert client.get('/api/queue').json()['runs'][0]['display_name'] == '备注名'
    store.put('runs', 'run1', run)  # A later remote refresh must not replace the label.
    history['display_name'] = '新备注名'
    store.put('history', history['id'], history)
    assert client.get('/api/runs').json()[0]['display_name'] == '新备注名'
    assert store.get('runs', 'run1')['display_name'] == 'raw'
    history['visibility'] = 'removed'
    store.put('history', history['id'], history)
    assert client.get('/api/runs').json()[0]['display_name'] == 'raw'


def test_completed_run_does_not_retain_running_eta(tmp_path, monkeypatch):
    store = Store(tmp_path/'db.sqlite')
    store.put('runs', 'r', {'id': 'r', 'status': 'running', 'remaining': '1m'})
    monkeypatch.setattr('ai_exp_app.runs.service.remote', lambda *a, **k: {
        'runs': [{'id': 'r', 'status': 'completed', 'remote_path': '/runs/r'}]})
    RunService(store).refresh()
    assert not store.get('runs', 'r').get('remaining')
