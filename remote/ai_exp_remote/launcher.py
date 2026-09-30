"""Build an argv launch from a project integration; never invoke a shell."""
import json
import os
from pathlib import Path
from .projects import integration
from .state import AgentError
from .config import settings


def expand(argv, values, optional_resume=False):
    result = []
    for arg in argv:
        if optional_resume and not values.get('resume') and '{resume}' in arg:
            raise AgentError('RESUME_COMMAND', '请使用 resume.flag 或 resume.command，避免新实验含空续跑参数')
        try:
            result.append(arg.format_map(values))
        except (KeyError, ValueError) as exc:
            raise AgentError('INTEGRATION_PLACEHOLDER', '启动命令包含未知占位符', str(exc)) from exc
    return result


def build_launch(project, run, gpu_ids):
    python = project.get('python') or settings()['remote_python']
    profile = run.get('schema', {}).get('integration') or integration(run['snapshot']['path'], project.get('integration'))
    attempt_dir = run.get('attempt_dir', str(Path(run['snapshot']['path']).parent / '.runtime' / run['run_id']))
    values = dict(python=python,run_dir=run['remote_path'],resume=run.get('resume_path',''),
                  gpu_count=str(len(gpu_ids)),gpu_ids=','.join(map(str,gpu_ids)),project_dir=run['snapshot']['path'],
                  parameter_file=attempt_dir+'/parameters.json')
    resume = profile.get('resume', {})
    command = resume.get('command', profile['command']) if values['resume'] else profile['command']
    argv = expand(command, values, optional_resume=True)
    fields = {f['key']:f for f in run['schema']['fields']}
    training = run['parameters']['training']
    parameter_argv = []
    for key,value in training.items():
        if key not in fields:
            raise AgentError('UNKNOWN_PARAMETER','参数不在项目定义中',key)
        if value is None:
            continue
        field = fields[key]
        choices = field.get('choices')
        if choices and value not in choices and not (field['kind'] == 'number_or_choice' and isinstance(value,(int,float)) and not isinstance(value,bool)):
            raise AgentError('PARAMETER_VALIDATION','参数不在允许选项中',key)
        flag = field['flags'][0]
        action = field.get('action')
        if action == '_StoreTrueAction':
            if value: parameter_argv.append(flag)
        elif action == '_StoreFalseAction':
            if not value: parameter_argv.append(flag)
        else:
            parameter_argv.extend([flag,str(value).lower() if isinstance(value,bool) else str(value)])
    if profile.get('parameter_style','cli') == 'json':
        Path(attempt_dir).mkdir(parents=True,exist_ok=True)
        Path(values['parameter_file']).write_text(json.dumps(training,ensure_ascii=False,allow_nan=False))
    else:
        argv.extend(parameter_argv)
    if values['resume'] and resume.get('flag'):
        argv.extend([resume['flag'],values['resume']])
    env = dict(os.environ,CUDA_VISIBLE_DEVICES=values['gpu_ids'],PYTHONDONTWRITEBYTECODE='1')
    for key,value in profile.get('environment', {}).items():
        if not isinstance(key,str) or not isinstance(value,str) or '\0' in key+value:
            raise AgentError('INTEGRATION_ENVIRONMENT','环境变量名称和值必须是字符串')
        env[key] = expand([value],values)[0]
    return dict(argv=argv,cwd=run['snapshot']['path'],env=env,launch_log=attempt_dir+'/launch.log',
                training=dict(training),parameter_argv=parameter_argv,integration=profile)
