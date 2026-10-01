import contextlib
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

class AgentError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.details = code, details


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def emit(state, kind, run=None, payload=None):
    state['seq'] += 1
    event = dict(seq=state['seq'], event_id=str(uuid.uuid4()), kind=kind,
                 run_id=run.get('run_id') if run else None,
                 attempt_id=run.get('attempt_id') if run else None,
                 at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), payload=payload or {})
    state['events'].append(event)
    return event


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def transaction(self):
        import fcntl  # The remote state store runs on Linux; pure helpers remain importable elsewhere.
        with (self.root / 'state.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.root / 'state.json'
            if path.exists():
                try:
                    state = json.loads(path.read_text())
                    assert all(k in state for k in ('runs','queue','requests','events','revision','seq','paused'))
                except (ValueError, AssertionError) as exc:
                    raise AgentError('STATE_CORRUPT', '远端状态损坏，已停止调度') from exc
            elif (self.root / 'initialized').exists():
                raise AgentError('STATE_MISSING', '远端状态丢失，已停止调度')
            else:
                state = dict(runs={}, queue=[], requests={}, events=[], revision=0, seq=0, paused=False)
            before = json.dumps(state, sort_keys=True)
            yield state
            if not path.exists() or json.dumps(state, sort_keys=True) != before:
                state['revision'] += 1
                atomic_json(path, state)
                (self.root / 'initialized').touch()
