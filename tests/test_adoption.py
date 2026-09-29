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
