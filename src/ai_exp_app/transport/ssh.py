"""JSON-over-stdin SSH transport; user values never enter shell commands."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

from ai_exp_app.config import local_settings

DEFAULT_AGENT = '.local/share/ai-exp-app/agent.pyz'

class RemoteError(RuntimeError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


def build_ssh_argv(ssh_path, alias, agent_path, python='python3'):
    if not alias or alias.startswith('-') or any(c.isspace() for c in alias):
        raise ValueError('invalid SSH alias')
    # Keep the user's ~/.ssh/config connection reuse.  In particular, the
    # gpu alias uses ControlMaster auto + ControlPersist, so a terminal login
    # is reused by the workbench instead of opening a fresh password session.
    return [ssh_path, alias, '-o', 'ConnectTimeout=12', '-o', 'ServerAliveInterval=5',
            '-o', 'ServerAliveCountMax=2', shlex.quote(python) + ' ' + shlex.quote(agent_path) + ' rpc']


def build_agent_argv(alias, settings, python_args=None):
    """Reuse the deployed agent and scheduler, locally or over SSH."""
    agent = os.environ.get('AI_EXP_REMOTE_AGENT', settings['remote_agent'])
    python = settings['remote_python']
    if settings.get('connection_mode', 'ssh') not in {'ssh', 'local'}:
        raise ValueError('连接方式必须为 ssh 或 local')
    if settings.get('connection_mode', 'ssh') == 'local':
        if alias != settings['ssh_alias']:
            raise ValueError('本机代理模式只能访问配置中的主机别名')
        if any(not Path(settings.get(key, '')).is_absolute()
               for key in ('remote_agent', 'remote_python', 'remote_state_dir')):
            raise ValueError('本机代理、Python 和既有状态目录必须为绝对路径')
        return [python, *(python_args if python_args is not None else [agent, 'rpc'])]
    wrapper = Path.home() / '.local/bin/ssh'
    argv = build_ssh_argv(str(wrapper) if wrapper.is_file() and sys.platform != 'win32' else 'ssh',
                          alias, agent, python=python)
    if python_args is not None:
        argv[-1] = shlex.join([python, *python_args])
    return argv


def call_remote(alias, request, timeout_s=20):
    settings = local_settings()
    argv = build_agent_argv(alias, settings)
    local = settings.get('connection_mode', 'ssh') == 'local'
    environment = {'env': dict(os.environ, AI_EXP_REMOTE_ROOT=settings['remote_state_dir'])} if local else {}
    last_error = None
    for attempt in range(2):
        try:
            response = subprocess.run(argv, input=json.dumps(request, allow_nan=False, ensure_ascii=False),
                                      text=True, encoding='utf-8', capture_output=True, timeout=timeout_s, **environment)
        except subprocess.TimeoutExpired as exc:
            last_error = RemoteError('LOCAL_TIMEOUT' if local else 'SSH_TIMEOUT', '连接超时；提交结果可能未知，请使用原请求 ID 查询')
            if attempt == 0:
                time.sleep(0.6)
                continue
            raise last_error from exc
        if response.returncode == 0:
            break
        last_error = RemoteError('LOCAL_AGENT' if local else 'SSH_CONNECTION',
                                 '本机代理执行失败' if local else '远端连接失败', response.stderr[-3000:])
        if attempt == 0:
            time.sleep(0.6)
            continue
        raise last_error
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
