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
    monkeypatch.setattr(sync.sys, 'platform', platform)
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
