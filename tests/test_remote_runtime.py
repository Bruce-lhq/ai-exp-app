import json
from pathlib import Path
import pytest
from ai_exp_remote import runtime
from ai_exp_remote.launcher import build_launch
from ai_exp_remote.state import Store, atomic_json


def sample(tmp_path):
    path=tmp_path/'output'
    return dict(run_id='r',id='r',project_id='p',project={'python':'python3','runs_root':str(tmp_path/'runs'),'integration':{'version':1,'command':['{python}','experiment.py','--output','{run_dir}'],'parameters':[],'environment':{'TORCHINDUCTOR_CACHE_DIR':'{project_dir}/../cache'}}},parameters={'training':{},'runtime':{'gpu_count':1}},schema={'fields':[]},snapshot={'path':str(tmp_path/'snapshot')},remote_path=str(path),status='queued',gpu_count=1,code={})

def seed(store,run):
    with store.transaction() as s:
        s['runs']['r']=run;s['queue']=['r']

def test_launch_log_and_cache_do_not_pollute_training_directory(tmp_path):
    run=sample(tmp_path)
    spec=build_launch(run['project'],run,[0])
    assert not Path(spec['launch_log']).is_relative_to(Path(run['remote_path']))
    assert not Path(spec['env']['TORCHINDUCTOR_CACHE_DIR']).is_relative_to(Path(run['remote_path']))
    assert not Path(run['remote_path']).exists()

def test_popen_failure_pauses_queue_and_is_durable(tmp_path,monkeypatch):
    store=Store(tmp_path/'state');run=sample(tmp_path);seed(store,run)
    monkeypatch.setattr(runtime,'gpu_status',lambda:[{'index':0,'available':True}])
    def fail(*a,**kw):raise OSError('failed handoff')
    monkeypatch.setattr(runtime.subprocess,'Popen',fail)
    runtime.tick(store)
    with store.transaction() as state:
        assert state['paused'] and not state['queue']
        assert state['runs']['r']['status']=='failed'

def test_launch_registers_into_newest_group_manifest(tmp_path,monkeypatch):
    store=Store(tmp_path/'state');run=sample(tmp_path);seed(store,run)
    monkeypatch.setattr(runtime,'gpu_status',lambda:[{'index':0,'available':True}])
    monkeypatch.setattr(runtime.subprocess,'Popen',lambda *a,**kw:None)
    groups=tmp_path/'groups';groups.mkdir()
    (groups/'terminal-batch.tsv').write_text('0\t0\t/srv/experiments/old\n')
    monkeypatch.setattr(runtime,'GROUPS_ROOT',groups)
    calls=[]
    monkeypatch.setattr(runtime.subprocess,'run',lambda argv,**kw:calls.append(argv) or type('R',(),{'returncode':0})())
    runtime.tick(store)
    assert calls==[['gpu-groups','register','terminal-batch','0',str(tmp_path/'output')]]

def test_register_manifest_failure_never_fails_launch(tmp_path,monkeypatch):
    store=Store(tmp_path/'state');run=sample(tmp_path);seed(store,run)
    monkeypatch.setattr(runtime,'gpu_status',lambda:[{'index':0,'available':True}])
    monkeypatch.setattr(runtime.subprocess,'Popen',lambda *a,**kw:None)
    monkeypatch.setattr(runtime,'GROUPS_ROOT',tmp_path/'missing')
    def fail(*a,**kw):raise OSError('no gpu-groups')
    monkeypatch.setattr(runtime.subprocess,'run',fail)
    runtime.tick(store)
    with store.transaction() as state:
        assert state['runs']['r']['status']=='starting'

def test_gpu_query_failure_retains_observed_completion(tmp_path,monkeypatch):
    store=Store(tmp_path/'state');run=sample(tmp_path)
    out=Path(run['remote_path']);out.mkdir();(out/'train.log').write_text('arbitrary program finished successfully\n')
    run.update(status='running',attempt_id='attempt',attempt_started_at=0)
    folder=store.root/'attempts/attempt';folder.mkdir(parents=True);atomic_json(folder/'exit.json',{'exit_code':0})
    with store.transaction() as state:state['runs']['r']=run
    def fail():raise OSError('no GPU inventory')
    monkeypatch.setattr(runtime,'gpu_status',fail)
    runtime.tick(store)
    with store.transaction() as state:
        assert state['runs']['r']['status']=='completed'
        assert state['paused']

def test_stopped_tokens_and_attempt_boundary(tmp_path,monkeypatch):
    store=Store(tmp_path/'state');run=sample(tmp_path);out=Path(run['remote_path']);out.mkdir()
    (out/'metrics.jsonl').write_text('{"tokens": 120000000}\n')
    run.update(status='stopping',attempt_id='attempt',attempt_started_at=0,stop_requested=1)
    folder=store.root/'attempts/attempt';folder.mkdir(parents=True);atomic_json(folder/'exit.json',{'exit_code':-15})
    with store.transaction() as state:state['runs']['r']=run
    monkeypatch.setattr(runtime,'gpu_status',lambda:[])
    runtime.tick(store)
    with store.transaction() as state:assert state['runs']['r']['stop_tokens']==120000000

def test_pause_confirm_exit_and_unified_resume(tmp_path, monkeypatch):
    from ai_exp_remote import rpc
    from ai_exp_remote.state import AgentError
    store = Store(tmp_path/'state')
    run = sample(tmp_path)
    run.update(status='running', attempt_id='attempt', attempt_started_at=0)
    with store.transaction() as state:
        state['runs']['r'] = run
    def request(op, payload, identity):
        return rpc.handle(dict(version=1, request_id=identity, operation=op, payload=payload), store.root, False)
    with pytest.raises(AgentError):
        request('pause', {'run_id':'r'}, 'unconfirmed')
    assert request('pause', {'run_id':'r','confirmed':True}, 'pause')['status'] == 'stopping'
    folder = store.root/'attempts/attempt'
    folder.mkdir(parents=True)
    atomic_json(folder/'exit.json', {'exit_code':-15})
    monkeypatch.setattr(runtime, 'gpu_status', lambda: [])
    runtime.tick(store)
    with store.transaction() as state:
        assert state['runs']['r']['status'] == 'paused'
        assert not state['queue']
    monkeypatch.setattr(rpc, 'validate_checkpoint', lambda run: None)
    assert request('resume', {'run_id':'r'}, 'resume')['status'] == 'queued'
    with store.transaction() as state:
        assert state['queue'] == ['r']
        assert 'stop_reason' not in state['runs']['r']


def test_deterministic_launch_configures_cublas(tmp_path):
    run = sample(tmp_path)
    run['parameters']['training']['deterministic'] = True
    run['schema']['fields'] = [{'key': 'deterministic', 'flags': ['--deterministic']}]
    run['project']['integration']['environment']['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
    assert build_launch(run['project'], run, [4])['env']['CUBLAS_WORKSPACE_CONFIG'] == ':4096:8'
