import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest
from ai_exp_app import config as settings
from ai_exp_app import locking
from ai_exp_app.config import Config
from ai_exp_app.locking import FileLock
from ai_exp_app.platform_runtime import LOCAL_HTTP, service_status, start_service, stop_service


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.mark.parametrize('platform,expected', [
    ('darwin', 'Library/Application Support/AI Experiment'),
    ('win32', 'windows-data/AI Experiment'),
    ('linux', 'xdg-data/ai-exp-app'),
])
def test_platform_directories(monkeypatch, tmp_path, platform, expected):
    monkeypatch.setattr(settings.sys, 'platform', platform)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'windows-data'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'xdg-data'))
    assert settings.platform_data_dir() == tmp_path / expected


def test_default_preserves_existing_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'ROOT', tmp_path / 'source')
    monkeypatch.setattr(settings, 'platform_data_dir', lambda: tmp_path / 'installed')
    for name in ('AI_EXP_DATA_DIR', 'AI_EXP_CONFIG_FILE', 'AI_EXP_CACHE_ROOT'):
        monkeypatch.delenv(name, raising=False)
    assert Config.load().data_dir == tmp_path / 'installed'
    legacy = tmp_path / 'source' / '.local'
    legacy.mkdir(parents=True)
    (legacy / 'app.sqlite3').touch()
    assert Config.load().data_dir == legacy
    assert Config.load().cache_root == tmp_path / 'source' / 'gpu_downloads'
    (tmp_path / 'installed' / 'app.sqlite3').touch()
    assert Config.load().data_dir == tmp_path / 'installed'


def test_windows_lock_uses_byte_lock_without_fcntl(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(locking, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setitem(sys.modules, 'msvcrt', SimpleNamespace(
        LK_NBLCK=1, LK_UNLCK=2, locking=lambda fd, operation, size: calls.append((operation, size))))
    with FileLock(tmp_path / 'service.lock'):
        assert calls == [(1, 1)]
    assert calls == [(1, 1), (2, 1)]


def test_lock_excludes_other_process_and_releases(tmp_path, monkeypatch):
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).parents[1] / 'src'))
    command = [sys.executable, '-c',
               'from pathlib import Path; from ai_exp_app.locking import FileLock; '
               'import sys; lock=FileLock(Path(sys.argv[1])); lock.__enter__()', str(tmp_path / 'lock')]
    with FileLock(tmp_path / 'lock'):
        result = subprocess.run(command, capture_output=True)
        assert result.returncode != 0
        assert b'BlockingIOError' in result.stderr
    assert subprocess.run(command, capture_output=True).returncode == 0


def test_actual_shared_service_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).parents[1] / 'src'))
    config = Config(tmp_path, tmp_path / 'cache', port=free_port(), config_file=tmp_path / 'config.local.json')
    assert service_status(config) is None
    assert stop_service(config) is False
    identity = start_service(config)
    try:
        assert identity['instance_id']
        assert start_service(config) == identity
        # Another workspace cannot authenticate or claim this instance.
        other = tmp_path / 'other'
        other.mkdir()
        with pytest.raises(RuntimeError, match='其他工作空间'):
            stop_service(Config(other, other / 'cache', port=config.port))
        request = urllib.request.Request(identity['url'] + '/api/desktop/shutdown', data=b'{}',
                                         headers={'X-Desktop-Token': 'incorrect', 'Content-Type': 'application/json'})
        with pytest.raises(urllib.error.HTTPError) as exc:
            LOCAL_HTTP.open(request)
        assert exc.value.code == 403
        assert service_status(config) == identity
    finally:
        assert stop_service(config)
    assert not (tmp_path / 'service.json').exists()
    # A stopped process releases its lock and the same workspace can restart.
    replacement = start_service(config)
    assert replacement['instance_id'] != identity['instance_id']
    assert stop_service(config)


def test_foreign_port_is_never_stopped_or_replaced(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'app': 'another-app'}).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = Config(tmp_path, tmp_path / 'cache', port=server.server_port)
    try:
        for action in (service_status, start_service, stop_service):
            with pytest.raises(RuntimeError, match='其他应用'):
                action(config)
        assert LOCAL_HTTP.open(f'http://127.0.0.1:{server.server_port}').status == 200
        assert not (tmp_path / 'service.json').exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_existing_old_service_requires_restart_but_can_be_stopped(tmp_path, monkeypatch):
    import os
    import time
    from ai_exp_app import __version__
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).parents[1] / 'src'))
    config = Config(tmp_path, tmp_path / 'cache', port=free_port(), config_file=tmp_path / 'config.local.json')
    env = {**os.environ, 'AI_EXP_DATA_DIR': str(tmp_path), 'AI_EXP_PORT': str(config.port),
           'AI_EXP_CONFIG_FILE': str(config.config_file)}
    command = [sys.executable, '-c',
               "import ai_exp_app.app as app; app.__version__='0.3.0'; "
               'from ai_exp_app.desktop import main; main()']
    with (tmp_path / 'old-service.log').open('wb') as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=log)
    try:
        deadline = time.monotonic() + 60
        identity = None
        while time.monotonic() < deadline and identity is None:
            identity = service_status(config)
            time.sleep(.05)
        assert identity and identity['version'] == '0.3.0'
        with pytest.raises(RuntimeError, match='service stop --yes'):
            start_service(config)
        assert service_status(config)['instance_id'] == identity['instance_id']
        assert process.poll() is None
        assert stop_service(config)
        process.wait(timeout=10)
        replacement = start_service(config)
        assert replacement['version'] == __version__
        assert replacement['instance_id'] != identity['instance_id']
        assert stop_service(config)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_failed_start_only_cleans_up_its_owned_child(tmp_path, monkeypatch):
    import ai_exp_app.platform_runtime as runtime
    real_popen = subprocess.Popen
    children = []

    def capture(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(runtime.subprocess, 'Popen', capture)
    config = Config(tmp_path, tmp_path / 'cache', port=free_port())
    with pytest.raises(RuntimeError, match='启动超时'):
        start_service(config, command=[sys.executable, '-c', 'import time; time.sleep(60)'], timeout=.2)
    assert len(children) == 1 and children[0].poll() is not None


def test_shutdown_socket_disconnect_waits_for_private_identity_cleanup(tmp_path):
    import time
    from ai_exp_app import __version__
    state = {'stopping': False}
    identity_file = tmp_path / 'service.json'
    cleanup_finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if state['stopping']:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'app': 'ai-exp-app', 'instance_id': 'owned', 'version': __version__}).encode())

        def do_POST(self):
            assert self.headers['X-Desktop-Token'] == 'private-test-token'
            state['stopping'] = True
            # Deliberately drop the shutdown response and all subsequent health connections.
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()

            def cleanup():
                time.sleep(.25)
                identity_file.unlink()
                cleanup_finished.set()

            threading.Thread(target=cleanup, daemon=True).start()

        def log_message(self, *args):
            pass

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = Config(tmp_path, tmp_path / 'cache', port=server.server_port)
    identity_file.write_text(json.dumps({'url': f'http://127.0.0.1:{server.server_port}', 'instance_id': 'owned'}))
    (tmp_path / 'desktop-token').write_text('private-test-token')
    try:
        started = time.monotonic()
        assert stop_service(config, timeout=2)
        assert cleanup_finished.is_set() and time.monotonic() - started >= .25
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('exception', [ConnectionAbortedError(10053, 'aborted'), ConnectionResetError('reset')])
def test_health_handles_direct_windows_connection_errors(monkeypatch, exception):
    from ai_exp_app import platform_runtime

    def aborted(*args, **kwargs):
        raise exception

    monkeypatch.setattr(platform_runtime.LOCAL_HTTP, 'open', aborted)
    assert platform_runtime.health('http://127.0.0.1:8765') is None
