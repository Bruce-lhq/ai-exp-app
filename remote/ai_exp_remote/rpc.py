import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from . import files,projects
from .launcher import build_launch
from .runtime import ensure_daemon
from .scheduler import choose_gpus,gpu_status
from .snapshot import create_snapshot
from .state import AgentError,Store,emit

ROOT=Path(os.environ.get('AI_EXP_REMOTE_ROOT','/your_exp/ai_exp_app/state'))
READERS={'list_directory':files.list_directory,'inspect_project':projects.inspect_project,'read_schema':projects.read_schema,'inspect_files':files.inspect_files,'read_file':files.read_file,'file_manifest':files.file_manifest,'read_file_chunk':files.read_file_chunk}
MUTATIONS={'submit','stop','resume','queue_order','queue_pause','queue_resume','queue_remove','delete_preview','delete_confirm'}

def handle(request,root=None,start_daemon=True):
    if request.get('version')!=1:raise AgentError('PROTOCOL_VERSION','不支持的协议版本')
    op=request['operation'];p=request.get('payload',{})
    if op in READERS:return READERS[op](p)
    root=Path(root or ROOT);store=Store(root)
    if op=='gpus':return gpu_status()
    if op in MUTATIONS and (root.parent/'read-only').exists():raise AgentError('READ_ONLY','远端组件尚未启用实验运行')
    digest=hashlib.sha256(json.dumps({'operation':op,'payload':p},sort_keys=True,allow_nan=False).encode()).hexdigest()
    with store.transaction() as state:
        request_id=request.get('request_id')
        if not request_id:raise AgentError('REQUEST_ID','缺少请求 ID')
        if op in MUTATIONS and request_id in state['requests']:
            previous=state['requests'][request_id]
            if previous['digest']!=digest:raise AgentError('REQUEST_CONFLICT','同一请求 ID 的内容不同')
            return previous['result']
        if op=='status':
            result={k:state[k] for k in ('revision','paused','queue','events')};result['runs']=list(state['runs'].values())
            try:result['gpus']=gpu_status()
            except Exception as exc:result['gpus']=[];result['gpu_error']=str(exc)
        elif op=='events':result=[e for e in state['events'] if e['seq']>p.get('after',0)]
        elif op=='request_status':result=state['requests'].get(p['request_id'])
        elif op=='read_log':
            run=state['runs'][p['run_id']]
            name=p.get('name','train.log');path=run['remote_path']
            if name=='launch.log' or not (Path(path)/name).exists():
                path=run.get('attempt_dir',path);name='launch.log'
            result=files.read_file(dict(path=path,name=name,offset=p.get('offset',0),limit=p.get('limit',65536)))
        elif op=='submit':
            run_id=p['run_id']
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',run_id):raise AgentError('RUN_ID','非法实验 ID')
            if run_id in state['runs']:raise AgentError('RUN_EXISTS','实验已存在')
            count=p['parameters']['runtime']['gpu_count'];choose_gpus(count,[])
            check_start(state,p.get('mode','queue'),count)
            project=p['project'];source=project.get('path') or project.get('remote_path')
            snapshot=create_snapshot(Path(source),root.parent/'snapshots'/run_id,p.get('code') or {'kind':'working_tree'},project.get('exclusions',[]))
            schema=projects.read_schema(dict(path=snapshot['path'],code={'kind':'working_tree'},python=project.get('python')))
            runs_root=Path(project.get('runs_root','/your_exp/runs'))
            if not runs_root.is_absolute():raise AgentError('INVALID_PATH','实验根目录必须是绝对路径')
            output=runs_root/('ai-exp-'+run_id);output.parent.mkdir(parents=True,exist_ok=True)
            if output.exists():raise AgentError('RUN_PATH_EXISTS','实验输出目录已存在')
            run=dict(p,id=run_id,status='queued',gpu_count=count,schema=schema,snapshot=snapshot,remote_path=str(output),code=p.get('code') or {'kind':'working_tree'},created_at=time.time())
            # Parser-level validation in selected environment, never run main or create a model.
            spec=build_launch(project,run,list(range(count)))
            run['resolved_parameters']=validate_launch(spec)
            data_meta=Path(project.get('data_root','/your_exp/data/fineweb_edu_gpt2_100B'))/'meta.json'
            run['data_meta_hash']=hashlib.sha256(data_meta.read_bytes()).hexdigest() if data_meta.exists() else None
            state['runs'][run_id]=run;state['queue'].append(run_id);emit(state,'accepted',run)
            result=run
        elif op=='queue_order':
            ids=p['run_ids']
            if p['revision']!=state['revision']:raise AgentError('REVISION_CONFLICT','队列已变化，请刷新')
            if len(ids)!=len(set(ids)) or set(ids)!=set(state['queue']):raise AgentError('QUEUE_ORDER','必须提供所有等待实验且不重复')
            state['queue']=ids;result={'queue':ids}
        elif op=='queue_remove':
            identity=p['run_id']
            if identity not in state['queue']:raise AgentError('QUEUE_STATE','实验已启动或不在等待队列中')
            state['queue'].remove(identity);run=state['runs'][identity];run['status']='stopped';emit(state,'stopped',run);result=run
        elif op in ('delete_preview','delete_confirm'):
            from . import deletion
            result=deletion.preview(p,state) if op=='delete_preview' else deletion.confirm(p,state)
        elif op in ('queue_pause','queue_resume'):
            state['paused']=op=='queue_pause';emit(state,'queue_paused' if state['paused'] else 'queue_resumed');result={'paused':state['paused']}
        elif op=='stop':
            if p.get('confirmed') is not True:raise AgentError('CONFIRM_REQUIRED','停止实验需要确认')
            run=state['runs'][p['run_id']]
            if run['status'] in ('queued','running','starting'):
                if p.get('pause_queue'):state['paused']=True;emit(state,'queue_paused',run)
                run['stop_requested']=time.time();emit(state,'stop_requested',run)
                if run['status']=='queued':state['queue'].remove(run['run_id']);run['status']='stopped';emit(state,'stopped',run)
                else:run['status']='stopping'
            result=run
        elif op=='resume':
            run=state['runs'][p['run_id']]
            if run['status'] not in ('failed','stopped'):raise AgentError('RESUME_STATE','仅允许续跑停止或失败的实验')
            check_start(state,p.get('mode','queue'),run['gpu_count'])
            validate_checkpoint(run)
            run['resume_path']=str(Path(run['remote_path'])/'latest.pt');run['status']='queued';run['stop_requested']=None
            state['queue'].append(run['run_id']);emit(state,'accepted',run,{'resume':True});result=run
        else:raise AgentError('UNKNOWN_OPERATION','未知操作')
        if op in MUTATIONS:state['requests'][request_id]={'digest':digest,'result':json.loads(json.dumps(result))}
    if start_daemon and (op in MUTATIONS or op=='status') and not (root.parent/'read-only').exists():ensure_daemon(root)
    return result

def check_start(state,mode,count):
    if mode not in ('queue','start'):raise AgentError('MODE','无效提交方式')
    if mode=='start':
        if state['paused']:raise AgentError('QUEUE_PAUSED','队列已暂停')
        if state['queue']:raise AgentError('QUEUE_AHEAD','已有等待实验，请加入队列')
        reserved={g for r in state['runs'].values() if r['status'] in ('starting','running','stopping') for g in r.get('gpu_ids',[])}
        if choose_gpus(count,[d['index'] for d in gpu_status() if d['available'] and d['index'] not in reserved]) is None:raise AgentError('RESOURCE_UNAVAILABLE','GPU 资源不足，请加入队列')

VALIDATE=r'''
import contextlib,importlib.util,sys,json
sys.path.insert(0,sys.argv[1])
with contextlib.redirect_stdout(sys.stderr):
 s=importlib.util.spec_from_file_location('ai_exp_train',sys.argv[1]+'/train.py');m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
 args=m.build_parser().parse_args(json.loads(sys.argv[2]))
 if hasattr(m,'_resolve_backbone_defaults'):m._resolve_backbone_defaults(args)
 if hasattr(m,'validate_args'):m.validate_args(args)
 if hasattr(m,'resolved_model_config'):
  config=m.resolved_model_config(args,50257)
  if getattr(args,'ca_lambda',None)==0 and getattr(config,'ca_lambda',0)!=0:raise ValueError('源码 ca_lambda=0 与模型配置不一致')
 print(json.dumps(vars(args),default=str))
'''
def validate_launch(spec):
    from .parser_probe import resolve
    try:return resolve(spec['cwd'],spec['argv'][6:])
    except (Exception,SystemExit) as exc:raise AgentError('PARAMETER_VALIDATION','源码参数校验失败',str(exc)) from exc

CHECKPOINT=r'''
import torch,sys,json,importlib.util,contextlib
c=torch.load(sys.argv[1],map_location='cpu',weights_only=False)
n=int(sys.argv[2]);required=['model_state','optimizer_state','rng_states','train_sample_cursors','tokens_seen','optimizer_step','args','model_config','data_config']
errors=['缺少 '+k for k in required if k not in c]
if c.get('world_size')!=n:errors.append('GPU 数不匹配')
for k in ['rng_states','train_sample_cursors']:
 if len(c.get(k,[]))!=n:errors.append(k+' 缺少 rank 状态')
if c.get('args',{}).get('amp_dtype')=='float16' and not c.get('grad_scaler_state'):errors.append('缺少 grad_scaler_state')
with contextlib.redirect_stdout(sys.stderr):
 sys.path.insert(0,sys.argv[3]);s=importlib.util.spec_from_file_location('ai_exp_resume_train',sys.argv[3]+'/train.py');m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
 a=m.build_parser().parse_args(json.loads(sys.argv[4]))
 if hasattr(m,'_resolve_backbone_defaults'):m._resolve_backbone_defaults(a)
 if hasattr(m,'_resume_setting_differences'):
  if m._resume_setting_differences(c,a):errors.append('训练参数与 checkpoint 不一致')
 if hasattr(m,'_validate_resume_config') and hasattr(m,'resolved_model_config'):
  m._validate_resume_config(c,m.resolved_model_config(a,c.get('model_config',{}).get('vocab_size',50257)))
print(json.dumps({'errors':errors,'tokens_seen':c.get('tokens_seen')}))
'''
def validate_checkpoint(run):
    path=Path(run['remote_path'])/'latest.pt'
    if not path.is_file():raise AgentError('CHECKPOINT_MISSING','没有最近完整 checkpoint，不能严格续跑')
    from .snapshot import manifest
    if manifest(Path(run['snapshot']['path']),[])!=run['snapshot']['manifest']:raise AgentError('CODE_CHANGED','原代码快照已改变，禁止续跑')
    data_meta=Path(run['project'].get('data_root','/your_exp/data/fineweb_edu_gpt2_100B'))/'meta.json'
    if run.get('data_meta_hash') is None or not data_meta.exists() or hashlib.sha256(data_meta.read_bytes()).hexdigest()!=run['data_meta_hash']:raise AgentError('DATA_CHANGED','无法确认原始数据身份，禁止续跑')
    spec=build_launch(run['project'],run,list(range(run['gpu_count'])))
    result=subprocess.run([run['project'].get('python') or projects.PYTHON,'-c',CHECKPOINT,str(path),str(run['gpu_count']),spec['cwd'],json.dumps(spec['argv'][6:])],capture_output=True,text=True,timeout=90,env=dict(os.environ,CUDA_VISIBLE_DEVICES=''))
    if result.returncode:raise AgentError('CHECKPOINT_INVALID','checkpoint 读取失败',result.stderr[-2000:])
    value=json.loads(result.stdout)
    if value['errors']:raise AgentError('CHECKPOINT_INCOMPLETE','checkpoint 无法完整续跑',value['errors'])
    run['resume_tokens']=value['tokens_seen']

def main():
    request={}
    try:
        request=json.load(sys.stdin);result=handle(request)
        response=dict(version=1,request_id=request.get('request_id'),ok=True,result=result,error=None)
    except Exception as exc:
        response=dict(version=1,request_id=request.get('request_id'),ok=False,result=None,error=dict(code=getattr(exc,'code','REMOTE_ERROR'),message=str(exc),details=getattr(exc,'details',None)))
    print(json.dumps(response,ensure_ascii=False,allow_nan=False))
