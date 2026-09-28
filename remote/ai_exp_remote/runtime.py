"""Single remote scheduler with durable, fail-closed process handoffs."""
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import uuid
from .launcher import build_launch
from .runner import alive, stop_attempt
from .scheduler import gpu_status, schedule_head
from .state import atomic_json, emit, Store

ACTIVE = ('starting', 'running', 'stopping')

def worker_command(*args):
    return [sys.executable, str(Path(sys.argv[0]).resolve()), *args]

def tail(path, limit=16000):
    if not path.exists():
        return ''
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - limit))
        return stream.read(limit).decode('utf-8', errors='replace')

def latest_tokens(path):
    for line in reversed(tail(path, 65536).splitlines()):
        try:
            item = json.loads(line)
            value = item.get('tokens_seen', item.get('tokens'))
            if isinstance(value, (int, float)):
                return value
        except (ValueError, AttributeError):
            continue
    return None

def pause_failure(state, run, reason):
    run['status'] = 'failed'
    run['ended_at'] = time.time()
    run['error'] = reason
    emit(state, 'failed', run, {'reason': reason})
    state['paused'] = True
    emit(state, 'queue_paused', run, {'reason': reason})

def write_metadata(run):
    output = Path(run['remote_path'])
    # train.py refuses nonempty new output directories; only write once it has prepared them.
    if not (output / 'train.log').exists():
        return
    if run['status'] not in ACTIVE and run.get('attempt_dir'):
        launch = Path(run['attempt_dir']) / 'launch.log'
        if launch.exists():
            temporary = output / '.launch.log.tmp'
            shutil.copyfile(launch, temporary)
            os.replace(temporary, output / 'launch.log')
    atomic_json(output / 'run.json', {k: run.get(k) for k in (
        'id', 'run_id', 'display_name', 'status', 'project_id', 'attempt_id', 'attempts',
        'stop_tokens', 'ended_at', 'created_at', 'gpu_count')})

def tick(store):
    with store.transaction() as state:
        for run in state['runs'].values():
            if run['status'] not in ACTIVE:
                continue
            folder = store.root / 'attempts' / run['attempt_id']
            ident_file, exit_file = folder / 'identity.json', folder / 'exit.json'
            if ident_file.exists():
                run['identity'] = json.loads(ident_file.read_text())
                if run['status'] == 'starting':
                    run['status'] = 'running'
                    emit(state, 'started', run, dict(parameters=run['parameters'], project_id=run['project_id'], code=run['code'], gpu_ids=run['gpu_ids']))
            ended = json.loads(exit_file.read_text()) if exit_file.exists() else None
            if not ended and run.get('stop_requested') and run.get('identity'):
                stop_attempt(run['identity'])
                if time.time() - run['stop_requested'] > 20 and alive(run['identity']):
                    os.killpg(run['identity']['pgid'], signal.SIGKILL)
            lost = False
            if not ended and time.time() - run['attempt_started_at'] > 30:
                supervisor = folder / 'supervisor.json'
                lost = not supervisor.exists() or not alive(json.loads(supervisor.read_text()))
                if lost and run.get('identity') and alive(run['identity']):
                    stop_attempt(run['identity'])
                    continue
            if ended or lost:
                text = tail(Path(run['remote_path']) / 'train.log')
                success = ended and ended['exit_code'] == 0 and 'done:' in text and ('Best:' in text or 'Final:' in text)
                run['status'] = 'completed' if success else 'stopped' if run.get('stop_requested') else 'failed'
                run['ended_at'], run['exit'] = time.time(), ended
                if run['status'] == 'stopped':
                    run['stop_tokens'] = latest_tokens(Path(run['remote_path']) / 'metrics.jsonl')
                for attempt in run.get('attempts', []):
                    if attempt['attempt_id'] == run['attempt_id']:
                        attempt.update(ended_at=run['ended_at'], status=run['status'], exit=ended)
                emit(state, run['status'], run)
                if run['status'] == 'failed':
                    state['paused'] = True
                    emit(state, 'queue_paused', run, {'reason': 'experiment_failed'})
            write_metadata(run)
        try:
            devices = gpu_status()
        except Exception as exc:
            # Commit observed exits even when the GPU inventory query fails.
            if not state['paused']:
                state['paused'] = True
                emit(state, 'queue_paused', payload={'reason': 'gpu_inventory_failed', 'error': str(exc)})
            return
        reserved = {gpu for r in state['runs'].values() if r['status'] in ACTIVE for gpu in r.get('gpu_ids', [])}
        available = [d['index'] for d in devices if d['available'] and d['index'] not in reserved]
        while True:
            decision = schedule_head([state['runs'][x] for x in state['queue']], available, state['paused'])
            if not decision:
                break
            run = state['runs'][decision['run_id']]
            state['queue'].pop(0)
            run.update(status='starting', gpu_ids=decision['gpu_ids'], attempt_id=str(uuid.uuid4()), attempt_started_at=time.time(), stop_requested=None)
            folder = store.root / 'attempts' / run['attempt_id']
            try:
                folder.mkdir(parents=True)
                run['attempt_dir'] = str(folder)
                run.pop('identity', None)
                metrics = Path(run['remote_path']) / 'metrics.jsonl'
                with metrics.open('rb') if metrics.exists() else open(os.devnull, 'rb') as stream:
                    source_index = sum(1 for _ in stream)
                run.setdefault('attempts', []).append(dict(id=run['attempt_id'], source_index=source_index, attempt_id=run['attempt_id'], started_at=run['attempt_started_at'], resume_tokens=run.get('resume_tokens'), metrics_start_offset=metrics.stat().st_size if metrics.exists() else 0))
                spec = build_launch(run['project'], run, run['gpu_ids'])
                atomic_json(folder / 'spec.json', spec)
                # Persist before Popen. A missing handshake fails after restart instead of double-starting.
                atomic_json(store.root / 'state.json', state)
                subprocess.Popen(worker_command('attempt', str(folder / 'spec.json')), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            except Exception as exc:
                pause_failure(state, run, 'launch_failed: ' + str(exc))
                break
            available = [x for x in available if x not in run['gpu_ids']]

def daemon(root):
    import fcntl
    store = Store(root)
    with (store.root / 'daemon.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        while True:
            try:
                tick(store)
            except Exception as exc:
                atomic_json(store.root / 'daemon_error.json', {'error': str(exc), 'at': time.time()})
                try:
                    with store.transaction() as state:
                        if not state['paused']:
                            state['paused'] = True
                            emit(state, 'queue_paused', payload={'reason': 'scheduler_error', 'error': str(exc)})
                except Exception:
                    pass  # Corrupt state must never be replaced with an empty queue.
            time.sleep(3)

def ensure_daemon(root):
    subprocess.Popen(worker_command('daemon', str(root)), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
