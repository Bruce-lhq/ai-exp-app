"""Read deployment-specific paths beside the agent, never from its archive."""
import json
import os
from pathlib import Path
import sys


def settings():
    agent = Path(sys.argv[0]).resolve()
    root = agent.parent.parent if agent.suffix == '.pyz' and agent.parent.name == 'releases' else agent.parent if agent.suffix == '.pyz' else Path.home() / '.local/share/ai-exp-app'
    path = Path(os.environ.get('AI_EXP_CONFIG_FILE', str(root / 'config.local.json')))
    document = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(document, dict):
        raise ValueError('config.local.json must be an object')
    defaults = dict(remote_root=str(root), remote_state_dir=str(root / 'state'), remote_python='python3', remote_runs_root='', remote_data_root='', remote_groups_root='')
    result = {**defaults, **document}
    result['remote_state_dir'] = result['remote_state_dir'] or str(root / 'state')
    result['remote_python'] = result['remote_python'] or 'python3'
    return result
