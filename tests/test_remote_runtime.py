import json
from pathlib import Path
import pytest
from ai_exp_remote import runtime
from ai_exp_remote.launcher import build_launch
from ai_exp_remote.state import Store, atomic_json


def sample(tmp_path):
    path=tmp_path/'output'
    return dict(run_id='r',id='r',project_id='p',project={'python':'python3'},parameters={'training':{},'runtime':{'gpu_count':1}},schema={'fields':[]},snapshot={'path':str(tmp_path/'snapshot')},remote_path=str(path),status='queued',gpu_count=1,code={})

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

def test_gpu_query_failure_retains_observed_completion(tmp_path,monkeypatch):
    store=Store(tmp_path/'state');run=sample(tmp_path)
    out=Path(run['remote_path']);out.mkdir();(out/'train.log').write_text('done: tokens\nFinal: 10\n')
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
