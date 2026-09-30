import sys
import pytest
from ai_exp_remote.rpc import handle
from ai_exp_remote.state import AgentError

def test_queue_submission_freezes_and_deduplicates(tmp_path):
    source=tmp_path/'project';source.mkdir()
    (source/'train.py').write_text('import argparse\ndef build_parser():\n p=argparse.ArgumentParser()\n p.add_argument("--lr",type=float,default=.1)\n p.add_argument("--run-dir")\n p.add_argument("--data-root")\n return p\n')
    payload=dict(run_id='test',project_id='p',display_name='Test',mode='queue',code={'kind':'working_tree'},project=dict(path=str(source),python=sys.executable,runs_root=str(tmp_path/'runs'),data_root=str(tmp_path/'data')),parameters=dict(training={'lr':.2},runtime={'gpu_count':2}))
    req=dict(version=1,request_id='request-1',operation='submit',payload=payload)
    first=handle(req,tmp_path/'state',False)
    (source/'train.py').write_text('changed')
    second=handle(req,tmp_path/'state',False)
    assert first['run_id']==second['run_id']
    assert first['resolved_parameters']['lr']==.2
    with pytest.raises(AgentError):handle(dict(req,payload=dict(payload,display_name='Other')),tmp_path/'state',False)
    status=handle(dict(version=1,request_id='s',operation='status',payload={}),tmp_path/'state',False)
    assert status['queue']==['test']

def test_submission_sanitizes_infinite_parser_defaults(tmp_path):
    source=tmp_path/'project';source.mkdir()
    (source/'train.py').write_text('import argparse\ndef build_parser():\n p=argparse.ArgumentParser()\n p.add_argument("--tau",type=float,default=float("inf"))\n p.add_argument("--run-dir")\n p.add_argument("--data-root")\n return p\n')
    payload=dict(run_id='inftest',project_id='p',display_name='Inf',mode='queue',code={'kind':'working_tree'},project=dict(path=str(source),python=sys.executable,runs_root=str(tmp_path/'runs'),data_root=str(tmp_path/'data')),parameters=dict(training={},runtime={'gpu_count':1}))
    run=handle(dict(version=1,request_id='r',operation='submit',payload=payload),tmp_path/'state',False)
    assert run['resolved_parameters']['tau'] is None
    assert next(f for f in run['schema']['fields'] if f['key']=='tau')['default'] is None
    status=handle(dict(version=1,request_id='s',operation='status',payload={}),tmp_path/'state',False)
    assert status['queue']==['inftest']
