"""Explicit project-owned strict-resume verification; no implicit unpickling."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from .state import AgentError

REQUIRED_STATE = ('model','optimizer','scheduler','rng','data_position')


def checkpoint_identity(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise AgentError('CHECKPOINT_MISSING', '云端没有可用的 checkpoint 文件')
    stat = path.stat()
    return dict(size=stat.st_size, mtime_ns=stat.st_mtime_ns, inode=stat.st_ino)


def verify(profile, project, checkpoint, request):
    from .launcher import expand
    hook = profile.get('resume', {})
    if not hook.get('validator'):
        raise AgentError('RESUME_UNSUPPORTED','此项目尚未配置严格续跑校验器；请让 Agent 检查保存与恢复代码后配置')
    before = checkpoint_identity(checkpoint)
    with tempfile.TemporaryDirectory(prefix='ai-exp-resume-') as temp:
        request_file = Path(temp)/'request.json'
        request_file.write_text(json.dumps(dict(request,checkpoint_path=str(checkpoint)),ensure_ascii=False,allow_nan=False))
        values = dict(python=project.get('python') or 'python3',checkpoint=str(checkpoint),request=str(request_file),project_dir=project['path'])
        try:
            result = subprocess.run(expand(hook['validator'],values),cwd=project['path'],capture_output=True,text=True,
                                    timeout=90,env=dict(os.environ,CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1'))
            if result.returncode:
                raise ValueError(result.stderr[-2000:])
            value = json.loads(result.stdout)
            states = value.get('verified_state',{})
            required = set(REQUIRED_STATE) | set(hook.get('required_state',[]))
            if value.get('strict') is not True or any(states.get(key) is not True for key in required):
                raise ValueError('校验器未确认模型、优化器、调度器、随机数及数据位置的完整状态')
            if value.get('errors') or value.get('compatible') is not True:
                raise ValueError(value.get('errors') or 'checkpoint 与当前配置不兼容')
            if not isinstance(value.get('training'),dict) or not isinstance(value.get('runtime',{}).get('gpu_count'),int) or value['runtime']['gpu_count'] < 1:
                raise ValueError('校验器未返回原训练参数和 GPU 数量')
        except (ValueError,TypeError,AttributeError,OSError,subprocess.SubprocessError) as exc:
            raise AgentError('CHECKPOINT_INVALID','checkpoint 无法严格续跑',str(exc)) from exc
    if before != checkpoint_identity(checkpoint):
        raise AgentError('CHECKPOINT_CHANGED','checkpoint 正在更新，请重新载入')
    return dict(value,path=str(checkpoint),identity=before)


def preview(payload):
    from .projects import directory, integration
    from .snapshot import create_snapshot
    project = dict(payload.get('project') or {})
    if not project.get('path'):
        raise AgentError('RESUME_UNSUPPORTED','请先选择已配置严格续跑校验器的代码项目')
    source = directory(project['path'])
    with tempfile.TemporaryDirectory(prefix='ai-exp-preview-') as temp:
        snapshot = create_snapshot(source,Path(temp)/'code',payload.get('code') or project.get('code') or {'kind':'working_tree'},project.get('exclusions',[]))
        project['path'] = snapshot['path']
        profile = integration(project['path'],project.get('integration'))
        checkpoint = Path(payload['path']) / profile.get('resume',{}).get('checkpoint','latest.pt')
        return verify(profile,project,checkpoint,dict(phase='preview',snapshot=snapshot))


def validate(run, checkpoint_path=None):
    from .projects import integration
    project = dict(run['project'],path=run['snapshot']['path'])
    profile = run['schema'].get('integration') or integration(project['path'],project.get('integration'))
    checkpoint = Path(checkpoint_path) if checkpoint_path else Path(run['remote_path'])/profile.get('resume',{}).get('checkpoint','latest.pt')
    value = verify(profile,project,checkpoint,dict(phase='validate',training=run['parameters']['training'],
                   runtime=dict(gpu_count=run['gpu_count']),snapshot=run['snapshot']))
    if value['runtime']['gpu_count'] != run['gpu_count']:
        raise AgentError('CHECKPOINT_INCOMPLETE','严格续跑不能改变 GPU 数量')
    saved = value['training']
    changed = [key for key,value in run['parameters']['training'].items() if key not in saved or saved[key] != value]
    if changed:
        raise AgentError('CHECKPOINT_INCOMPLETE','训练参数与 checkpoint 不一致',changed)
    return value


def pin(source, destination):
    path = Path(source['path'])
    if checkpoint_identity(path) != source['identity']:
        raise AgentError('CHECKPOINT_CHANGED', 'checkpoint 已更新，请从历史重新载入续跑')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(path, destination)
        if checkpoint_identity(path) != source['identity']:
            raise AgentError('CHECKPOINT_CHANGED', '复制时 checkpoint 已更新，请重新载入')
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return str(destination)


def validate_resume_metadata(checkpoint,expected):
    errors=[]
    for key in ('model_state','optimizer_state','rng_states','train_sample_cursors'):
        if key not in checkpoint:errors.append('缺少 '+key)
    if expected.get('requires_scaler') and not checkpoint.get('grad_scaler_state'):errors.append('缺少 scaler_state')
    for key in ('rng_states','train_sample_cursors'):
        if key in checkpoint and len(checkpoint[key])!=expected['world_size']:errors.append(key+' 的 rank 数量不匹配')
    for key in ('world_size','manifest_fingerprint','args','model_config'):
        if key in expected and checkpoint.get(key)!=expected[key]:errors.append(key+' 不匹配')
    if checkpoint.get('allow_nonexact_resume') or checkpoint.get('allow_world_size_change'):errors.append('不允许非严格续跑')
    return errors
