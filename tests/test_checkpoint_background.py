import threading
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_exp_app.db import Store
from ai_exp_app.history.api import create_router
from ai_exp_app.history import sync, worker
from ai_exp_remote import files


@pytest.mark.parametrize('remove', [False, True], ids=['rename-and-refresh', 'remove'])
def test_checkpoint_transfer_does_not_block_history_actions(tmp_path, monkeypatch, remove):
    origin = tmp_path / 'source'
    origin.mkdir()
    (origin / 'args.json').write_text('{"lr":0.001}')
    (origin / 'metrics.jsonl').write_text('{"tokens_seen":100}\n')
    (origin / 'latest.pt').write_bytes(b'checkpoint')
    cache = tmp_path / 'cache'
    store = Store(tmp_path / 'db.sqlite')
    monkeypatch.setattr(sync, 'rpc', lambda alias, operation, payload:
                        files.sync_files({**payload, 'path': str(origin)}))
    app = FastAPI()
    app.include_router(create_router(store, cache))
    client = TestClient(app)
    payload = {'source': {'kind': 'remote', 'path': '/runs/run'}, 'name': 'run'}
    response = client.post('/api/history/import', json=payload)
    assert response.status_code == 200, response.text
    record = response.json()
    identity = record['id']
    store.put('history', identity, {**store.get('history', identity), 'status': 'completed'})
    record = client.post('/api/history/import', json=payload).json()
    assert record['sync_status'] == 'synced'
    assert record['checkpoint_sync_status'] == 'pending'
    preview = client.post('/api/history/' + identity + '/delete-preview', json={'scope': 'remote'})
    assert preview.status_code == 409
    assert 'checkpoint' in preview.json()['detail']
    old_cache = Path(record['cache_dir'])
    assert not (old_cache / 'latest.pt').exists()
    started, finish = threading.Event(), threading.Event()

    def slow_download(source, entry, target):
        started.set()
        assert finish.wait(5), 'History action blocked behind the checkpoint transfer'
        target.write_bytes((origin / 'latest.pt').read_bytes())

    monkeypatch.setattr(worker, 'download_checkpoint', slow_download)
    thread = threading.Thread(target=worker.sync_checkpoints, args=(store, cache))
    thread.start()
    try:
        assert started.wait(2)
        if remove:
            assert client.delete('/api/history/' + identity).status_code == 200
        else:
            assert client.patch('/api/history/' + identity, json={'name': 'renamed'}).status_code == 200
            (origin / 'metrics.jsonl').write_text('{"tokens_seen":5000000000}\n')
            updated = client.post('/api/history/import', json=payload).json()
            assert updated['sync_status'] == 'synced'
            assert (Path(updated['cache_dir']) / 'metrics.jsonl').read_text() == '{"tokens_seen":5000000000}\n'
    finally:
        finish.set()
        thread.join(timeout=2)
    assert not thread.is_alive()
    result = store.get('history', identity)
    if remove:
        assert 'latest.pt' not in result['files']
        assert not (old_cache / 'latest.pt').exists()
    else:
        assert not old_cache.exists()
        assert (Path(result['cache_dir']) / 'latest.pt').read_bytes() == b'checkpoint'
        assert result['checkpoint_sync_status'] == 'synced'
        refreshed = client.post('/api/history/import', json=payload).json()
        assert 'latest.pt' in refreshed['files']
        assert refreshed['checkpoint_sync_status'] == 'synced'


def test_checkpoint_failure_preserves_synced_metrics_and_retries(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    cache.mkdir()
    store = Store(tmp_path / 'db.sqlite')
    store.put('history', 'run', {'id': 'run', 'status': 'completed', 'sync_status': 'synced',
        'source': {'kind': 'remote', 'path': '/runs/run'}, 'cache_dir': str(cache / 'run'),
        'files': ['metrics.jsonl'], 'checkpoint_sync_status': 'pending',
        'manifest': [{'name': 'latest.pt', 'size': 10, 'mtime_ns': 1}]})

    def interrupted(*args):
        raise OSError('connection interrupted')

    monkeypatch.setattr(worker, 'download_checkpoint', interrupted)
    worker.sync_checkpoints(store, cache)
    result = store.get('history', 'run')
    assert result['sync_status'] == 'synced'
    assert result['files'] == ['metrics.jsonl']
    assert result['checkpoint_sync_status'] == 'pending'
    assert result['checkpoint_sync_error'] == 'connection interrupted'
    assert result['checkpoint_retry_at'] > 0
    assert not list(cache.glob('.checkpoint-*'))


def test_app_exit_cancels_checkpoint_process_and_cleans_partial_file(tmp_path, monkeypatch):
    from ai_exp_app.transport import ssh
    monkeypatch.setattr(ssh, 'build_agent_argv', lambda *args: [
        sys.executable, '-c', 'import threading; threading.Event().wait(600)'])
    started, stop = threading.Event(), threading.Event()
    processes, errors = [], []
    popen = subprocess.Popen

    def capture_process(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr(sync.subprocess, 'Popen', capture_process)

    def transfer():
        try:
            sync.download_checkpoint({'path': '/runs/run'}, {'size': 10, 'mtime_ns': 1},
                                     tmp_path / 'latest.pt', stop_event=stop)
        except OSError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=transfer)
    thread.start()
    try:
        assert started.wait(2)
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert errors and '已取消' in errors[0]
    assert processes[0].poll() is not None
    assert not list(tmp_path.iterdir())
