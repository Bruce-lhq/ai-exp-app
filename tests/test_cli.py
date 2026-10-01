import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

import pytest

from ai_exp_app import cli
from ai_exp_app.client import Client

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def environment(tmp_path, port):
    return {**os.environ, 'AI_EXP_DATA_DIR': str(tmp_path / 'workspace'),
            'AI_EXP_CONFIG_FILE': str(tmp_path / 'workspace/config.local.json'),
            'AI_EXP_CACHE_ROOT': str(tmp_path / 'workspace/cache'), 'AI_EXP_PORT': str(port),
            'PYTHONPATH': str(ROOT / 'src') + os.pathsep + str(ROOT / 'remote')}


def invoke(env, *args, url=None):
    prefix = ['--url', url] if url else []
    budget = 120 if args and args[0] == 'plot' else 60
    try:
        return subprocess.run([sys.executable, '-m', 'ai_exp_app.cli', *prefix, *args],
                              env=env, cwd=ROOT, input='', text=True, capture_output=True, timeout=budget)
    except subprocess.TimeoutExpired as exc:
        log = Path(env['AI_EXP_DATA_DIR']).parent / 'server.log'
        details = log.read_text(encoding='utf-8', errors='replace') if log.exists() else '(no server log)'
        pytest.fail(f'CLI {args} exceeded {budget}s: {exc}\nServer log:\n{details}')


@pytest.fixture
def local_service(tmp_path):
    port = free_port(); env = environment(tmp_path, port)
    url = 'http://127.0.0.1:' + str(port)
    with (tmp_path / 'server.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'ai_exp_app.app:create_app',
                                    '--factory', '--host', '127.0.0.1', '--port', str(port)],
                                   env=env, cwd=ROOT, stdout=log, stderr=log)
        deadline = time.monotonic() + 60
        try:
            while time.monotonic() < deadline:
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url + '/api/health', timeout=.5):
                        break
                except OSError:
                    if process.poll() is not None: pytest.fail((tmp_path / 'server.log').read_text())
                    time.sleep(.05)
            else:
                pytest.fail('Isolated test service did not start within 60s\n' + (tmp_path / 'server.log').read_text(encoding='utf-8', errors='replace'))
            yield env, url
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # Only the fixture's own Popen child is killed; no shared/user service is touched.
                process.kill()
                process.wait(timeout=5)


def test_cli_import_sync_table_and_export_use_shared_cache(local_service, tmp_path):
    env, url = local_service
    source = tmp_path / 'original-run'; source.mkdir()
    (source / 'args.json').write_text('{"learning_rate": 0.001}')
    (source / 'metrics.jsonl').write_text('{"step":1,"accuracy":0.75}\n')
    result = invoke(env, 'history', 'import', '--path', str(source), '--name', 'Classifier', url=url)
    assert result.returncode == 0, result.stderr
    history = json.loads(result.stdout); identity = history['id']
    result = invoke(env, 'history', 'list', '--json', url=url)
    assert json.loads(result.stdout)[0]['id'] == identity
    request = tmp_path / 'table.json'
    request.write_text(json.dumps({'columns': [
        {'id':'name', 'kind':'name', 'title':'Experiment'},
        {'id':'accuracy', 'kind':'metric', 'field':'accuracy', 'aggregate':'final', 'title':'Accuracy'}]}))
    table = invoke(env, 'table', identity, '--request-file', str(request), url=url)
    assert table.returncode == 0 and 'Classifier' in table.stdout and '0.75' in table.stdout
    (source / 'metrics.jsonl').write_text('{"step":1,"accuracy":0.75}\n{"step":2,"accuracy":0.95}\n')
    assert invoke(env, 'history', 'sync', url=url).returncode == 0
    assert '0.95' in invoke(env, 'table', identity, '--request-file', str(request), url=url).stdout
    archive = tmp_path / 'experiment.zip'
    exported = invoke(env, 'history', 'export', identity, '--output', str(archive), url=url)
    assert exported.returncode == 0, exported.stderr
    with zipfile.ZipFile(archive) as saved:
        assert json.loads(saved.read('Classifier/args.json')) == {'learning_rate': .001}
    assert (source / 'args.json').read_text() == '{"learning_rate": 0.001}'
    assert invoke(env, 'history', 'export', identity, '--output', str(archive), url=url).returncode == 2


def test_cli_errors_confirmation_and_safe_delete(local_service, tmp_path):
    env, url = local_service
    original = tmp_path / 'original'; original.mkdir()
    (original / 'args.json').write_text('{}')
    imported = json.loads(invoke(env, 'history', 'import', '--path', str(original), url=url).stdout)
    refused = invoke(env, 'history', 'delete', imported['id'], url=url)
    assert refused.returncode == 5 and '--yes' in refused.stderr
    assert Path(imported['cache_dir']).exists() and original.exists()
    deleted = invoke(env, 'history', 'delete', imported['id'], '--yes', url=url)
    assert deleted.returncode == 0, deleted.stderr
    assert not Path(imported['cache_dir']).exists() and original.exists()
    missing = invoke(env, 'run', 'show', 'missing', url=url)
    assert missing.returncode == 4 and 'API 404' in missing.stderr
    assert invoke(env, 'plot', 'missing', url=url).returncode == 2
    assert invoke(env, 'api', 'DELETE', '/api/projects/missing', url=url).returncode == 5
    remote = invoke(env, 'history', 'list', url='https://example.com')
    assert remote.returncode == 2


def test_cli_strict_resume_and_optimistic_queue_order_use_existing_api(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('AI_EXP_DATA_DIR', str(tmp_path / 'workspace'))
    calls = []
    class Fake:
        def request(self, method, path, body=None):
            calls.append((method, path, body))
            if path.endswith('/resume-editor'):
                return {'project_id':'p', 'training':{'epochs':3}, 'runtime':{'gpu_count':2},
                        'resume':{'ticket':'verified', 'path':'/runs/checkpoint.bin'}, 'display_name':'Strict resume'}
            if path == '/api/queue' and method == 'GET': return {'revision':9,'runs':[]}
            return {'ok':True}
        def post(self, path, body=None): return self.request('POST', path, body)
        def get(self, path): return self.request('GET', path)
    monkeypatch.setattr(cli, 'client_for', lambda *args: Fake())
    assert cli.main(['run', 'resume', 'h', '--queue']) == 0
    body = calls[-1][2]
    assert body['resume_ticket'] == 'verified' and body['mode'] == 'queue'
    assert body['parameters']['runtime']['gpu_count'] == 2
    assert cli.main(['queue', 'order', 'b', 'a']) == 0
    assert calls[-1] == ('PUT', '/api/queue/order', {'run_ids':['b','a'], 'revision':9})
    before = len(calls)
    assert cli.main(['run', 'stop', 'live']) == 5
    assert len(calls) == before
    assert cli.main(['run', 'stop', 'live', '--yes']) == 0
    assert calls[-1] == ('POST', '/api/runs/live/stop', {'confirmed':True,'pause_queue':False})


def test_cli_and_desktop_reuse_one_isolated_service_and_can_restart(tmp_path):
    env = environment(tmp_path, free_port())
    try:
        first = invoke(env, 'service', 'start')
        assert first.returncode == 0, first.stderr
        identity = json.loads(first.stdout)
        second = json.loads(invoke(env, 'service', 'start').stdout)
        assert second['instance_id'] == identity['instance_id']
        assert invoke(env, 'history', 'list', '--json').returncode == 0
        assert invoke(env, 'service', 'stop').returncode == 5
        stopped = invoke(env, 'service', 'stop', '--yes')
        assert stopped.returncode == 0 and json.loads(stopped.stdout)['stopped']
        assert json.loads(invoke(env, 'service', 'status').stdout) == {'running':False}
        restarted = json.loads(invoke(env, 'service', 'start').stdout)
        assert restarted['instance_id'] != identity['instance_id']
    finally:
        invoke(env, 'service', 'stop', '--yes')


def test_client_ignores_system_proxies_for_local_service(local_service, monkeypatch):
    _, url = local_service
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:1')
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('no_proxy', '')
    assert Client(url).get('/api/health')['app'] == 'ai-exp-app'


def test_cli_exports_png_offline_and_preserves_missing_metric_warning(local_service, tmp_path):
    import struct
    env, url = local_service
    identities = []
    for name, record in (("loss-run", {"step":1,"loss":3}), ("accuracy-run", {"step":1,"accuracy":.8})):
        source = tmp_path / name; source.mkdir()
        (source / 'args.json').write_text('{}')
        (source / 'metrics.jsonl').write_text(json.dumps(record)+'\n')
        result = invoke(env, 'history', 'import', '--path', str(source), url=url)
        identities.append(json.loads(result.stdout)['id'])
    request = tmp_path / 'plot-style.json'
    request.write_text(json.dumps({'settings': {'width':640, 'height':440, 'pixelRatio':1},
        'appearance': {identities[0]: {'name':'My loss', 'color':'#123456'}}}))
    destination = tmp_path / 'curve.png'
    result = invoke(env, 'plot', *identities, '--metric', 'loss', '--axis', 'step',
                    '--request-file', str(request), '--output', str(destination), url=url)
    assert result.returncode == 0, result.stderr
    assert 'Warning:' in result.stderr and 'loss' in result.stderr
    raw = destination.read_bytes()
    assert raw[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II', raw[16:24]) == (640,440)


def test_cli_redirected_unicode_input_and_output_are_utf8(local_service, tmp_path):
    env,url=local_service
    env={**env,'PYTHONIOENCODING':'cp1252'}
    body=json.dumps({'local_import_root':'C:/用户/实验/'},ensure_ascii=False).encode('utf-8')
    prefix=[sys.executable,'-m','ai_exp_app.cli','--url',url]
    result=subprocess.run([*prefix,'config','set','--file','-','--json'],input=body,
                          env=env,cwd=ROOT,capture_output=True,timeout=60)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['local_settings']['local_import_root']=='C:/用户/实验/'
    result=subprocess.run([*prefix,'config','show','--json'],env=env,cwd=ROOT,
                          capture_output=True,timeout=60)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['local_settings']['local_import_root']=='C:/用户/实验/'
