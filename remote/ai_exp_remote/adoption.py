"""Observe external torchrun launchers; never signal shells or process groups."""
import ctypes
import errno
import os
from pathlib import Path
import platform
import signal
import time
from .state import AgentError


def processes():
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    result = {}
    for root in Path('/proc').glob('[0-9]*'):
        try:
            stat = (root / 'stat').read_text().rsplit(')', 1)[1].split()
            if stat[0] == 'Z':
                continue
            argv = (root / 'cmdline').read_bytes().decode().split('\0')[:-1]
            result[int(root.name)] = dict(pid=int(root.name), ppid=int(stat[1]),
                start_ticks=stat[19], boot_id=boot, argv=argv,
                cwd=str((root / 'cwd').resolve()))
        except (OSError, ValueError, UnicodeError):
            continue
    return result


def same(saved, current):
    return current is not None and all(saved.get(k) == current.get(k)
        for k in ('pid', 'start_ticks', 'boot_id', 'argv', 'cwd'))


def run_path(argv):
    if '--run-dir' in argv:
        index = argv.index('--run-dir')
        return argv[index + 1] if index + 1 < len(argv) else None
    return next((arg.split('=', 1)[1] for arg in argv if arg.startswith('--run-dir=')), None)


def descendants(pid, table):
    found = {pid}
    while True:
        next_ids = found | {p['pid'] for p in table.values() if p['ppid'] in found}
        if next_ids == found:
            return [table[i] for i in sorted(found) if i in table]
        found = next_ids


def discover(path, table=None):
    table = processes() if table is None else table
    matches = [p for p in table.values() if run_path(p['argv']) == path
        and any(Path(a).name == 'torchrun' or a == 'torch.distributed.run' for a in p['argv'][:4])]
    if len(matches) != 1:
        raise AgentError('ADOPTION_IDENTITY', '未找到唯一匹配此实验目录的 torchrun，拒绝接管')
    launcher = matches[0]
    members = descendants(launcher['pid'], table)
    if any(run_path(p['argv']) not in (None, path) for p in members):
        raise AgentError('ADOPTION_IDENTITY', '进程树包含其他实验，拒绝接管')
    return dict(launcher=launcher, members=members, status='external_running',
                adopted_at=time.time(), remote_path=path)


def signal_launcher(saved):
    # A pidfd pins the process across the final identity check and signal.
    # Linux x86_64/aarch64 use these syscall numbers, including Python 3.8 hosts.
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'aarch64'):
        raise AgentError('PIDFD_UNAVAILABLE', '当前主机不支持安全进程控制')
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.syscall(434, saved['pid'], 0)
    if fd < 0:
        raise AgentError('PROCESS_CHANGED', '无法锁定训练进程，请刷新并重新接管')
    try:
        if not same(saved, processes().get(saved['pid'])):
            raise AgentError('PROCESS_CHANGED', '训练进程身份已变化，未发送停止信号')
        if libc.syscall(424, fd, int(signal.SIGTERM), 0, 0) < 0:
            error = ctypes.get_errno()
            if error != errno.ESRCH:
                raise OSError(error, os.strerror(error))
    finally:
        os.close(fd)


def pause(record):
    table = processes()
    launcher = record['launcher']
    if not same(launcher, table.get(launcher['pid'])):
        raise AgentError('PROCESS_CHANGED', '接管后进程已变化，请重新接管；未发送信号')
    members = descendants(launcher['pid'], table)
    if any(run_path(p['argv']) not in (None, record['remote_path']) for p in members):
        raise AgentError('PROCESS_CHANGED', '进程树出现其他实验，未发送信号')
    signal_launcher(launcher)
    record.update(members=members, status='stopping', pause_requested=time.time())


def observe(record, table):
    alive = [p for p in record['members'] if same(p, table.get(p['pid']))]
    if record['status'] == 'stopping' and not alive:
        record.update(status='paused', ended_at=time.time())
        from .runtime import latest_tokens
        record['stop_tokens'] = latest_tokens(Path(record['remote_path']) / 'metrics.jsonl')
    elif record['status'] == 'external_running' and not same(record['launcher'], table.get(record['launcher']['pid'])):
        record['status'] = 'external_exited'
    return record
