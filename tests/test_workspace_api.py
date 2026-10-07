import json
from fastapi.testclient import TestClient
from ai_exp_app.app import create_app


def client(tmp_path, monkeypatch, name):
    root = tmp_path / name
    monkeypatch.setenv('AI_EXP_CONFIG_FILE', str(root / 'config.local.json'))
    app = create_app(root)
    browser = TestClient(app, base_url='http://127.0.0.1')
    browser.get('/')
    browser.headers['Origin'] = 'http://127.0.0.1'
    return app, browser


def test_sync_routes_backup_enable_exchange_and_private_paths(tmp_path, monkeypatch):
    hub, phone = client(tmp_path, monkeypatch, 'phone')
    mac, desktop = client(tmp_path, monkeypatch, 'mac')
    mac.state.config.save_local_settings({'ssh_alias': 'custom'})
    source = {'kind': 'remote', 'path': '/runs/exp', 'ssh_alias': 'custom'}
    mac.state.store.put('history', 'run', {'id': 'run', 'name': 'shared', 'source': source,
                                        'cache_dir': '/private/mac/cache', 'notes': 'test', 'visibility': 'visible'})
    assert phone.post('/api/workspace-sync/exchange', json={'changes': []}).status_code == 409
    for browser, mode in [(phone, 'hub'), (desktop, 'client')]:
        assert browser.put('/api/workspace-sync/settings', json={'mode': mode, 'port': 8765}).status_code == 200
    assert list((tmp_path / 'mac' / 'backups').glob('*/app.sqlite3'))
    mac.state.workspace_sync.forward = lambda body: phone.post('/api/workspace-sync/exchange', json=body).json()
    result = desktop.post('/api/workspace-sync/refresh', json={}).json()
    assert result['state'] == 'idle' and result['pending'] == 0
    record = hub.state.store.list('history')[0]
    assert record['name'] == 'shared'
    assert record['source']['ssh_alias'] == 'gpu'
    assert record['cache_dir'].startswith(str(tmp_path / 'phone' / 'gpu_downloads'))
    assert mac.state.store.get('history', 'run')['cache_dir'] == '/private/mac/cache'
    assert phone.post('/api/workspace-sync/exchange', json={'changes': [{}]}).status_code == 422
    assert desktop.post('/api/workspace-sync/conflicts/missing', json={'choice': 'remote'}).status_code == 409


def test_shared_view_local_persistence_and_offline_status(tmp_path, monkeypatch):
    app, browser = client(tmp_path, monkeypatch, 'mac')
    value = {'settings': {'title': 'test'}, 'appearance': {}}
    assert browser.get('/api/workspace-sync/view').json() == {}
    assert browser.put('/api/workspace-sync/view', json=value).json() == value
    assert browser.get('/api/workspace-sync/view').json() == value
    assert browser.put('/api/workspace-sync/view', json={'cache_dir': '/private'}).status_code == 422
    assert browser.put('/api/workspace-sync/settings', json={'mode': 'client', 'port': 65536}).status_code == 422
    browser.put('/api/workspace-sync/settings', json={'mode': 'client', 'port': 8765})
    def disconnected(body):
        raise RuntimeError('offline')
    app.state.workspace_sync.forward = disconnected
    result = browser.post('/api/workspace-sync/refresh', json={}).json()
    assert result['state'] == 'offline' and result['pending'] >= 1
    assert browser.get('/api/workspace-sync/view').json() == value
    # Sync stays behind existing session + same-origin protection.
    assert TestClient(app, base_url='http://127.0.0.1').get('/api/workspace-sync').status_code == 403
