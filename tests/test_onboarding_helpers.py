import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import shutil
import threading

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/experiment-workbench-setup/scripts'


def helper(name):
    spec = importlib.util.spec_from_file_location('onboarding_' + name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_probe_never_executes_unconventional_entrypoint(tmp_path):
    sentinel = tmp_path / 'executed'
    (tmp_path / 'optimize_image.py').write_text(
        f'from pathlib import Path\nPath({str(sentinel)!r}).touch()\n'
        'import argparse\np = argparse.ArgumentParser()\n'
        'p.add_argument("--image-width", type=int, default=16)\n'
        'p.add_argument("--output-dir")\n'
    )
    result = helper('probe').inspect_source(tmp_path)
    assert not sentinel.exists()
    entry = result['entrypoints'][0]
    assert entry['path'] == 'optimize_image.py'
    assert entry['arguments'][0]['literal_default'] == 16


def test_explicit_nested_entrypoint_is_discovered_without_import(tmp_path):
    entrypoint = tmp_path / 'packages' / 'image_task' / 'bin' / 'fit_model.py'
    entrypoint.parent.mkdir(parents=True)
    sentinel = tmp_path / 'unexpected-execution'
    entrypoint.write_text(f'from pathlib import Path\nPath({str(sentinel)!r}).touch()\n'
                          'import argparse\np=argparse.ArgumentParser()\np.add_argument("--epochs", default=3, type=int)\n')
    module = helper('probe')
    assert module.inspect_source(tmp_path)['entrypoints'] == []
    result = module.inspect_source(tmp_path, ['packages/image_task/bin/fit_model.py'])
    assert result['entrypoints'][0]['arguments'][0]['literal_default'] == 3
    assert not sentinel.exists()
    with pytest.raises(ValueError):
        module.inspect_source(tmp_path, ['../../outside.py'])


def test_ssh_probe_keeps_host_verification_and_quotes_executable(monkeypatch):
    captured = {}

    def run(argv, **kwargs):
        captured.update(argv=argv, kwargs=kwargs)
        return subprocess.CompletedProcess(argv, 0, json.dumps({'read_only': True}), '')

    module = helper('probe')
    monkeypatch.setattr(module.subprocess, 'run', run)
    assert module.probe_ssh('test-gpu', '/your_exp/projects', '/path with spaces/python')['read_only']
    assert 'StrictHostKeyChecking=yes' in captured['argv']
    assert captured['argv'][-1] == "'/path with spaces/python' -"
    assert captured['kwargs']['input'].startswith('import json')
    with pytest.raises(ValueError):
        module.probe_ssh('-oProxyCommand=unexpected')


def test_local_api_helper_obtains_session_and_sends_origin():
    observed = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Set-Cookie', 'ai_exp_session=test-session; Path=/; HttpOnly')
            self.end_headers()
            self.wfile.write(b'home')

        def do_POST(self):
            observed.update(cookie=self.headers.get('Cookie'), origin=self.headers.get('Origin'),
                            body=json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        assert helper('api').call(base, 'POST', '/api/projects', {'name': 'Image experiment'}) == {'ok': True}
        assert observed == {'cookie': 'ai_exp_session=test-session', 'origin': base, 'body': {'name': 'Image experiment'}}
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.mark.parametrize('base,path', [
    ('https://127.0.0.1:8765', '/api/projects'),
    ('http://remote.example', '/api/projects'),
    ('http://127.0.0.1:8765', '//remote.example/api/projects'),
    ('http://127.0.0.1:8765', '/api/../private'),
])
def test_api_helper_rejects_nonlocal_requests(base, path):
    with pytest.raises(ValueError):
        helper('api').call(base, 'GET', path)


def test_csv_conversion_preserves_source_and_missing_metrics(tmp_path):
    source = tmp_path / 'measurements.csv'
    content = 'iteration,error,rate\n1,0.5,1200\n2,,NaN\n'
    source.write_text(content)
    destination = tmp_path / 'canonical' / 'metrics.jsonl'
    module = helper('normalize_metrics')
    result = module.normalize(source, destination, {'step': 'iteration', 'loss': 'error', 'tok_per_s': 'rate'})
    assert source.read_text() == content
    assert [json.loads(line) for line in destination.read_text().splitlines()] == [
        {'step': 1, 'loss': 0.5, 'tok_per_s': 1200}, {'step': 2}]
    assert result['missing_or_invalid_fields'] == ['error', 'rate']
    with pytest.raises(ValueError):
        module.normalize(source, destination, {'step': 'iteration'})


def test_nested_jsonl_conversion_is_atomic_on_bad_record(tmp_path):
    source = tmp_path / 'observations.jsonl'
    source.write_text('{"iteration":1,"metrics":{"accuracy":0.8}}\n')
    destination = tmp_path / 'metrics.jsonl'
    module = helper('normalize_metrics')
    module.normalize(source, destination, {'step': 'iteration', 'accuracy': 'metrics.accuracy'})
    assert json.loads(destination.read_text()) == {'step': 1, 'accuracy': 0.8}
    source.write_text('{broken-json\n')
    with pytest.raises(ValueError):
        module.normalize(source, destination, {'step': 'iteration'}, overwrite=True)
    assert json.loads(destination.read_text()) == {'step': 1, 'accuracy': 0.8}


def test_csv_literal_dotted_header_is_not_treated_as_nested(tmp_path):
    source = tmp_path / 'observations.csv'
    source.write_text('iteration,train.loss\n1,0.8\n')
    destination = tmp_path / 'metrics.jsonl'
    helper('normalize_metrics').normalize(source, destination, {'step': 'iteration', 'loss': 'train.loss'})
    assert json.loads(destination.read_text()) == {'step': 1, 'loss': 0.8}


def test_profile_validator_can_be_used_from_copied_skill(tmp_path):
    destination = tmp_path / 'copied' / 'scripts'
    destination.mkdir(parents=True)
    shutil.copy2(SCRIPTS / 'check_profile.py', destination)
    profile = tmp_path / 'workbench.project.json'
    profile.write_text(json.dumps({'version': 1, 'command': ['custom-binary'], 'parameters': []}))
    result = subprocess.run([sys.executable, str(destination / 'check_profile.py'), str(profile), '--repo', str(SCRIPTS.parents[2])], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['command'] == ['custom-binary']
    failure = subprocess.run([sys.executable, str(destination / 'check_profile.py'), str(profile), '--repo', str(tmp_path)], cwd=tmp_path, capture_output=True, text=True)
    assert failure.returncode != 0
    assert '--repo' in failure.stderr
