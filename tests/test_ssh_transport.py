import os
import pytest
from ai_exp_app.transport.ssh import build_ssh_argv

def test_alias_first():
    argv=build_ssh_argv('/test/ssh','gpu','/tmp/agent.pyz')
    assert argv[:2]==['/test/ssh','gpu']
    assert argv[-1]=='python3 /tmp/agent.pyz rpc'

def test_host_option_rejected():
    with pytest.raises(ValueError):build_ssh_argv('ssh','-oBad','/tmp/agent.pyz')


def test_remote_interpreter_and_agent_are_shell_quoted():
    import shlex
    python = '/environment with spaces/python'
    agent = '/deployment with spaces/agent.pyz'
    argv = build_ssh_argv('ssh', 'gpu', agent, python=python)
    assert shlex.split(argv[-1]) == [python, agent, 'rpc']


@pytest.mark.parametrize('platform,use_wrapper', [('win32', False), ('darwin', True), ('linux', True)])
def test_rpc_uses_configured_python_utf8_and_platform_ssh(monkeypatch, tmp_path, platform, use_wrapper):
    import json
    import shlex
    import subprocess
    from pathlib import Path
    from ai_exp_app.transport import ssh
    wrapper = tmp_path / '.local' / 'bin' / 'ssh'
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text('wrapper')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(ssh.sys, 'platform', platform)
    monkeypatch.delenv('AI_EXP_REMOTE_AGENT', raising=False)
    monkeypatch.setattr(ssh, 'local_settings', lambda: {
        'remote_agent': '/deployment with spaces/agent.pyz', 'remote_python': '/env with spaces/python'})
    observed = {}
    request = {'version': 1, 'request_id': 'unicode-request', 'operation': 'inspect', 'payload': {'name': '实验'}}

    def run(argv, **kwargs):
        observed.update(argv=argv, options=kwargs)
        return subprocess.CompletedProcess(argv, 0, json.dumps({
            'version': 1, 'request_id': request['request_id'], 'ok': True, 'result': {'name': '实验'}}, ensure_ascii=False), '')

    monkeypatch.setattr(ssh.subprocess, 'run', run)
    assert ssh.call_remote('gpu', request) == {'name': '实验'}
    assert observed['argv'][0] == (str(wrapper) if use_wrapper else 'ssh')
    assert shlex.split(observed['argv'][-1]) == ['/env with spaces/python', '/deployment with spaces/agent.pyz', 'rpc']
    assert observed['options']['encoding'] == 'utf-8'
    assert observed['options']['text'] is True
    assert '实验' in observed['options']['input']


@pytest.mark.parametrize('platform,use_wrapper', [('win32', False), ('linux', True)])
def test_checkpoint_stream_uses_configured_python_and_binary_io(monkeypatch, tmp_path, platform, use_wrapper):
    import shlex
    import subprocess
    from pathlib import Path
    from ai_exp_app.config import Config
    from ai_exp_app.history import sync
    wrapper = tmp_path / '.local' / 'bin' / 'ssh'
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text('wrapper')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    from ai_exp_app.transport import ssh
    monkeypatch.setattr(ssh.sys, 'platform', platform)
    config = Config.load(tmp_path / 'workspace')
    config.save_local_settings({'remote_python': '/remote environment/python', 'remote_runs_root': '/srv/runs'})
    monkeypatch.setenv('AI_EXP_CONFIG_FILE', str(config.config_file))
    observed = {}
    content = b'\x00\xffcheckpoint\x00'

    def run(argv, **kwargs):
        observed.update(argv=argv, options=kwargs)
        kwargs['stdout'].write(content)
        return subprocess.CompletedProcess(argv, 0, None, b'')

    monkeypatch.setattr(sync.subprocess, 'run', run)
    target = tmp_path / 'download' / 'latest.pt'
    sync.download_checkpoint({'path': '/srv/runs/example', 'ssh_alias': 'gpu'},
                             {'size': len(content), 'mtime_ns': 123}, target)
    assert target.read_bytes() == content
    assert observed['argv'][0] == (str(wrapper) if use_wrapper else 'ssh')
    command = shlex.split(observed['argv'][-1])
    assert command[:2] == ['/remote environment/python', '-c']
    assert "'/srv/runs/example'" in command[2]
    assert 'encoding' not in observed['options'] and 'text' not in observed['options']


def test_rpc_decodes_real_utf8_process_output_under_non_utf8_default(monkeypatch):
    import subprocess
    import sys
    from ai_exp_app.transport import ssh
    real_run = subprocess.run
    monkeypatch.setattr(subprocess, '_text_encoding', lambda: 'cp1252')
    monkeypatch.setattr(ssh, 'local_settings', lambda: {'remote_agent': '/srv/agent.pyz', 'remote_python': 'python3'})
    script = ('import json,sys; request=json.loads(sys.stdin.buffer.read().decode("utf-8")); '
              'response={"version":1,"request_id":request["request_id"],"ok":True,"result":request["payload"]}; '
              'sys.stdout.buffer.write(json.dumps(response,ensure_ascii=False).encode("utf-8"))')

    def local_process_instead_of_ssh(argv, **kwargs):
        return real_run([sys.executable, '-c', script], **kwargs)

    monkeypatch.setattr(ssh.subprocess, 'run', local_process_instead_of_ssh)
    assert ssh.call_remote('gpu', {'version': 1, 'request_id': 'unicode', 'operation': 'inspect',
                                  'payload': {'name': '中文实验'}}) == {'name': '中文实验'}


def test_local_agent_does_not_use_ssh_and_rejects_other_host(monkeypatch):
    from ai_exp_app.transport.ssh import build_agent_argv
    monkeypatch.delenv('AI_EXP_REMOTE_AGENT', raising=False)
    settings = {'connection_mode': 'local', 'ssh_alias': 'gpu',
                'remote_agent': '/srv/app with spaces/agent.pyz', 'remote_python': '/srv/env/python',
                'remote_state_dir': '/srv/existing-state'}
    assert build_agent_argv('gpu', settings) == ['/srv/env/python', settings['remote_agent'], 'rpc']
    assert build_agent_argv('gpu', settings, ['-c', 'print(1)']) == ['/srv/env/python', '-c', 'print(1)']
    with pytest.raises(ValueError, match='主机别名'):
        build_agent_argv('different-host', settings)


def test_local_rpc_uses_real_agent_protocol(tmp_path, monkeypatch):
    import sys
    import uuid
    import zipapp
    from pathlib import Path
    from ai_exp_app.config import Config
    from ai_exp_app.transport.ssh import call_remote
    agent = tmp_path / 'agent.pyz'
    zipapp.create_archive(Path(__file__).resolve().parents[1] / 'remote', agent,
                         filter=lambda p: '__pycache__' not in p.parts)
    config = Config.load(tmp_path / 'web-workspace')
    config.save_local_settings({'connection_mode': 'local', 'remote_agent': str(agent),
                                'remote_python': sys.executable, 'remote_state_dir': str(tmp_path / 'state'),
                                'remote_runs_root': str(tmp_path / 'runs')})
    monkeypatch.setenv('AI_EXP_CONFIG_FILE', str(config.config_file))
    monkeypatch.delenv('AI_EXP_REMOTE_AGENT', raising=False)
    folder = tmp_path / 'runs' / 'example'
    folder.mkdir(parents=True)
    (folder / 'train.log').write_text('中文实验日志', encoding='utf-8')
    value = call_remote('gpu', {'version': 1, 'request_id': str(uuid.uuid4()), 'operation': 'read_log',
                               'payload': {'path': str(folder)}})
    assert value['content'] == '中文实验日志'
    assert not (tmp_path / 'state').exists()  # Reading logs must not create another scheduler.


def test_local_checkpoint_stream_preserves_bytes(tmp_path, monkeypatch):
    import sys
    from ai_exp_app.config import Config
    from ai_exp_app.history.sync import download_checkpoint
    config = Config.load(tmp_path / 'workspace')
    config.save_local_settings({'connection_mode': 'local', 'remote_agent': str(tmp_path / 'agent.pyz'),
                                'remote_python': sys.executable, 'remote_state_dir': str(tmp_path / 'state')})
    monkeypatch.setenv('AI_EXP_CONFIG_FILE', str(config.config_file))
    folder = tmp_path / 'source'; folder.mkdir()
    origin = folder / 'latest.pt'; origin.write_bytes(b'\x00\xffcheckpoint')
    stat = origin.stat()
    target = tmp_path / 'cache' / 'latest.pt'
    download_checkpoint({'path': str(folder), 'ssh_alias': 'gpu'},
                        {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}, target)
    assert target.read_bytes() == origin.read_bytes()


@pytest.mark.skipif(os.name == 'nt', reason='GPU agent state locking uses POSIX fcntl')
def test_local_rpc_reads_the_existing_scheduler_state(tmp_path, monkeypatch):
    import sys
    import uuid
    from ai_exp_app.config import Config
    from ai_exp_app.remote_install import build_agent
    from ai_exp_app.transport.ssh import call_remote
    from ai_exp_remote.state import Store
    state_root = tmp_path / 'existing-agent-state'
    with Store(state_root).transaction() as state:
        state['requests']['previous-submission'] = {'digest': 'previous', 'result': {'run_id': 'existing-run'}}
        state['queue'] = ['existing-run']
    before = (state_root / 'state.json').read_bytes()
    agent = build_agent(tmp_path / 'agent.pyz')
    config = Config.load(tmp_path / 'web-workspace')
    config.save_local_settings({'connection_mode': 'local', 'remote_agent': str(agent),
                                'remote_python': sys.executable, 'remote_state_dir': str(state_root)})
    monkeypatch.setenv('AI_EXP_CONFIG_FILE', str(config.config_file))
    monkeypatch.delenv('AI_EXP_REMOTE_AGENT', raising=False)
    value = call_remote('gpu', {'version': 1, 'request_id': str(uuid.uuid4()), 'operation': 'request_status',
                               'payload': {'request_id': 'previous-submission'}})
    assert value['result']['run_id'] == 'existing-run'
    assert (state_root / 'state.json').read_bytes() == before


@pytest.mark.skipif(os.name == 'nt', reason='GPU agent state locking uses POSIX fcntl')
def test_web_api_monitors_existing_local_agent_without_replacing_queue(tmp_path, monkeypatch):
    import sys
    from ai_exp_app.app import create_app
    from ai_exp_app.config import Config
    from ai_exp_app.remote_install import build_agent
    from ai_exp_remote.state import Store
    from fastapi.testclient import TestClient
    deployment = tmp_path / 'agent-deployment'
    state_root = deployment / 'state'
    with Store(state_root).transaction() as state:
        state['runs']['existing-run'] = {'run_id': 'existing-run', 'display_name': '原有实验',
                                        'status': 'queued', 'remote_path': str(tmp_path / 'runs/example')}
        state['queue'] = ['existing-run']
    (deployment / 'read-only').touch()  # Never spawn a scheduler in this read-only acceptance test.
    before = (state_root / 'state.json').read_bytes()
    agent = build_agent(deployment / 'agent.pyz')
    config = Config.load(tmp_path / 'workspace')
    config.save_local_settings({'connection_mode': 'local', 'remote_agent': str(agent),
                                'remote_python': sys.executable, 'remote_state_dir': str(state_root)})
    monkeypatch.setenv('AI_EXP_CONFIG_FILE', str(config.config_file))
    monkeypatch.delenv('AI_EXP_REMOTE_AGENT', raising=False)
    monkeypatch.setenv('AI_EXP_REMOTE_ROOT', '/wrong/inherited/state')
    app = create_app(config.data_dir)
    app.state.store.put('projects', 'p', {'id': 'p', 'ssh_alias': 'gpu', 'remote_path': '/srv/project'})
    with TestClient(app) as client:
        client.get('/')
        response = client.post('/api/connection/refresh', json={}, headers={'Origin': 'http://testserver'})
        assert response.json()['connected'] is True
        assert client.get('/api/runs').json()[0]['display_name'] == '原有实验'
        assert client.get('/api/queue').json()['runs'][0]['run_id'] == 'existing-run'
    assert (state_root / 'state.json').read_bytes() == before
