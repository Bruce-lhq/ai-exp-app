import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from .snapshot import create_snapshot
from .state import AgentError

PYTHON = '/your_exp/venv/bin/python'
CONTROLLED = {'data_root','run_dir','resume','allow_nonexact_resume','allow_world_size_change','config_index','config_total','config_name','config_description'}
PROBE = r'''
import argparse, importlib.util, json, sys, contextlib
from pathlib import Path
path = Path(sys.argv[1]); sys.path.insert(0, str(path))
with contextlib.redirect_stdout(sys.stderr):
 spec=importlib.util.spec_from_file_location('ai_exp_selected_train',path/'train.py')
 module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
 parser=module.build_parser()
fields=[]
for group in parser._action_groups:
 for a in group._group_actions:
  if a.dest=='help' or not a.option_strings:continue
  typ=getattr(a.type,'__name__','')
  kind='integer' if a.type is int else 'number' if a.type is float else 'boolean' if typ in ('str2bool','parse_bool','bool') or isinstance(a,(argparse._StoreTrueAction,argparse._StoreFalseAction)) else 'string'
  fields.append(dict(key=a.dest,flags=a.option_strings,kind=kind,nullable=a.default is None,has_default=a.default!=argparse.SUPPRESS,default=None if a.default==argparse.SUPPRESS else a.default,required=a.required,choices=list(a.choices) if a.choices else None,group=group.title,help=a.help or '',constraints={},action=type(a).__name__))
print(json.dumps(fields))
'''

def directory(path):
    path = Path(path)
    if not path.is_absolute() or '\0' in str(path) or not path.is_dir():
        raise AgentError('INVALID_PATH', '请选择存在的绝对目录')
    return path.resolve()


def inspect_project(payload):
    path = directory(payload['path'])
    result = dict(path=str(path), git=False, branches=[], commit=None, branch=None, dirty=False, supported=(path/'train.py').is_file())
    git = subprocess.run(['git','-C',str(path),'rev-parse','--show-toplevel'],text=True,capture_output=True)
    if git.returncode == 0:
        def command(*args):
            return subprocess.check_output(['git','-C',str(path),*args],text=True).strip()
        result.update(git=True,commit=command('rev-parse','HEAD'),branch=command('branch','--show-current'),dirty=bool(command('status','--porcelain')),branches=command('for-each-ref','--format=%(refname:short)','refs/heads','refs/remotes').splitlines())
    return result


def read_schema(payload):
    path = directory(payload['path'])
    code = payload.get('code') or {'kind':'working_tree'}
    with tempfile.TemporaryDirectory(prefix='ai-exp-probe-') as temp:
        snapshot = create_snapshot(path,Path(temp)/'code',code,payload.get('exclusions',[]))
        env = dict(os.environ, CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1')
        from .parser_probe import fields as parser_fields
        try:
            fields = [f for f in parser_fields(snapshot['path']) if f['key'] not in CONTROLLED]
        except Exception as exc:
            raise AgentError('SCHEMA_UNSUPPORTED','无法读取 launcher 的纯参数定义；此项目需要额外适配',str(exc)) from exc
        return dict(fields=fields, code_fingerprint=snapshot['id'], schema_fingerprint=hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest())
