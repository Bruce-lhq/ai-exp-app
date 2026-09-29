import pytest
from ai_exp_app.parameters.validation import parse_number, validate_parameters


@pytest.mark.parametrize("text,value", [("1.5B", 1500000000), ("2k", 2000), ("3M", 3000000)])
def test_units(text, value):
    assert parse_number(text, True) == value


@pytest.mark.parametrize("text", ["NaN", "1.5", "2abc", "1e999999999"])
def test_invalid_integer(text):
    with pytest.raises(ValueError):
        parse_number(text, True)


def test_repair_does_not_replace_invalid_values():
    schema = [{"key": "count", "kind": "integer", "has_default": True, "default": 5}, {"key": "mode", "kind": "string", "choices": ["a", "b"], "has_default": True, "default": "a"}]
    result = validate_parameters(schema, {"training": {"count": "abc", "old": 10}, "runtime": {"gpu_count": 2}})
    assert result["errors"][0]["field"] == "count"
    assert result["parameters"]["training"] == {"mode": "a"}
    assert {w["field"] for w in result["warnings"]} == {"old", "mode"}


def test_default_project_and_cached_schema_survive_router_reload(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_exp_app.db import Store
    from ai_exp_app.projects.api import create_router
    store = Store(tmp_path / 'db')
    for identity in ('wonn', 's1llt'):
        store.put('projects', identity, {'id': identity, 'name': identity, 'remote_path': '/projects/' + identity})
        store.put('schemas', identity, {'fields': [{'key': 'lr', 'default': .01}], 'code': {'kind': 'working_tree', 'ref': None}})
    def offline(*args, **kwargs):
        raise AssertionError('Switching cached directories should not need SSH schema reload')
    monkeypatch.setattr('ai_exp_app.projects.api.remote', offline)
    app = FastAPI(); app.include_router(create_router(store)); client = TestClient(app)
    assert client.patch('/api/projects/s1llt', json={'is_default': True}).status_code == 200
    restored = FastAPI(); restored.include_router(create_router(Store(tmp_path / 'db')))
    client = TestClient(restored)
    projects = client.get('/api/projects').json()
    assert [p['id'] for p in projects if p['is_default']] == ['s1llt']
    for identity in ('s1llt', 'wonn', 's1llt'):
        assert client.post(f'/api/projects/{identity}/schema', json={'refresh': False}).status_code == 200
