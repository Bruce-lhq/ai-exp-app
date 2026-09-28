from fastapi.testclient import TestClient
from ai_exp_app.app import create_app
from ai_exp_app.runs.service import apply_started_event

ORIGIN = {"Origin": "http://testserver"}
PARAMS = {"training": {"learning_rate": 0.001}, "runtime": {"gpu_count": 2}}


def setup(client):
    client.get("/")
    project = client.post("/api/projects", json={"name": "p", "remote_path": "/project"}, headers=ORIGIN).json()
    id = project["id"]
    client.app.state.store.put("schemas", id, {"fields": [{"key": "learning_rate", "kind": "number", "default": 0.01, "has_default": True}], "code": {"kind": "working_tree", "ref": None}})
    return id


def test_import_and_preset_changes_never_replace_last_run(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        id = setup(c)
        group = c.post(f"/api/projects/{id}/presets/import", json={"name": "wonn", "document": {"parameters": PARAMS}}, headers=ORIGIN)
        assert group.status_code == 201
        assert c.get(f"/api/projects/{id}/editor-initial").json()["training"]["learning_rate"] == 0.01
        store = c.app.state.store
        store.put("runs", "r1", {"project_id": id, "parameters": PARAMS})
        assert apply_started_event(store, {"kind": "started", "run_id": "r1", "seq": 8})
        assert not apply_started_event(store, {"kind": "started", "run_id": "r1", "seq": 7})
        assert not apply_started_event(store, {"kind": "accepted", "run_id": "r1", "seq": 10})
        c.request("DELETE", f"/api/projects/{id}/presets/{group.json()['id']}", json={}, headers=ORIGIN)
        assert c.get(f"/api/projects/{id}/editor-initial").json()["training"]["learning_rate"] == 0.001
    with TestClient(create_app(tmp_path)) as c:
        c.get("/")
        assert c.get(f"/api/projects/{id}/editor-initial").json()["runtime"]["gpu_count"] == 2


def test_invalid_import_not_saved(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        id = setup(c)
        r = c.post(f"/api/projects/{id}/presets/import", json={"name": "bad", "document": {"learning_rate": "abc"}}, headers=ORIGIN)
        assert r.status_code == 422
        assert c.get(f"/api/projects/{id}/presets").json() == []
