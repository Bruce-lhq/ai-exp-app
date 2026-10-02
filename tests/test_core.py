from fastapi.testclient import TestClient
from ai_exp_app.app import create_app

ORIGIN = {"Origin": "http://testserver"}


def test_projects_persist_and_delete_only_unfavorites(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        client.get("/")
        result = client.post("/api/projects", json={"name": "project-a", "ssh_alias": "gpu", "remote_path": "/project"}, headers=ORIGIN)
        assert result.status_code == 201
        id = result.json()["id"]
    with TestClient(create_app(tmp_path)) as client:
        client.get("/")
        assert client.get("/api/projects").json()[0]["id"] == id
        assert client.request("DELETE", f"/api/projects/{id}", json={}, headers=ORIGIN).status_code == 200
        assert client.get("/api/projects").json() == []
        assert client.app.state.store.get("projects", id)["favorite"] is False


def test_session_origin_and_host_enforced(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/projects").status_code == 403
        client.get("/")
        assert client.post("/api/projects", json={}, headers={"Origin": "http://evil.test"}).status_code == 403
        assert client.get("/api/health", headers={"Host": "evil.test"}).status_code == 403


def test_homepage_refreshes_session_after_service_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as first:
        home = first.get('/')
        assert home.headers.get('cache-control') == 'no-store'
        old_cookie = first.cookies.get('ai_exp_session')
    with TestClient(create_app(tmp_path)) as second:
        second.cookies.set('ai_exp_session', old_cookie, domain='testserver.local', path='/')
        assert second.get('/api/projects').status_code == 403
        home = second.get('/')
        assert second.cookies.get('ai_exp_session') != old_cookie
        assert second.get('/api/projects').status_code == 200


def test_history_is_compressed_without_changing_data_or_session_security(tmp_path):
    import json
    from ai_exp_app.history.importer import import_history

    app = create_app(tmp_path / 'workspace')
    source = tmp_path / 'experiment'
    source.mkdir()
    (source / 'args.json').write_text(json.dumps({'learning_rate': 0.001, 'description': 'training parameter ' * 1000}))
    import_history(app.state.store, {'kind': 'local', 'path': str(source)}, tmp_path / 'cache', 'Existing experiment')
    client = TestClient(app)
    assert client.get('/api/history', headers={'Accept-Encoding': 'gzip'}).status_code == 403
    client.get('/')
    plain = client.get('/api/history', headers={'Accept-Encoding': 'identity'})
    compressed = client.get('/api/history', headers={'Accept-Encoding': 'gzip'})
    assert compressed.json() == plain.json()
    assert compressed.json()[0]['name'] == 'Existing experiment'
    assert compressed.headers['content-encoding'] == 'gzip'
    assert 'accept-encoding' in compressed.headers['vary'].lower()
    assert int(compressed.headers['content-length']) < len(plain.content) / 4
