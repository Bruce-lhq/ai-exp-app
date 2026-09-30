from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_exp_app.config import Config
from ai_exp_app.db import Store
from ai_exp_app.projects.api import create_router, schema_for
from ai_exp_app.runs.service import RunService


def setup(tmp_path):
    store = Store(tmp_path / 'app.sqlite3')
    store.config = Config.load(tmp_path)
    store.put('projects', 'p', {'id': 'p', 'name': 'Training', 'ssh_alias': 'compute',
                               'remote_path': '/srv/project', 'config': {}})
    return store


def test_project_integration_and_python_changes_invalidate_cached_schema(tmp_path, monkeypatch):
    store = setup(tmp_path)
    requests = []

    def inspect(alias, operation, payload):
        assert (alias, operation) == ('compute', 'read_schema')
        requests.append(payload)
        return {'fields': [{'key': 'resume', 'kind': 'string', 'default': 'fresh', 'has_default': True}],
                'integration': payload.get('integration', {}), 'controlled_keys': []}

    monkeypatch.setattr('ai_exp_app.projects.api.remote', inspect)
    first = schema_for(store, 'p')
    assert schema_for(store, 'p') == first
    assert len(requests) == 1
    app = FastAPI()
    app.include_router(create_router(store))
    client = TestClient(app)
    integration = {'version': 1, 'command': ['{python}', 'entry.py']}
    assert client.patch('/api/projects/p', json={'config': {'python': '/env/bin/python', 'integration': integration}}).status_code == 200
    value = schema_for(store, 'p')
    assert len(requests) == 2
    assert requests[-1]['python'] == '/env/bin/python'
    assert requests[-1]['integration'] == integration
    assert value['integration'] == integration
    assert client.get('/api/projects/p/editor-initial').json()['training']['resume'] == 'fresh'


def test_submit_pins_discovered_profile_and_maps_only_declared_gpu_field(tmp_path, monkeypatch):
    store = setup(tmp_path)
    profile = {'version': 1, 'command': ['{python}', 'fit.py'],
               'runtime': {'workers_parameter': 'processes'}, 'controlled_parameters': ['output']}
    fields = [{'key': 'processes', 'kind': 'integer', 'default': 2, 'has_default': True},
              {'key': 'output', 'kind': 'string', 'default': '/untrusted', 'has_default': True},
              {'key': 'data_root', 'kind': 'string', 'default': '/dataset', 'has_default': True}]
    calls = []

    def call(alias, operation, payload, request_id=None):
        calls.append((operation, payload))
        if operation == 'read_schema':
            return {'fields': fields, 'integration': profile, 'controlled_keys': ['output']}
        if operation == 'status':
            return {'runs': [], 'queue': [], 'events': []}
        return {'run_id': payload['run_id']}

    monkeypatch.setattr('ai_exp_app.projects.api.remote', call)
    monkeypatch.setattr('ai_exp_app.runs.service.remote', call)
    app = FastAPI()
    app.include_router(RunService(store).create_router())
    response = TestClient(app).post('/api/runs', json={
        'project_id': 'p', 'mode': 'queue',
        'parameters': {'training': {'processes': 3, 'output': '/manual'}, 'runtime': {'gpu_count': 1}}})
    assert response.status_code == 201
    payload = next(payload for operation, payload in calls if operation == 'submit')
    assert payload['project']['integration'] == profile
    assert payload['parameters']['runtime']['gpu_count'] == 3
    assert payload['parameters']['training'] == {'processes': 3, 'data_root': '/dataset'}
    project = store.get('projects', 'p')
    project['config'] = {'integration': {'command': ['different-program']}}
    store.put('projects', 'p', project)
    assert store.get('submissions', payload['run_id'])['payload']['project']['integration'] == profile


def test_resume_project_profile_propagates_without_requiring_token_progress(tmp_path, monkeypatch):
    from ai_exp_app.history.api import create_router as history_router
    store = setup(tmp_path)
    profile = {"version": 1, "command": ["{python}", "fit.py"], "parameters": []}
    project = store.get("projects", "p")
    project["config"] = {"integration": profile, "python": "/env/bin/python"}
    store.put("projects", "p", project)
    store.put("history", "h", {"id": "h", "name": "Classifier", "source": {
        "kind": "remote", "ssh_alias": "compute", "path": "/runs/classifier"}})
    def preview(alias, operation, payload):
        assert alias == "compute" and operation == "checkpoint_preview"
        assert payload["project"]["path"] == "/srv/project"
        assert payload["project"]["python"] == "/env/bin/python"
        assert payload["project"]["integration"] == profile
        return {"path": "/runs/classifier/checkpoints/latest.bin", "identity": {"size": 24},
                "training": {}, "runtime": {"gpu_count": 1}, "step": 200}
    monkeypatch.setattr("ai_exp_app.projects.api.remote", preview)
    app = FastAPI(); app.include_router(history_router(store, tmp_path / "cache"))
    response = TestClient(app).post("/api/history/h/resume-editor", json={})
    assert response.status_code == 200
    assert response.json()["resume"]["tokens_seen"] is None
    assert response.json()["resume"]["step"] == 200
    assert response.json()["resume"]["ticket"]
