"""Run the actual NSIS install/upgrade/uninstall lifecycle in a private Windows workspace."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OwnedService:
    """Hold the verified process handle, so cleanup never follows a reused PID."""
    def __init__(self, identity, executable):
        self.identity = identity
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.OpenProcess(0x100000 | 0x1000 | 1, False, identity['pid'])
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        size = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not self.kernel.QueryFullProcessImageNameW(self.handle, 0, image, ctypes.byref(size)) or Path(image.value).resolve() != executable.resolve():
            self.close()
            raise RuntimeError('Workspace PID does not belong to the installed test executable')

    def exited(self, timeout=0):
        result = self.kernel.WaitForSingleObject(self.handle, int(timeout * 1000))
        if result not in (0, 258):
            raise RuntimeError('Could not wait for the owned service process')
        return result == 0

    def cleanup(self):
        if not self.exited():
            self.kernel.TerminateProcess(self.handle, 1)
            if not self.exited(5):
                raise RuntimeError('Owned test service did not exit during cleanup')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def marker_hashes(paths):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def nsis_command(executable, install, *, uninstall=False):
    # NSIS consumes the final directory option verbatim, without quotes even for spaces.
    return subprocess.list2cmdline([str(executable), '/S']) + (' _?=' if uninstall else ' /D=') + str(install)


def verify_identity(workspace, url):
    identity = json.loads((workspace / 'service.json').read_text(encoding='utf-8'))
    if identity.get('url') != url:
        raise RuntimeError('Service belongs to a different test endpoint')
    with LOCAL_HTTP.open(url + '/api/health', timeout=3) as response:
        health = json.load(response)
    if health.get('app') != 'ai-exp-app' or health.get('instance_id') != identity.get('instance_id'):
        raise RuntimeError('Service identity does not match the private workspace')
    return identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    report = Path(args.report).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    results = {'ok': False, 'platform': platform.platform(), 'human_acceptance': False, 'checks': []}
    root = Path(tempfile.mkdtemp(prefix='ai-experiment-installer-'))
    workspace, cache, install = root / 'workspace', root / 'cache', root / 'installed app'
    workspace.mkdir(); cache.mkdir()
    config = workspace / 'config.local.json'
    config.write_text('{"ssh_alias":"installer-smoke","remote_runs_root":""}\n', encoding='utf-8')
    cache_marker = cache / 'cached-experiment-marker.txt'
    cache_marker.write_text('preserve cached experiments\n', encoding='utf-8')
    markers = [config, cache_marker]
    original = marker_hashes(markers)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'AI_EXP_DATA_DIR': str(workspace), 'AI_EXP_CACHE_ROOT': str(cache),
           'AI_EXP_CONFIG_FILE': str(config), 'AI_EXP_PORT': str(port), 'PYTHONUTF8': '1'}
    for key in ('PYTHONPATH', 'AI_EXP_WEB_ROOT'):
        env.pop(key, None)
    executable = install / 'ai-experiment.exe'
    services = []
    logs = []

    def call(label, command, timeout=90, json_result=False):
        argv = command if isinstance(command, str) else [str(value) for value in command]
        with subprocess.Popen(argv, cwd=root, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace') as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # This exact Popen belongs to the smoke test; never taskkill other processes.
                process.kill()
                stdout, stderr = process.communicate(timeout=10)
                logs.append({'step': label, 'timeout': True, 'stdout': stdout, 'stderr': stderr})
                raise RuntimeError(label + ' timed out')
            logs.append({'step': label, 'exit_code': process.returncode, 'stdout': stdout, 'stderr': stderr})
            if process.returncode:
                raise RuntimeError(f'{label} failed with exit code {process.returncode}: {stderr}')
            return json.loads(stdout) if json_result else stdout

    def start():
        identity = call('start installed backend', [executable, 'service', 'start', '--json'], json_result=True)
        verified = verify_identity(workspace, url)
        if identity['instance_id'] != verified['instance_id']:
            raise RuntimeError('CLI returned a different backend instance')
        service = OwnedService(verified, executable)
        services.append(service)
        return service

    def stopped(service):
        if not service.exited(15) or (workspace / 'service.json').exists():
            raise RuntimeError('Installer left its workspace backend running')
        try:
            LOCAL_HTTP.open(url + '/api/health', timeout=2).close()
        except urllib.error.URLError:
            return
        raise RuntimeError('Test endpoint still responds after installer stopped the backend')

    try:
        if os.name != 'nt':
            raise RuntimeError('The real NSIS smoke test requires Windows; it is not skipped')
        installer = Path(args.installer).resolve()
        call('silent first install', nsis_command(installer, install), timeout=240)
        if not executable.is_file() or not (install / 'Uninstall.exe').is_file():
            raise RuntimeError('Silent installer did not create the application and uninstaller')
        results['checks'].append('real NSIS silent install into a dedicated directory')
        service = start()
        native = root / 'native.json'
        try:
            call('installed native renderer', [executable, 'desktop', '--smoke-test', native], timeout=90)
        finally:
            if native.exists():
                results['native_window'] = json.loads(native.read_text(encoding='utf-8'))
        rendered = results.get('native_window', {})
        if not rendered.get('ok') or rendered.get('renderer') != 'edgechromium' or rendered.get('children', 0) < 1:
            raise RuntimeError('Installed WebView2 did not render the actual application')
        if service.exited() or verify_identity(workspace, url)['instance_id'] != service.identity['instance_id']:
            raise RuntimeError('Closing the native window stopped the shared backend')
        results['checks'].append('installed WebView2 renders bundled UI and preserves shared backend')
        call('silent upgrade with active backend', nsis_command(installer, install), timeout=240)
        stopped(service)
        if marker_hashes(markers) != original:
            raise RuntimeError('Upgrade modified workspace configuration or cached experiment marker')
        results['checks'].append('upgrade safely stops the verified backend and preserves data')
        service = start()
        # NSIS runs synchronously without creating a detached temporary uninstaller copy.
        call('silent uninstall with active backend', nsis_command(install / 'Uninstall.exe', install, uninstall=True), timeout=120)
        stopped(service)
        if executable.exists() or (install / '_internal').exists():
            raise RuntimeError('Uninstall left application binaries behind')
        if marker_hashes(markers) != original:
            raise RuntimeError('Uninstall modified workspace configuration or cached experiment marker')
        results['checks'].append('uninstall stops owned backend, removes binaries and retains config/cache')
        results['preserved_marker_hashes'] = original
        results['ok'] = True
    except Exception as exc:
        results['error'] = str(exc)
        raise
    finally:
        cleanup_errors = []
        # Capture any backend started before a failed CLI response, after verifying its identity and binary.
        if os.name == 'nt' and (workspace / 'service.json').exists():
            try:
                identity = verify_identity(workspace, url)
                if not any(item.identity['instance_id'] == identity['instance_id'] for item in services):
                    services.append(OwnedService(identity, executable))
                token = (workspace / 'desktop-token').read_text(encoding='utf-8').strip()
                request = urllib.request.Request(url + '/api/desktop/shutdown', data=b'{}',
                                                 headers={'X-Desktop-Token': token, 'Content-Type': 'application/json'})
                with LOCAL_HTTP.open(request, timeout=3) as response:
                    json.load(response)
                time.sleep(.5)
            except Exception as exc:
                cleanup_errors.append(str(exc))
        for service in services:
            try:
                service.cleanup()
            except Exception as exc:
                cleanup_errors.append(str(exc))
            finally:
                service.close()
        if cleanup_errors:
            results['cleanup_errors'] = cleanup_errors
        backend_log = workspace / 'service.log'
        if backend_log.exists():
            shutil.copyfile(backend_log, report.with_suffix('.service.log'))
        report.with_suffix('.commands.json').write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding='utf-8')
        report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        shutil.rmtree(root, ignore_errors=True)
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
