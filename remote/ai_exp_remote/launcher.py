import os
from pathlib import Path
from .projects import CONTROLLED
from .state import AgentError
from .config import settings

def build_launch(project, run, gpu_ids):
    python=project.get('python') or settings()['remote_python']
    argv=[python,'-m','torch.distributed.run','--standalone','--nproc-per-node='+str(len(gpu_ids)),'train.py']
    fields={f['key']:f for f in run['schema']['fields']}
    for key,value in run['parameters']['training'].items():
        if key in CONTROLLED:raise AgentError('CONTROLLED_PARAMETER','禁止覆盖受控参数',key)
        if key not in fields:raise AgentError('UNKNOWN_PARAMETER','参数不在源码定义中',key)
        if value is None:continue
        field=fields[key];flag=field['flags'][0]
        if field.get('action')=='_StoreTrueAction':
            if value:argv.append(flag)
        elif field.get('action')=='_StoreFalseAction':
            if not value:argv.append(flag)
        else:argv.extend([flag,str(value).lower() if isinstance(value,bool) else str(value)])
    data_root=project.get('data_root') or settings()['remote_data_root']
    if not data_root or not Path(data_root).is_absolute():
        raise AgentError('CONFIG_REQUIRED','请先配置远端数据绝对目录')
    argv.extend(['--run-dir',run['remote_path'],'--data-root',data_root])
    if run.get('resume_path'):argv.extend(['--resume',run['resume_path']])
    attempt_dir=run.get('attempt_dir',str(Path(run['snapshot']['path']).parent / '.runtime' / run['run_id']))
    env=dict(os.environ,CUDA_VISIBLE_DEVICES=','.join(map(str,gpu_ids)),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1',TORCHINDUCTOR_CACHE_DIR=attempt_dir+'/.inductor',TRITON_CACHE_DIR=attempt_dir+'/.triton')
    env.pop('HF_ENDPOINT',None)
    if run['parameters']['training'].get('deterministic') is True:
        env['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
    return dict(argv=argv,cwd=run['snapshot']['path'],env=env,launch_log=attempt_dir+'/launch.log')
