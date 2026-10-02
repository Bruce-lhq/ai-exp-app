import json
import subprocess
import sys
import zipfile
import pytest
from ai_exp_app.config import Config
from ai_exp_app.remote_install import build_agent, install_agent


def test_agent_zip_is_complete_and_runs_without_source_checkout(tmp_path):
    artifact = build_agent(tmp_path / 'agent.pyz')
    with zipfile.ZipFile(artifact) as archive:
        assert '__main__.py' in archive.namelist()
        assert 'ai_exp_remote/rpc.py' in archive.namelist()
        for name in archive.namelist():
            if name.endswith('.py'):
                compile(archive.read(name), name, 'exec')
    process = subprocess.run([sys.executable, str(artifact), 'rpc'], input=json.dumps({'version':1,'request_id':'zip','method':'unknown','params':{}}), text=True, capture_output=True, cwd=tmp_path)
    reply = json.loads(process.stdout)
    assert reply['request_id'] == 'zip' and reply['version'] == 1
    assert not reply['ok']


def test_installer_uses_configured_python_and_sends_atomic_archive(tmp_path, monkeypatch):
    config = Config.load(tmp_path / 'workspace')
    config.save_local_settings({'ssh_alias':'example','remote_root':'/workspace/example','remote_runs_root':'/workspace/runs','remote_python':'/opt/custom env/bin/python'})
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: calls.append((args, kwargs)))
    value = install_agent(config, read_only=True)
    assert value['installed'] == '/workspace/example/agent.pyz'
    args, kwargs = calls[0]
    assert args[0][1] == 'example'
    assert args[0][-1].startswith("'/opt/custom env/bin/python' -c ")
    assert kwargs['input'][:2] == b'PK'
    assert value['read_only']


def test_local_mode_never_redeploys_or_ssh_connects(monkeypatch, tmp_path):
    import sys
    from ai_exp_app.config import Config
    from ai_exp_app.remote_install import install_agent
    config = Config.load(tmp_path)
    config.save_local_settings({'connection_mode': 'local', 'remote_agent': str(tmp_path / 'agent.pyz'),
                                'remote_python': sys.executable, 'remote_state_dir': str(tmp_path / 'existing-state')})
    def unexpected(*args, **kwargs):
        raise AssertionError('Local deployment must never call SSH')
    monkeypatch.setattr('ai_exp_app.remote_install.subprocess.run', unexpected)
    with pytest.raises(ValueError, match='复用既有代理'):
        install_agent(config)
    assert not (tmp_path / 'agent.pyz').exists()


@pytest.mark.skipif(sys.platform == 'win32', reason='Agent execution requires POSIX process supervision')
def test_built_agent_executes_attempt_without_entering_rpc(tmp_path):
    import os
    artifact = build_agent(tmp_path / 'agent.pyz')
    spec = tmp_path / 'spec.json'
    log = tmp_path / 'launch.log'
    spec.write_text(json.dumps({'argv': [sys.executable, '-c', 'print("tiny isolated acceptance")'],
                               'cwd': str(tmp_path), 'env': dict(os.environ), 'launch_log': str(log)}))
    result = subprocess.run([sys.executable, str(artifact), 'attempt', str(spec)],
                            capture_output=True, timeout=15, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / 'exit.json').read_text())['exit_code'] == 0
    assert 'tiny isolated acceptance' in log.read_text()
