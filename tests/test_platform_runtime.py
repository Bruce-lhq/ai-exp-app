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
