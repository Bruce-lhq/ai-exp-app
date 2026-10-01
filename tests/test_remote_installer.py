import json
import subprocess
import sys
import zipfile
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
