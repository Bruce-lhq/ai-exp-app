import json
import os
from pathlib import Path
import signal
import subprocess
import time
from .state import atomic_json, AgentError

def identity(pid):
    try:
        stat=Path('/proc/%s/stat'%pid).read_text().rsplit(')',1)[1].split()
        return dict(pid=pid,pgid=os.getpgid(pid),boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),start_ticks=stat[19])
    except (OSError,IndexError):return None

def alive(record):
    actual=identity(record['pid'])
    return actual is not None and all(actual.get(k)==record.get(k) for k in ('pid','pgid','boot_id','start_ticks'))

def stop_attempt(record):
    if alive(record):
        if record['pgid']!=record['pid']:raise AgentError('IDENTITY_MISMATCH','拒绝停止非独立进程组')
        os.killpg(record['pgid'],signal.SIGTERM)
        return {'signaled':True}
    return {'signaled':False}

def execute_attempt(spec_file):
    """Detached supervisor writes exit evidence even when the SSH client disappears."""
    spec=json.loads(Path(spec_file).read_text());folder=Path(spec_file).parent
    import fcntl
    with (folder/'execution.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        if (folder/'exit.json').exists():return
        atomic_json(folder/'supervisor.json',identity(os.getpid()))
        try:
            with open(spec['launch_log'],'ab') as log:
                process=subprocess.Popen(spec['argv'],cwd=spec['cwd'],env=spec['env'],stdout=log,stderr=log,start_new_session=True,stdin=subprocess.DEVNULL)
                atomic_json(folder/'identity.json',identity(process.pid))
                atomic_json(folder/'exit.json',{'exit_code':process.wait(),'at':time.time()})
        except Exception as exc:
            atomic_json(folder/'exit.json',{'exit_code':-1,'error':str(exc),'at':time.time()})
