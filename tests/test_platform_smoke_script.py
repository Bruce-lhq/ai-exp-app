"""Failed package verification must retain evidence and its original error."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('primary_failure', [True, False])
def test_smoke_reports_cleanup_error_without_hiding_primary_failure(tmp_path, monkeypatch, primary_failure):
    source = Path(__file__).parents[1] / 'scripts' / 'smoke_platform.py'
    spec = importlib.util.spec_from_file_location('platform_smoke_script', source)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    # Exercise report handling on any CI OS without pretending to own a real Windows process.
    monkeypatch.setattr(smoke, 'os', SimpleNamespace(name='posix', environ=os.environ))
    report = tmp_path / 'report.json'
    monkeypatch.setattr(sys, 'argv', ['smoke_platform.py', '--executable', str(tmp_path / 'test-cli'), '--report', str(report)])
    operations = []

    def run(command, **kwargs):
        args = command[1:]
        operations.append(args)
        value = ''
        if args[:2] == ['service', 'status']:
            value = {'running': False}
        elif args[:2] == ['service', 'start']:
            value = {'instance_id': 'owned', 'url': 'http://127.0.0.1:' + kwargs['env']['AI_EXP_PORT']}
        elif args[:2] == ['service', 'stop']:
            return subprocess.CompletedProcess(command, 3, '', 'secondary cleanup failure')
        elif args[:2] == ['config', 'show']:
            if primary_failure:
                return subprocess.CompletedProcess(command, 4, '', 'primary verification failure')
            value = {'configured': False}
        elif args[:2] == ['history', 'import']:
            value = {'id': 'example'}
        elif args[:2] == ['history', 'list']:
            value = [{'id': 'example'}]
        elif args[0] == 'table':
            value = 'Example run | 0.95'
        elif args[0] == 'plot':
            destination = Path(args[args.index('--output') + 1])
            destination.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\0' * 8 + struct.pack('>II', 640, 440))
        stdout = json.dumps(value) if isinstance(value, (dict, list)) else value
        return subprocess.CompletedProcess(command, 0, stdout, '')

    monkeypatch.setattr(smoke.subprocess, 'run', run)
    expected = 'primary verification failure' if primary_failure else 'secondary cleanup failure'
    with pytest.raises(RuntimeError, match=expected):
        smoke.main()
    saved = json.loads(report.read_text(encoding='utf-8'))
    assert 'secondary cleanup failure' in saved['cleanup_error']
    if primary_failure:
        assert 'primary verification failure' in saved['error']
    else:
        assert saved['packaged_cli'] is True
    assert any(operation[:2] == ['service', 'stop'] for operation in operations)
