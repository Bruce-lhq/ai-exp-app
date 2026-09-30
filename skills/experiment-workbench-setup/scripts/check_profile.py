#!/usr/bin/env python3
"""Validate a profile with the remote agent's own validator; do not run training."""
import argparse
import json
import os
from pathlib import Path
import sys


def find_repository(explicit=None):
    candidates = [Path(explicit)] if explicit else []
    if not explicit:
        if os.environ.get('AI_EXP_REPO'):
            candidates.append(Path(os.environ['AI_EXP_REPO']))
        candidates.extend([Path(__file__).resolve().parents[3], Path.cwd(), *Path.cwd().parents])
    for root in candidates:
        root = root.expanduser().resolve()
        if (root / 'pyproject.toml').is_file() and (root / 'remote/ai_exp_remote/projects.py').is_file():
            return root
    raise ValueError('Workbench source checkout not found; pass --repo /path/to/ai-exp-app or set AI_EXP_REPO')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path)
    parser.add_argument('--repo', type=Path, help='Workbench source checkout, required when an installed skill cannot discover it')
    args = parser.parse_args()
    # This helper ships inside the source repository, beside the actual implementation.
    try:
        repository = find_repository(args.repo)
        sys.path.insert(0, str(repository / 'remote'))
        from ai_exp_remote.projects import schema_fields, validate_profile
        normalized = validate_profile(json.loads(args.profile.read_text(encoding='utf-8')))
        if 'parameters' in normalized:
            schema_fields(normalized, args.profile.parent)
    except Exception as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(normalized, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
