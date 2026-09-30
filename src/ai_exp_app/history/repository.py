TERMINAL = {'completed', 'stopped', 'failed', 'paused', 'external_exited'}


def should_auto_add(visibility: str, status: str) -> bool:
    return visibility == 'absent' and status in TERMINAL
