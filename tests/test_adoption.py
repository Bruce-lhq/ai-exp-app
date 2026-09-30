import pytest
from ai_exp_remote import adoption, rpc
from ai_exp_remote.state import AgentError, Store


def process(pid=10, parent=1, ticks='100', argv=None):
    return dict(pid=pid, ppid=parent, start_ticks=ticks, boot_id='boot', cwd='/project',
                argv=argv or ['python', '/env/bin/torchrun', 'train.py', '--run-dir', '/runs/a'])


def test_discovery_requires_unique_launcher_and_exact_path():
    p = process()
    assert adoption.discover('/runs/a', {10:p})['launcher'] == p
    with pytest.raises(AgentError):
        adoption.discover('/runs/ab', {10:p})
    with pytest.raises(AgentError):
        adoption.discover('/runs/a', {10:p, 20:process(20)})


def test_reused_pid_never_receives_signal(monkeypatch):
    original = process()
    record = adoption.discover('/runs/a', {10:original})
    monkeypatch.setattr(adoption, 'processes', lambda: {10:process(ticks='200')})
    monkeypatch.setattr(adoption, 'signal_launcher', lambda p: pytest.fail('must not signal reused PID'))
    with pytest.raises(AgentError):
        adoption.pause(record)


def test_pause_signals_only_launcher_waits_for_children(monkeypatch):
    launcher = process()
    child = process(11, 10, argv=['python','train.py','--run-dir','/runs/a'])
    unrelated = process(20, argv=['bash','launch.sh'])
    table = {10:launcher, 11:child, 20:unrelated}
    record = adoption.discover('/runs/a', table)
    monkeypatch.setattr(adoption, 'processes', lambda: table)
    signals = []
    monkeypatch.setattr(adoption, 'signal_launcher', lambda p: signals.append(p['pid']))
    adoption.pause(record)
    assert signals == [10]
    assert adoption.observe(record, {11:child, 20:unrelated})['status'] == 'stopping'
    assert adoption.observe(record, {20:unrelated})['status'] == 'paused'


def test_adopt_in_read_only_mode_does_not_enable_scheduler(tmp_path, monkeypatch):
    root = tmp_path/'state'
    (tmp_path/'read-only').touch()
    monkeypatch.setattr(rpc, 'external_runs', lambda *a: [dict(id='e',remote_path='/runs/a')])
    monkeypatch.setattr(adoption, 'processes', lambda: {10:process()})
    monkeypatch.setattr(rpc, 'ensure_daemon', lambda *a: pytest.fail('must not enable scheduler'))
    def request(op, payload):
        return rpc.handle(dict(version=1,request_id=op,operation=op,payload=payload),root)
    assert request('adopt_external', {'run_id':'e'})['adopted']
    with pytest.raises(AgentError):
        request('pause_external', {'run_id':'e'})
    with Store(root).transaction() as state:
        assert not state['runs'] and not state['queue']
    calls = []
    monkeypatch.setattr(adoption, 'signal_launcher', lambda p: calls.append(p['pid']))
    request('pause_external', {'run_id':'e','confirmed':True})
    request('pause_external', {'run_id':'e','confirmed':True})
    assert calls == [10]


def test_status_hides_external_duplicates_of_managed_runs(tmp_path, monkeypatch):
    store = Store(tmp_path/'state')
    with store.transaction() as state:
        state['runs']['r'] = dict(id='r', remote_path='/runs/a', status='running')
    monkeypatch.setattr(rpc, 'external_runs', lambda *a: [
        dict(id='external-x', remote_path='/runs/a', external=True),
        dict(id='external-y', remote_path='/runs/b', external=True)])
    monkeypatch.setattr(rpc, 'gpu_status', lambda: [])
    result = rpc.handle(dict(version=1, request_id='s', operation='status', payload={}), tmp_path/'state', False)
    assert [r['id'] for r in result['external_runs']] == ['external-y']


def test_remove_external_forgets_paused_record_only(tmp_path, monkeypatch):
    monkeypatch.setattr(rpc, 'external_runs', lambda *a: [dict(id='e', remote_path='/runs/a')])
    monkeypatch.setattr(adoption, 'processes', lambda: {10: process()})
    monkeypatch.setattr(adoption, 'signal_launcher', lambda p: None)
    def request(op, payload):
        return rpc.handle(dict(version=1, request_id=op, operation=op, payload=payload), tmp_path/'state', False)
    request('adopt_external', {'run_id': 'e'})
    with pytest.raises(AgentError):
        request('remove_external', {'run_id': 'e', 'confirmed': True})
    request('pause_external', {'run_id': 'e', 'confirmed': True})
    monkeypatch.setattr(adoption, 'processes', lambda: {})
    request('status', {})
    with pytest.raises(AgentError):
        request('remove_external', {'run_id': 'e'})
    assert request('remove_external', {'run_id': 'e', 'confirmed': True})['removed']
    with Store(tmp_path/'state').transaction() as state:
        assert not state['adoptions']


def test_paused_adopted_run_reports_progress_from_metrics(tmp_path, monkeypatch):
    import json as jsonlib
    monkeypatch.setattr(rpc, 'external_runs', lambda *a: [])
    monkeypatch.setattr(adoption, 'processes', lambda: {})
    monkeypatch.setattr(adoption, 'signal_launcher', lambda p: None)
    run_dir = tmp_path/'runs/a'; run_dir.mkdir(parents=True)
    (run_dir/'args.json').write_text(jsonlib.dumps({'max_tokens': 2000000000, 'warmup_tokens': 20000000}))
    (run_dir/'metrics.jsonl').write_text('\n'.join(
        jsonlib.dumps({'tokens_seen': i*100_000_000, 'elapsed_s': i*1000.0, 'event': 'train'})
        for i in range(1, 4)) + '\n')
    with Store(tmp_path/'state').transaction() as state:
        state.setdefault('adoptions', {})['e'] = dict(id='e', remote_path=str(run_dir), status='paused',
                                       launcher=dict(pid=10, start_ticks='1', boot_id='boot'), members=[])
    result = rpc.handle(dict(version=1, request_id='s', operation='status', payload={}), tmp_path/'state', False)
    entry = next(r for r in result['external_runs'] if r['id'] == 'e')
    assert entry['status'] == 'paused' and entry['adopted']
    assert entry['progress'] == '0.30B/2B' and 'remaining' not in entry
