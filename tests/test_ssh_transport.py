import pytest
from ai_exp_app.transport.ssh import build_ssh_argv

def test_alias_first():
    argv=build_ssh_argv('/test/ssh','gpu','/tmp/agent.pyz')
    assert argv[:2]==['/test/ssh','gpu']
    assert argv[-1]=='python3 /tmp/agent.pyz rpc'

def test_host_option_rejected():
    with pytest.raises(ValueError):build_ssh_argv('ssh','-oBad','/tmp/agent.pyz')
