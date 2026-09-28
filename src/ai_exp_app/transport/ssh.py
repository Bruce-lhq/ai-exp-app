"""JSON-over-stdin SSH transport; user values never enter shell commands."""
import json
import os
from pathlib import Path
import shlex
import subprocess

DEFAULT_AGENT = '/your_exp/ai_exp_app/agent.pyz'

class RemoteError(RuntimeError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


def build_ssh_argv(ssh_path, alias, agent_path):
    if not alias or alias.startswith('-') or any(c.isspace() for c in alias):
        raise ValueError('invalid SSH alias')
    return [ssh_path, alias, '-o', 'ControlMaster=no', '-o', 'ControlPath=none', '-o', 'ConnectTimeout=12', '-o', 'ServerAliveInterval=5',
            '-o', 'ServerAliveCountMax=2', 'python3 ' + shlex.quote(agent_path) + ' rpc']


def call_remote(alias, request, timeout_s=20):
    wrapper = Path.home() / '.local/bin/ssh'
    argv = build_ssh_argv(str(wrapper) if wrapper.exists() else 'ssh', alias,
                          os.environ.get('AI_EXP_REMOTE_AGENT', DEFAULT_AGENT))
    try:
        response = subprocess.run(argv, input=json.dumps(request, allow_nan=False),
                                  text=True, capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise RemoteError('SSH_TIMEOUT', '连接超时；提交结果可能未知，请使用原请求 ID 查询') from exc
    if response.returncode:
        raise RemoteError('SSH_CONNECTION', '远端连接失败', response.stderr[-3000:])
    try:
        data = json.loads(response.stdout)
        if data['version'] != 1 or data['request_id'] != request['request_id']:
            raise ValueError('mismatched response')
    except (ValueError, KeyError) as exc:
        raise RemoteError('PROTOCOL_ERROR', '远端返回无效协议') from exc
    if not data['ok']:
        error = data['error']
        raise RemoteError(error['code'], error['message'], error.get('details'))
    return data['result']
