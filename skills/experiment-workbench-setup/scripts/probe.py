#!/usr/bin/env python3
"""Inspect source or probe an SSH host without importing or running training code."""
import argparse
import ast
import json
import re
import shlex
import subprocess
from pathlib import Path


def inspect_source(path, entrypoints=()):
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Source directory does not exist')
    files = sorted(p.name for p in root.iterdir() if p.is_file() and not p.name.startswith('.'))
    python_files = list(root.glob('*.py'))
    for folder in root.iterdir():
        if folder.is_dir() and not folder.is_symlink() and not folder.name.startswith('.') and folder.name not in {'venv', 'node_modules', 'tests'}:
            python_files.extend(folder.glob('*.py'))
    for name in entrypoints:
        file = (root / name).resolve()
        if root not in file.parents or not file.is_file():
            raise ValueError('Explicit entrypoint must be an existing file inside the source root')
        if file not in python_files:
            python_files.insert(0, file)
    entries, warnings = [], []
    for file in sorted(python_files)[:100]:
        if file.is_symlink() or file.stat().st_size > 2_000_000:
            continue
        try:
            tree = ast.parse(file.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeError) as exc:
            warnings.append(str(file.relative_to(root)) + ': ' + type(exc).__name__)
            continue
        arguments = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != 'add_argument':
                continue
            flags = [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
            default = next((kw.value for kw in node.keywords if kw.arg == 'default'), None)
            item = {'flags': flags}
            if default is not None:
                try:
                    value = ast.literal_eval(default)
                    json.dumps(value, allow_nan=False)
                    item['literal_default'] = value
                except (ValueError, TypeError):
                    item['default_requires_review'] = True
            arguments.append(item)
        functions = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if arguments or file.stem in {'train', 'main', 'experiment'}:
            entries.append({'path': str(file.relative_to(root)), 'functions': functions, 'arguments': arguments})
    return {'root': str(root), 'files': files, 'entrypoints': entries, 'warnings': warnings,
            'coverage': 'Top-level and immediate subdirectories, at most 100 Python files; use --entrypoint for deeper paths.',
            'note': 'Static inspection only; no source code was executed.'}


def probe_ssh(alias, project=None, python='python3'):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', alias) or alias.startswith('-'):
        raise ValueError('Use an SSH Host alias from your SSH config')
    if '\n' in python or '\0' in python:
        raise ValueError('Invalid Python executable')
    script = '\n'.join([
        'import json, os, shutil, subprocess, sys',
        'from pathlib import Path',
        'project = ' + repr(project),
        'result = {"python":sys.executable,"python_version":list(sys.version_info[:3]),"platform":sys.platform,"home":str(Path.home()),"read_only":True}',
        'if project:',
        ' p = Path(project); result["project"]={"path":str(p),"exists":p.is_dir(),"readable":os.access(str(p),os.R_OK),"profile":(p/"workbench.project.json").is_file()}',
        'tools={name:shutil.which(name) for name in ("nvidia-smi","amd-smi","rocm-smi")}; result["gpu_tools"]=tools',
        'gpu = tools["nvidia-smi"]',
        'if gpu:',
        ' r=subprocess.run([gpu,"--query-gpu=index,name,memory.total","--format=csv,noheader"],capture_output=True,text=True,timeout=15); result["gpu"]={"available":r.returncode==0,"inventory":r.stdout.strip(),"error":r.stderr.strip()}',
        'else: result["gpu"]={"available":None,"error":"No NVIDIA query; inspect vendor tools or configured inventory. This does not establish that GPUs are absent."}',
        'print(json.dumps(result))',
    ])
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', alias, shlex.quote(python) + ' -'], input=script, text=True, capture_output=True, timeout=35)
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'SSH probe failed')
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    local = commands.add_parser('local'); local.add_argument('path'); local.add_argument('--entrypoint', action='append', default=[])
    ssh = commands.add_parser('ssh'); ssh.add_argument('--alias', required=True)
    ssh.add_argument('--project'); ssh.add_argument('--python', default='python3')
    args = parser.parse_args()
    try:
        result = inspect_source(args.path, args.entrypoint) if args.command == 'local' else probe_ssh(args.alias, args.project, args.python)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
