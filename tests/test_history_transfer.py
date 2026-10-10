import base64
import gzip
import json
import pytest
from ai_exp_app.history import sync
from ai_exp_app.transport.ssh import RemoteError
from ai_exp_remote import files


@pytest.mark.parametrize('newline', [b'\n', b'\r\n'], ids=['lf', 'crlf'])
def test_compressed_snapshot_incremental_refresh_and_rewrite(tmp_path, monkeypatch, newline):
    origin = tmp_path / 'source'; origin.mkdir()
    (origin / 'args.json').write_text('{}')
    initial = (b'first' + newline) * 1000
    appended = b'next' + newline
    (origin / 'metrics.jsonl').write_bytes(initial)
    (origin / 'run.json').write_text('{"status":"running"}')
    (origin / 'latest.pt').write_bytes(b'checkpoint')
    cache = tmp_path / 'cache'
    record = {'id': 'live', 'source': {'kind': 'remote', 'path': str(origin)},
              'status': 'running', 'cache_dir': str(cache / 'live')}
    calls = []
    def rpc(alias, operation, payload):
        calls.append(operation)
        assert not payload['checkpoint']
        result = files.sync_files(payload)
        contents = json.loads(gzip.decompress(base64.b64decode(result['data'])))
        calls.append(contents)
        return result
    monkeypatch.setattr(sync, 'rpc', rpc)
    record.update(sync.sync_history(record, cache))
    assert calls[0] == 'sync_files'
    assert (cache / 'live' / 'metrics.jsonl').read_bytes() == initial
    assert not (cache / 'live' / 'latest.pt').exists()
    calls.clear()
    with (origin / 'metrics.jsonl').open('ab') as stream: stream.write(appended)
    record.update(sync.sync_history(record, cache))
    assert calls[1]['metrics.jsonl']['offset'] == len(initial)
    assert base64.b64decode(calls[1]['metrics.jsonl']['data']) == appended
    assert (cache / 'live' / 'metrics.jsonl').read_bytes() == initial + appended
    # Same inode can be rewritten as well as appended; verify the prefix.
    replacement = (b'replacement' + newline) * 1000
    (origin / 'metrics.jsonl').write_bytes(replacement)
    calls.clear()
    record.update(sync.sync_history(record, cache))
    assert calls[1]['metrics.jsonl']['offset'] == 0
    assert (cache / 'live' / 'metrics.jsonl').read_bytes() == replacement


def test_status_churn_keeps_transferred_manifest(tmp_path, monkeypatch):
    origin = tmp_path / 'source'; origin.mkdir()
    (origin / 'args.json').write_text('{}')
    (origin / 'metrics.jsonl').write_text('first\n')
    status = origin / 'run.json'; status.write_text('{"tick":1}')
    manifest = files.file_manifest
    calls = []
    def changing(payload):
        if calls: status.write_text('{"tick":333}')
        result = manifest(payload)
        calls.append(result)
        if len(calls) == 1: status.write_text('{"tick":2}')
        return result
    monkeypatch.setattr(files, 'file_manifest', changing)
    monkeypatch.setattr(sync, 'rpc', lambda alias, operation, payload: files.sync_files(payload))
    cache = tmp_path / 'cache'
    record = {'id': 'live', 'source': {'kind': 'remote', 'path': str(origin)},
              'status': 'running', 'cache_dir': str(cache / 'live')}
    result = sync.sync_history(record, cache)
    assert result['sync_status'] == 'pending'
    assert result['manifest']
    assert json.loads((cache / 'live' / 'run.json').read_text())['tick'] == 2


def test_old_agent_fallback_still_reads_coherent_status(tmp_path, monkeypatch):
    origin = tmp_path / 'source'; origin.mkdir()
    (origin / 'args.json').write_text('{}')
    (origin / 'metrics.jsonl').write_text('first\n')
    (origin / 'run.json').write_text('{"tick":1}')
    def old_rpc(alias, operation, payload):
        if operation == 'sync_files': raise RemoteError('UNKNOWN_OPERATION', 'old agent')
        return {'file_manifest': files.file_manifest, 'read_file': files.read_file,
                'read_file_chunk': files.read_file_chunk}[operation](payload)
    monkeypatch.setattr(sync, 'rpc', old_rpc)
    cache = tmp_path / 'cache'
    record = {'id': 'live', 'source': {'kind': 'remote', 'path': str(origin)},
              'status': 'running', 'cache_dir': str(cache / 'live')}
    assert sync.sync_history(record, cache)['sync_status'] == 'synced'
    assert json.loads((cache / 'live' / 'run.json').read_text()) == {'tick': 1}


def test_checkpoint_remains_streamed_separately(tmp_path, monkeypatch):
    origin = tmp_path / 'source'; origin.mkdir()
    (origin / 'args.json').write_text('{}')
    (origin / 'metrics.jsonl').write_text('first\n')
    (origin / 'latest.pt').write_bytes(b'checkpoint')
    monkeypatch.setattr(sync, 'rpc', lambda alias, operation, payload:
                        files.file_manifest(payload) if operation == 'file_manifest' else files.sync_files(payload))
    downloaded = []
    def checkpoint(source, entry, target):
        downloaded.append(entry)
        target.write_bytes((origin / 'latest.pt').read_bytes())
    monkeypatch.setattr(sync, 'download_checkpoint', checkpoint)
    cache = tmp_path / 'cache'
    record = {'id': 'done', 'source': {'kind': 'remote', 'path': str(origin)},
              'status': 'paused', 'cache_dir': str(cache / 'done')}
    record.update(sync.sync_history(record, cache))
    assert len(downloaded) == 1
    assert 'latest.pt' in record['files']
    record.update(sync.sync_history(record, cache))
    assert len(downloaded) == 1
