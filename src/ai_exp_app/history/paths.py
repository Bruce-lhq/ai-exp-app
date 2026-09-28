import re


def export_basename(name: str, run_id: str, occupied: set[str]) -> str:
    name = re.sub(r'[/\\\x00-\x1f:]', '_', name).strip()
    if name in {'', '.', '..'}:
        raise ValueError('实验名称不能为空或为路径符号')
    name = name[:160]
    if name in occupied:
        name += '-' + re.sub(r'[^a-zA-Z0-9]', '', run_id)[:8]
    candidate, index = name, 2
    while candidate in occupied:
        candidate = f'{name}-{index}'
        index += 1
    return candidate
