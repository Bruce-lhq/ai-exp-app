"""Shared localhost service lifecycle for native windows and command-line clients."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from ai_exp_app.config import Config

# Local control must never travel through a machine-wide HTTP proxy.
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def is_our_service(value):
    return isinstance(value, dict) and value.get('app') == 'ai-exp-app' and bool(value.get('instance_id'))


def health(url):
    try:
        with LOCAL_HTTP.open(url + '/api/health', timeout=1) as response:
            value = json.load(response)
    except urllib.error.URLError as exc:
        if isinstance(exc, urllib.error.HTTPError):
            raise RuntimeError('端口由其他应用占用') from exc
        return None
    except (ValueError, TimeoutError) as exc:
        raise RuntimeError('端口由其他应用占用或服务未响应') from exc
    if not is_our_service(value):
        raise RuntimeError('端口由其他应用占用')
    return value


def service_status(config=None):
    config = config or Config.load()
    url = f'http://127.0.0.1:{config.port}'
    value = health(url)
    if value is None:
        return None
    path = config.data_dir / 'service.json'
    try:
        identity = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise RuntimeError('此端口的工作台属于其他工作空间') from exc
    if identity.get('instance_id') != value['instance_id'] or identity.get('url') != url:
        raise RuntimeError('此端口的工作台属于其他工作空间')
    return identity


def start_service(config=None, command=None, timeout=15):
    config = config or Config.load()
    identity = service_status(config)
    if identity:
        return identity
    env = dict(os.environ, AI_EXP_DATA_DIR=str(config.data_dir), AI_EXP_CACHE_ROOT=str(config.cache_root),
               AI_EXP_CONFIG_FILE=str(config.config_file), AI_EXP_WEB_ROOT=str(config.web_root), AI_EXP_PORT=str(config.port))
    if command is None:
        command = [sys.executable, 'service', 'run'] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'ai_exp_app.desktop']
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    with (config.data_dir / 'service.log').open('ab') as log:
        process = subprocess.Popen(command, env=env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        identity = service_status(config)
        if identity:
            return identity
        if process.poll() not in (None, 0):
            raise RuntimeError('本地服务启动失败，请查看 ' + str(config.data_dir / 'service.log'))
        time.sleep(.1)
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    raise RuntimeError('本地服务启动超时，请查看 ' + str(config.data_dir / 'service.log'))


def stop_service(config=None, timeout=10):
    config = config or Config.load()
    identity = service_status(config)
    if identity is None:
        return False
    token = (config.data_dir / 'desktop-token').read_text(encoding='utf-8').strip()
    request = urllib.request.Request(identity['url'] + '/api/desktop/shutdown', data=b'{}', method='POST',
                                     headers={'X-Desktop-Token': token, 'Content-Type': 'application/json'})
    with LOCAL_HTTP.open(request, timeout=2) as response:
        if not json.load(response).get('ok'):
            raise RuntimeError('当前服务不支持安全退出')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service_status(config) is None and not (config.data_dir / 'service.json').exists():
            return True
        time.sleep(.1)
    raise RuntimeError('本地服务未在限定时间内退出')
