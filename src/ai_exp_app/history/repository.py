TERMINAL = {'completed', 'stopped', 'failed'}


def should_auto_add(visibility: str, status: str) -> bool:
    return visibility == 'absent' and status in TERMINAL
