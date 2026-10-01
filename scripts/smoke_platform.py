"""Exercise a packaged CLI/service/cache without SSH or training, optionally a real native window."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import struct
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--mac-app', help='Built macOS app executable for a real WebKit smoke test')
    args = parser.parse_args()
    executable = Path(args.executable).resolve()
    with tempfile.TemporaryDirectory(prefix='ai-experiment-smoke-') as folder:
        root = Path(folder)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = {**os.environ, 'AI_EXP_DATA_DIR': str(root / 'workspace'), 'AI_EXP_PORT': str(port),
               'AI_EXP_CACHE_ROOT': str(root / 'cache'), 'AI_EXP_CONFIG_FILE': str(root / 'config.local.json')}
        # A packaged test must succeed without importing the repository or an external web build.
        for name in ('PYTHONPATH', 'AI_EXP_WEB_ROOT'):
            env.pop(name, None)
        results = {'platform': platform.platform(), 'architecture': platform.machine(), 'packaged_cli': False,
                   'native_window': 'not tested', 'human_acceptance': False, 'checks': []}

        def call(*arguments, json_result=False):
            command = [str(executable), *arguments]
            completed = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=75)
            if completed.returncode:
                raise RuntimeError(f'{arguments[0]} failed ({completed.returncode}): {completed.stderr}\n{completed.stdout}')
            return json.loads(completed.stdout) if json_result else completed.stdout

        service = None
        try:
            call('--help')
            assert call('service', 'status', '--json', json_result=True) == {'running': False}
            service = call('service', 'start', '--json', json_result=True)
            assert service['instance_id'] and service['url'].endswith(':' + str(port))
            assert call('service', 'start', '--json', json_result=True)['instance_id'] == service['instance_id']
            results['checks'].append('start/reuse own localhost service')
            assert call('config', 'show', '--json', json_result=True)['configured'] is False
            results['checks'].append('neutral private workspace')
            source = root / 'source-run'
            source.mkdir()
            (source / 'args.json').write_text('{"learning_rate":0.001}', encoding='utf-8')
            metrics = source / 'metrics.jsonl'
            metrics.write_text('{"step":1,"accuracy":0.75}\n{"step":2,"accuracy":0.95}\n', encoding='utf-8')
            before = hashlib.sha256(metrics.read_bytes()).hexdigest()
            history = call('history', 'import', '--path', str(source), '--name', 'Example run', '--json', json_result=True)
            identity = history['id']
            assert call('history', 'list', '--json', json_result=True)[0]['id'] == identity
            request = root / 'table.json'
            request.write_text(json.dumps({'columns': [
                {'id': 'name', 'kind': 'name', 'title': 'Experiment'},
                {'id': 'accuracy', 'kind': 'metric', 'field': 'accuracy', 'aggregate': 'final', 'title': 'Accuracy'}]}))
            table = call('table', identity, '--request-file', str(request))
            assert 'Example run' in table and '0.95' in table
            results['checks'].append('local history and cached Markdown table')
            png = root / 'curve.png'
            call('plot', identity, '--metric', 'accuracy', '--axis', 'step', '--output', str(png))
            assert png.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
            results['png_size'] = struct.unpack('>II', png.read_bytes()[16:24])
            assert all(number > 100 for number in results['png_size'])
            assert hashlib.sha256(metrics.read_bytes()).hexdigest() == before
            results['checks'].append('headless PNG export preserves source metrics')
            if args.desktop or args.mac_app:
                native = root / 'native.json'
                if args.mac_app:
                    native_env = {**env, 'AI_EXP_NATIVE_SMOKE_PATH': str(native)}
                    completed = subprocess.run([str(Path(args.mac_app).resolve())], cwd=root, env=native_env, capture_output=True, text=True, timeout=75)
                    if completed.returncode:
                        raise RuntimeError('Mac native window failed: ' + completed.stderr)
                else:
                    call('desktop', '--smoke-test', str(native))
                result = json.loads(native.read_text())
                assert result.get('ok') and result.get('children', 0) > 0, result
                results['native_window'] = result
                results['checks'].append('real native renderer loads bundled React UI')
            results['packaged_cli'] = True
        except Exception as exc:
            results['error'] = str(exc)
            raise
        finally:
            if service is not None:
                call('service', 'stop', '--yes', '--json')
                assert call('service', 'status', '--json', json_result=True) == {'running': False}
                results['checks'].append('authenticated service stop')
            report = Path(args.report).resolve()
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
