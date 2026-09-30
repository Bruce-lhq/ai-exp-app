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


def test_historical_args_ignore_managed_metadata_but_warn_for_unknown_training_fields():
    schema = [
        {"key": "learning_rate", "kind": "number", "has_default": True, "default": .01},
        {"key": "seed", "kind": "integer", "has_default": True, "default": 42},
        {"key": "resume", "kind": "string", "has_default": True, "default": None},
        {"key": "config_index", "kind": "integer", "has_default": True, "default": 1},
    ]
    arguments = {
        "learning_rate": .00005, "scaling_up": 2,
        "run_dir": "/runs/original", "data_root": "/datasets/train",
        "resume": "/runs/original/latest.pt", "allow_nonexact_resume": False,
        "allow_world_size_change": False, "config_index": 1, "config_total": 1,
        "config_name": "historical-config", "config_description": None,
    }
    result = validate_parameters(schema, arguments, controlled_keys={"resume", "config_index"})
    assert result["parameters"]["training"] == {"learning_rate": .00005, "seed": 42}
    assert result["errors"] == []
    assert result["warnings"] == [
        {"field": "scaling_up", "message": "当前代码没有此参数，已忽略"},
        {"field": "seed", "message": "未填写，已使用源码默认值"},
    ]
    assert arguments["resume"] == "/runs/original/latest.pt"


def test_default_project_and_cached_schema_survive_router_reload(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_exp_app.db import Store
    from ai_exp_app.projects.api import create_router
    store = Store(tmp_path / 'db')
    for identity in ('project-a', 'project-b'):
        store.put('projects', identity, {'id': identity, 'name': identity, 'remote_path': '/projects/' + identity})
        store.put('schemas', identity, {'fields': [{'key': 'lr', 'default': .01}], 'code': {'kind': 'working_tree', 'ref': None}})
    def offline(*args, **kwargs):
        raise AssertionError('Switching cached directories should not need SSH schema reload')
    monkeypatch.setattr('ai_exp_app.projects.api.remote', offline)
    app = FastAPI(); app.include_router(create_router(store)); client = TestClient(app)
    assert client.patch('/api/projects/project-b', json={'is_default': True}).status_code == 200
    restored = FastAPI(); restored.include_router(create_router(Store(tmp_path / 'db')))
    client = TestClient(restored)
    projects = client.get('/api/projects').json()
    assert [p['id'] for p in projects if p['is_default']] == ['project-b']
    for identity in ('project-b', 'project-a', 'project-b'):
        assert client.post(f'/api/projects/{identity}/schema', json={'refresh': False}).status_code == 200


def test_declared_fields_are_not_reserved_by_name():
    schema = [{"key": key, "kind": "string", "has_default": True, "default": "default"}
              for key in ("data_root", "run_dir", "resume", "config_name")]
    result = validate_parameters(schema, {"training": {"resume": "adapter-v2"}})
    assert result["errors"] == []
    assert result["parameters"]["training"]["resume"] == "adapter-v2"
    assert set(result["parameters"]["training"]) == {field["key"] for field in schema}


def test_workers_are_gpu_count_only_when_profile_declares_mapping():
    schema = [{"key": "num_workers", "kind": "integer", "has_default": True, "default": 16}]
    parameters = {"training": {}, "runtime": {"gpu_count": 2}}
    ordinary = validate_parameters(schema, parameters)
    mapped = validate_parameters(schema, parameters, workers_parameter="num_workers")
    assert ordinary["parameters"]["runtime"]["gpu_count"] == 2
    assert mapped["parameters"]["runtime"]["gpu_count"] == 16
