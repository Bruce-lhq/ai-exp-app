import os
from pathlib import Path
from .projects import PYTHON, CONTROLLED
from .state import AgentError

def build_launch(project, run, gpu_ids):
    python=project.get('python') or PYTHON
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
    argv.extend(['--run-dir',run['remote_path'],'--data-root',project.get('data_root','/your_exp/data/fineweb_edu_gpt2_100B')])
    if run.get('resume_path'):argv.extend(['--resume',run['resume_path']])
    attempt_dir=run.get('attempt_dir',str(Path(run['snapshot']['path']).parent / '.runtime' / run['run_id']))
    env=dict(os.environ,CUDA_VISIBLE_DEVICES=','.join(map(str,gpu_ids)),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1',TORCHINDUCTOR_CACHE_DIR=attempt_dir+'/.inductor',TRITON_CACHE_DIR=attempt_dir+'/.triton')
    env.pop('HF_ENDPOINT',None)
    return dict(argv=argv,cwd=run['snapshot']['path'],env=env,launch_log=attempt_dir+'/launch.log')
