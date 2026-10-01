import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer_smoke', ROOT / 'scripts/smoke_windows_installer.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_nsis_last_directory_option_is_unquoted_even_with_spaces():
    assert smoke.nsis_command(r'C:\Build Files\Setup.exe', r'C:\Test app') == '"C:\\Build Files\\Setup.exe" /S /D=C:\\Test app'
    assert smoke.nsis_command(r'C:\Test app\Uninstall.exe', r'C:\Test app', uninstall=True) == '"C:\\Test app\\Uninstall.exe" /S _?=C:\\Test app'


def test_installer_smoke_rejects_foreign_backend_identity(tmp_path, monkeypatch):
    (tmp_path / 'service.json').write_text(json.dumps({'url': 'http://127.0.0.1:9191', 'instance_id': 'own'}), encoding='utf-8')
    monkeypatch.setattr(smoke.LOCAL_HTTP, 'open', lambda *a, **k: io.BytesIO(b'{"app":"ai-exp-app","instance_id":"other"}'))
    with pytest.raises(RuntimeError, match='private workspace'):
        smoke.verify_identity(tmp_path, 'http://127.0.0.1:9191')


def test_installer_cleanup_never_captures_another_executable(tmp_path, monkeypatch):
    kernel = SimpleNamespace(OpenProcess=Mock(return_value=123), QueryFullProcessImageNameW=Mock(),
                             WaitForSingleObject=Mock(), TerminateProcess=Mock(), CloseHandle=Mock())
    def image(handle, flags, buffer, size):
        buffer.value = str(tmp_path / 'unrelated.exe')
        return True
    kernel.QueryFullProcessImageNameW.side_effect = image
    monkeypatch.setattr(smoke.ctypes, 'WinDLL', lambda *a, **k: kernel, raising=False)
    with pytest.raises(RuntimeError, match='installed test executable'):
        smoke.OwnedService({'pid': 123}, tmp_path / 'ai-experiment.exe')
    kernel.CloseHandle.assert_called_once_with(123)
    kernel.TerminateProcess.assert_not_called()


def test_installer_smoke_records_failure_without_skipping_or_launching_on_other_os(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, 'os', SimpleNamespace(name='posix', environ={}))
    monkeypatch.setattr(smoke.platform, 'platform', lambda: 'test OS')
    monkeypatch.setattr(smoke.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not execute installer on another OS'))
    report = tmp_path / 'verification.json'
    monkeypatch.setattr('sys.argv', ['smoke', '--installer', str(tmp_path / 'Setup.exe'), '--report', str(report)])
    with pytest.raises(RuntimeError, match='not skipped'):
        smoke.main()
    result = json.loads(report.read_text(encoding='utf-8'))
    assert result['ok'] is False
    assert 'requires Windows' in result['error']
    assert result['checks'] == []


def test_preservation_check_detects_changes_even_for_unicode_markers(tmp_path):
    marker = tmp_path / 'config.local.json'
    marker.write_text('{"label":"实验"}', encoding='utf-8')
    before = smoke.marker_hashes([marker])
    marker.write_text('{"label":"changed"}', encoding='utf-8')
    assert smoke.marker_hashes([marker]) != before
