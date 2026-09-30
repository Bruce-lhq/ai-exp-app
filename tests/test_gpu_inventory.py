import json
import sys
import pytest
from ai_exp_remote.scheduler import gpu_status, choose_gpus
from ai_exp_remote.state import AgentError


def probe(tmp_path, monkeypatch, data):
    script = tmp_path / 'provider_inventory.py'
    script.write_text('print(' + repr(json.dumps(data)) + ')')
    monkeypatch.setattr('ai_exp_remote.scheduler.settings', lambda: {'remote_gpu_probe': str(script), 'remote_python': sys.executable})


def test_project_supplied_gpu_inventory_does_not_require_nvidia(tmp_path, monkeypatch):
    probe(tmp_path, monkeypatch, [{'index': 2, 'available': False, 'name': 'provider device'},
                                  {'index': 0, 'available': True}, {'index': 1, 'available': True}])
    devices = gpu_status()
    assert choose_gpus(2, [d['index'] for d in devices if d['available']]) == [0, 1]


@pytest.mark.parametrize('data', [None, [{}], [{'index': 0, 'available': 'yes'}],
                                  [{'index': 0, 'available': True}, {'index': 0, 'available': False}]])
def test_invalid_inventory_never_allocates_cards(tmp_path, monkeypatch, data):
    probe(tmp_path, monkeypatch, data)
    with pytest.raises(AgentError, match='GPU 检查失败'):
        gpu_status()


def test_probe_failure_is_not_an_empty_free_gpu_list(tmp_path, monkeypatch):
    script = tmp_path / 'bad_probe.py'
    script.write_text('raise SystemExit(1)')
    monkeypatch.setattr('ai_exp_remote.scheduler.settings', lambda: {'remote_gpu_probe': str(script), 'remote_python': sys.executable})
    with pytest.raises(AgentError, match='GPU 检查失败'):
        gpu_status()
