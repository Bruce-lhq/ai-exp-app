"""Project discovery and declarative training integrations."""
import hashlib
import json
from pathlib import Path
import subprocess
import string
import tempfile
from .snapshot import create_snapshot
from .state import AgentError

PYTHON = 'python3'


def directory(path):
    path = Path(path)
    if not path.is_absolute() or '\0' in str(path) or not path.is_dir():
        raise AgentError('INVALID_PATH', '请选择存在的绝对目录')
    return path.resolve()


def integration(path, override=None):
    manifest = Path(path) / 'workbench.project.json'
    value = override if override is not None else json.loads(manifest.read_text()) if manifest.exists() else {}
    return validate_profile(value)


def validate_profile(document):
    if not isinstance(document,dict):
        raise AgentError('INTEGRATION_SCHEMA','项目接入文件必须是 JSON 对象')
    value = dict(document)
    if value.get('version', 1) != 1:
        raise AgentError('INTEGRATION_VERSION', '不支持的项目接入版本')
    value.setdefault('version', 1)
    value.setdefault('entrypoint', 'train.py')
    value.setdefault('parser_function', 'build_parser')
    value.setdefault('command', ['{python}', value['entrypoint']])
    command = value['command']
    if not isinstance(command, list) or not command or any(not isinstance(x, str) or '\0' in x for x in command):
        raise AgentError('INTEGRATION_COMMAND', 'command 必须是非空字符串数组，不使用 shell')
    if value.get('parameter_style', 'cli') not in ('cli', 'json'):
        raise AgentError('INTEGRATION_PARAMETERS', 'parameter_style 必须是 cli 或 json')
    if value.get('parameter_style') == 'json' and not any('{parameter_file}' in arg for arg in command):
        raise AgentError('INTEGRATION_PARAMETERS', 'json 参数模式需要 command 中的 {parameter_file}')
    if not isinstance(value.get('environment', {}), dict):
        raise AgentError('INTEGRATION_ENVIRONMENT', 'environment 必须是对象')
    for key,item in value.get('environment',{}).items():
        if not isinstance(key,str) or not key or '=' in key or not isinstance(item,str) or '\0' in key+item:
            raise AgentError('INTEGRATION_ENVIRONMENT','环境变量名称和值必须是字符串；名称不能包含 =')
    for option in ('entrypoint','parser_function'):
        if not isinstance(value[option],str) or not value[option]:
            raise AgentError('INTEGRATION_SCHEMA', option + ' 必须是字符串')
    if 'parameters' in value and (not isinstance(value['parameters'],list) or any(not isinstance(p,dict) for p in value['parameters'])):
        raise AgentError('INTEGRATION_SCHEMA','parameters 必须是参数对象数组')
    controlled = value.get('controlled_parameters',[])
    if not isinstance(controlled,list) or any(not isinstance(k,str) for k in controlled):
        raise AgentError('INTEGRATION_SCHEMA','controlled_parameters 必须是字符串数组')
    runtime = value.get('runtime', {})
    if not isinstance(runtime, dict) or ('workers_parameter' in runtime and (not isinstance(runtime['workers_parameter'], str) or not runtime['workers_parameter'])):
        raise AgentError('INTEGRATION_SCHEMA', 'runtime 必须是对象，workers_parameter 必须是参数名称')
    resume = value.get('resume')
    if resume is not None:
        if not isinstance(resume,dict) or not isinstance(resume.get('validator'),list) or not resume['validator'] or any(not isinstance(a,str) for a in resume['validator']):
            raise AgentError('INTEGRATION_RESUME','resume 需要非空 validator 命令数组')
        checkpoint = resume.get('checkpoint','latest.pt')
        if not isinstance(checkpoint,str) or Path(checkpoint).is_absolute() or '..' in Path(checkpoint).parts:
            raise AgentError('INTEGRATION_RESUME','checkpoint 必须是实验目录中的相对文件路径')
    launch_keys={'python','run_dir','resume','gpu_count','gpu_ids','project_dir','parameter_file'}
    def placeholders(args,allowed):
        try:
            for arg in args:
                for _,name,format_spec,conversion in string.Formatter().parse(arg):
                    if name is not None and (name not in allowed or format_spec or conversion):
                        raise ValueError('未知占位符 ' + str(name))
        except (ValueError,TypeError) as exc:
            raise AgentError('INTEGRATION_PLACEHOLDER','接入文件含无效占位符',str(exc)) from exc
    placeholders(command,launch_keys)
    placeholders(list(value.get('environment',{}).values()),launch_keys)
    if resume is not None:
        resume_command=resume.get('command',command)
        if not isinstance(resume_command,list) or not resume_command or any(not isinstance(x,str) for x in resume_command):
            raise AgentError('INTEGRATION_RESUME','resume.command 必须是字符串数组')
        if not resume.get('flag') and not any('{resume}' in arg for arg in resume_command):
            raise AgentError('INTEGRATION_RESUME','resume 需要 flag 或包含 {resume} 的 command')
        placeholders(resume_command,launch_keys)
        placeholders(resume['validator'],{'python','checkpoint','request','project_dir'})
        if 'flag' in resume and (not isinstance(resume['flag'],str) or not resume['flag'].startswith('-')):
            raise AgentError('INTEGRATION_RESUME','resume.flag 必须是命令行选项')
        required=resume.get('required_state',[])
        if not isinstance(required,list) or any(not isinstance(x,str) for x in required):
            raise AgentError('INTEGRATION_RESUME','required_state 必须是字符串数组')
    if 'parameters' in value:
        schema_fields(value,None)
    return value


def inspect_project(payload):
    path = directory(payload['path'])
    result = dict(path=str(path), git=False, branches=[], commit=None, branch=None, dirty=False,
                  supported=bool(payload.get('integration')) or (path/'workbench.project.json').is_file() or (path/'train.py').is_file())
    git = subprocess.run(['git','-C',str(path),'rev-parse','--show-toplevel'],text=True,capture_output=True)
    if git.returncode == 0:
        def command(*args):
            return subprocess.check_output(['git','-C',str(path),*args],text=True).strip()
        result.update(git=True,commit=command('rev-parse','HEAD'),branch=command('branch','--show-current'),dirty=bool(command('status','--porcelain')),branches=command('for-each-ref','--format=%(refname:short)','refs/heads','refs/remotes').splitlines())
    return result


def schema_fields(profile, path):
    if 'parameters' not in profile:
        from .parser_probe import fields
        return fields(path, profile['entrypoint'], profile['parser_function'])
    result = []
    for item in profile['parameters']:
        key = item.get('name', item.get('key'))
        kind = item.get('type', item.get('kind', 'string'))
        if not isinstance(key, str) or not key or kind not in ('integer','number','number_or_choice','boolean','string'):
            raise ValueError('参数必须有 name 和受支持的 type')
        flags = item.get('flags') or [item.get('flag', '--' + key.replace('_', '-'))]
        if not isinstance(flags,list) or not flags or any(not isinstance(flag, str) or not flag.startswith('-') for flag in flags):
            raise ValueError('flag 必须是命令行选项')
        action = {'store':'_StoreAction','store_true':'_StoreTrueAction','store_false':'_StoreFalseAction'}.get(item.get('action','store'),item.get('action','_StoreAction'))
        if action not in ('_StoreAction','_StoreTrueAction','_StoreFalseAction'):
            raise ValueError('参数 action 不受支持')
        default = item.get('default')
        valid = default is None or (kind == 'string' and isinstance(default,str)) or (kind == 'boolean' and isinstance(default,bool)) or (kind == 'integer' and isinstance(default,int) and not isinstance(default,bool)) or (kind in ('number','number_or_choice') and isinstance(default,(int,float)) and not isinstance(default,bool)) or (kind == 'number_or_choice' and isinstance(default,str) and default in item.get('choices',[]))
        if not valid:
            raise ValueError('参数默认值类型错误：' + key)
        choices = item.get('choices')
        if choices is not None and (not isinstance(choices,list) or not choices):
            raise ValueError('choices 必须是非空数组：' + key)
        if choices and default is not None and default not in choices:
            raise ValueError('默认值不在 choices 中：' + key)
        result.append(dict(key=key,flags=flags,kind=kind,nullable=item.get('nullable',item.get('default') is None),
                           has_default='default' in item,default=item.get('default'),required=item.get('required',False),
                           choices=item.get('choices'),group=item.get('group','参数'),help=item.get('help',''),
                           constraints=item.get('constraints',{}),action=action))
    if len({item['key'] for item in result}) != len(result):
        raise ValueError('参数名称不能重复')
    return result


def read_schema(payload):
    path = directory(payload['path'])
    code = payload.get('code') or {'kind':'working_tree'}
    with tempfile.TemporaryDirectory(prefix='ai-exp-probe-') as temp:
        snapshot = create_snapshot(path,Path(temp)/'code',code,payload.get('exclusions',[]))
        try:
            profile = integration(snapshot['path'], payload.get('integration'))
            controlled = profile.get('controlled_parameters', [])
            fields = [f for f in schema_fields(profile, snapshot['path']) if f['key'] not in controlled]
        except Exception as exc:
            raise AgentError('SCHEMA_UNSUPPORTED','无法读取项目参数；请提供 workbench.project.json 参数定义',str(exc)) from exc
        return dict(fields=fields,integration=profile,controlled_keys=controlled,code_fingerprint=snapshot['id'],
                    schema_fingerprint=hashlib.sha256(json.dumps({'fields':fields,'integration':profile},sort_keys=True).encode()).hexdigest())
