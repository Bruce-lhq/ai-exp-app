import json
from pathlib import Path
import pytest
from ai_exp_remote.resume import pin, checkpoint_identity
from ai_exp_remote.state import AgentError
from ai_exp_app.history.sync import sync_history
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ai_exp_app.db import Store
from ai_exp_app.history.api import create_router
import sys
from ai_exp_remote.rpc import handle
from ai_exp_remote.launcher import build_launch


def test_checkpoint_pin_rejects_new_version_and_keeps_independent_copy(tmp_path):
    source = tmp_path / 'latest.pt'
    source.write_bytes(b'original')
    draft = {'path': str(source), 'identity': checkpoint_identity(source)}
    frozen = tmp_path / 'frozen' / 'resume.pt'
    pin(draft, frozen)
    source.write_bytes(b'updated checkpoint')
    assert frozen.read_bytes() == b'original'
    with pytest.raises(AgentError, match='已更新'):
        pin(draft, tmp_path / 'rejected.pt')
    assert not (tmp_path / 'rejected.pt').exists()


def test_terminal_sync_copies_checkpoint_but_live_sync_does_not(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'latest.pt').write_bytes(b'complete checkpoint')
    cache = tmp_path / 'cache'
    record = {'id': 'r', 'source': {'kind': 'local', 'path': str(source)},
              'cache_dir': str(cache / 'experiment'), 'status': 'running'}
    record.update(sync_history(record, cache))
    assert 'latest.pt' not in record['files']
    record['status'] = 'paused'
    record.update(sync_history(record, cache))
    assert (Path(record['cache_dir']) / 'latest.pt').read_bytes() == b'complete checkpoint'
    assert record['sync_status'] == 'synced'


def test_resume_editor_uses_checkpoint_not_display_overrides(tmp_path, monkeypatch):
    store = Store(tmp_path / 'db.sqlite')
    store.put('projects', 'p', {'id': 'p', 'ssh_alias': 'gpu', 'is_default': True})
    store.put('history', 'h', {'id': 'h', 'name': '备注名', 'source': {'kind': 'remote', 'path': '/runs/a'},
        'parameters': {'learning_rate': 'display only'}, 'parameter_overrides': {'learning_rate': '任意字符串'}})
    def preview(alias, operation, payload):
        assert (alias, operation, payload['path']) == ('gpu', 'checkpoint_preview', '/runs/a')
        return {'training': {'learning_rate': .001, 'ca_lambda': 0}, 'runtime': {'gpu_count': 4},
                'tokens_seen': 5000000000, 'identity': {'size': 12}, 'path': '/runs/a/latest.pt'}
    monkeypatch.setattr('ai_exp_app.projects.api.remote', preview)
    app = FastAPI()
    app.include_router(create_router(store, tmp_path / 'cache'))
    value = TestClient(app).post('/api/history/h/resume-editor', json={}).json()
    assert value['training']['learning_rate'] == .001
    assert value['training']['ca_lambda'] == 0
    assert value['project_id'] == 'p'
    assert value['display_name'] == '备注名 · 续跑'
    assert store.get('resume_drafts', value['resume']['ticket'])['path'] == '/runs/a/latest.pt'


def test_submission_pins_resume_before_queue_and_uses_new_output(tmp_path, monkeypatch):
    source = tmp_path / 'project'
    source.mkdir()
    (source / 'train.py').write_text('import argparse\ndef build_parser():\n p=argparse.ArgumentParser()\n p.add_argument("--lr",type=float,default=.1)\n p.add_argument("--run-dir")\n p.add_argument("--data-root")\n p.add_argument("--resume")\n return p\n')
    (source/'workbench.project.json').write_text(json.dumps({'version':1,'command':['{python}','train.py','--run-dir','{run_dir}'],'parameters':[{'name':'lr','type':'number','default':.1,'flag':'--lr'}],'resume':{'flag':'--resume','validator':['{python}','verify.py','{checkpoint}','{request}']}}))
    old = tmp_path / 'old'
    old.mkdir()
    checkpoint = old / 'latest.pt'
    checkpoint.write_bytes(b'checkpoint')
    validated = []
    monkeypatch.setattr('ai_exp_remote.rpc.validate_checkpoint', lambda run, path: validated.append(path))
    payload = dict(run_id='new', mode='queue', project={'path': str(source), 'python': sys.executable,
        'runs_root': str(tmp_path / 'runs'), 'data_root': str(tmp_path / 'data')}, parameters={'training': {'lr': .1}, 'runtime': {'gpu_count': 1}},
        resume={'path': str(checkpoint), 'identity': checkpoint_identity(checkpoint)})
    run = handle({'version': 1, 'operation': 'submit', 'request_id': 'req', 'payload': payload}, tmp_path / 'state', False)
    assert validated == [run['resume_path']]
    checkpoint.write_bytes(b'newer checkpoint')
    assert Path(run['resume_path']).read_bytes() == b'checkpoint'
    assert Path(run['remote_path']) != old
    argv = build_launch(run['project'], run, [0])['argv']
    assert argv[argv.index('--resume') + 1] == run['resume_path']
