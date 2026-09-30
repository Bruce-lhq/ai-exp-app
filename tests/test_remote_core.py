import json
from pathlib import Path
import sys
import pytest
from ai_exp_remote.state import Store, AgentError
from ai_exp_remote.files import list_directory,read_file_chunk,file_manifest
from ai_exp_remote.projects import read_schema
from ai_exp_remote.rpc import handle

def request(op,payload=None,id='r1'):return dict(version=1,request_id=id,operation=op,payload=payload or {})

def test_state_corruption_fails_closed(tmp_path):
    store=Store(tmp_path)
    with store.transaction() as state:state['paused']=True
    (tmp_path/'state.json').write_text('broken')
    with pytest.raises(AgentError):
        with store.transaction():pass

def test_read_does_not_change_revision(tmp_path):
    a=handle(request('status'),tmp_path,False)
    b=handle(request('status'),tmp_path,False)
    c=handle(request('status'),tmp_path,False)
    assert b['revision']==c['revision']

def test_idempotency_and_conflict(tmp_path):
    req=request('queue_pause')
    handle(req,tmp_path,False);handle(req,tmp_path,False)
    result=handle(request('status'),tmp_path,False)
    assert len(result['events'])==1
    with pytest.raises(AgentError):handle(request('queue_resume'),tmp_path,False)

def test_directory_names_not_executed(tmp_path):
    name='a $(touch HACK) " b';(tmp_path/name).mkdir()
    assert list_directory({'path':str(tmp_path)})['entries'][0]['name']==name

def test_chunk_checks_version(tmp_path):
    f=tmp_path/'train.log';f.write_text('hello')
    item=file_manifest({'path':str(tmp_path)})['files'][0]
    assert read_file_chunk(dict(path=str(tmp_path),name=f.name,offset=1,length=2,mtime_ns=item['mtime_ns']))['data']=='ZWw='
    f.write_text('updated')
    with pytest.raises(AgentError):read_file_chunk(dict(path=str(tmp_path),name=f.name,mtime_ns=item['mtime_ns']))

def test_schema_uses_parser_without_main(tmp_path):
    (tmp_path/'train.py').write_text('import argparse\ndef build_parser():\n p=argparse.ArgumentParser()\n p.add_argument("--lr",type=float,default=.01)\n p.add_argument("--run-dir")\n return p\nif __name__ == "__main__": raise RuntimeError("must not run")\n')
    result=read_schema(dict(path=str(tmp_path),python=sys.executable))
    assert result['fields'][0]['key']=='lr'
    assert len(result['fields'])==2
    assert result['controlled_keys']==[]


def test_failed_run_log_contains_launcher_traceback(tmp_path):
    state = Store(tmp_path/'state')
    run_dir = tmp_path/'run'; run_dir.mkdir()
    attempt = tmp_path/'attempt'; attempt.mkdir()
    (run_dir/'train.log').write_text('CONFIG_1/1\n')
    (attempt/'launch.log').write_text('CONFIG_1/1\nRuntimeError: CUDA failure\n')
    with state.transaction() as s:
        s['runs']['failed'] = {'id': 'failed', 'status': 'failed', 'remote_path': str(run_dir), 'attempt_dir': str(attempt)}
    result = handle(request('read_log', {'run_id': 'failed'}), state.root, False)
    assert 'RuntimeError: CUDA failure' in result['content']


def test_append_snapshot_reads_original_prefix_but_rejects_replacement(tmp_path):
    import base64
    f = tmp_path / 'metrics.jsonl'
    f.write_bytes(b'first\n')
    item = file_manifest({'path': str(tmp_path)})['files'][0]
    request = dict(path=str(tmp_path), name=f.name, snapshot_size=item['size'], inode=item['inode'], mtime_ns=item['mtime_ns'])
    with f.open('ab') as stream: stream.write(b'second\n')
    assert base64.b64decode(read_file_chunk(request)['data']) == b'first\n'
    replacement = tmp_path / 'replacement'
    replacement.write_bytes(b'changed file\n')
    replacement.replace(f)
    with pytest.raises(AgentError): read_file_chunk(request)
    item = file_manifest({'path': str(tmp_path)})['files'][0]
    request.update(inode=item['inode'], snapshot_size=item['size'])
    f.write_bytes(b'x')
    with pytest.raises(AgentError): read_file_chunk(request)
