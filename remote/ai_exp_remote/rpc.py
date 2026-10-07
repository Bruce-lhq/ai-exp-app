import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import shutil
import sys
import time
import uuid
from . import files,projects
from .launcher import build_launch
from .runtime import ensure_daemon
from .scheduler import choose_gpus,gpu_status
from .snapshot import create_snapshot
from .state import AgentError,Store,emit
from .config import settings

ROOT=Path(os.environ.get('AI_EXP_REMOTE_ROOT',settings()['remote_state_dir']))
READERS={'list_directory':files.list_directory,'inspect_project':projects.inspect_project,'read_schema':projects.read_schema,'inspect_files':files.inspect_files,'read_file':files.read_file,'file_manifest':files.file_manifest,'read_file_chunk':files.read_file_chunk,'sync_files':files.sync_files}
MUTATIONS={'submit','stop','pause','resume','queue_order','queue_pause','queue_resume','queue_remove','delete_preview','delete_confirm','remove_external'}

def external_runs(alias='gpu'):
    if shutil.which('gpu-groups') is None:
        return []
    completed = subprocess.run(['gpu-groups', 'list', '--all'], text=True, capture_output=True, timeout=15)
    if completed.returncode:
        raise AgentError('EXTERNAL_STATUS', '无法读取终端 GPU 分组', completed.stderr[-2000:])
    dashboard = subprocess.run(['dashboard'], text=True, capture_output=True, timeout=15) if shutil.which('dashboard') else subprocess.CompletedProcess(['dashboard'],0,'','')
    details = {}
    for line in dashboard.stdout.splitlines() if dashboard.returncode == 0 else []:
        parts = [x.strip() for x in line.split('|')]
        if len(parts) >= 7 and parts[1] not in {'GPU', '---'}:
            details[parts[5]] = {'dashboard_status': parts[2], 'progress': parts[3], 'remaining': parts[4], 'queue_name': parts[6]}
    items=[]
    for line in completed.stdout.splitlines():
        parts=line.split('\t')
        if len(parts) < 3 or not parts[0].isdigit(): continue
        group, gpus, path = parts[0], parts[1], parts[2]
        items.append(dict(id='external-'+hashlib.sha1(path.encode()).hexdigest()[:16], display_name=Path(path).name,
                          status='external_running', external=True, group=group,
                          gpu_ids=[int(x) for x in gpus.split(',') if x.isdigit()], remote_path=path,
                          ssh_alias=alias, **details.get(Path(path).name, {})))
    return items

def handle(request,root=None,start_daemon=True):
    if request.get('version')!=1:raise AgentError('PROTOCOL_VERSION','不支持的协议版本')
    op=request['operation'];p=request.get('payload',{})
    if op == 'checkpoint_preview':
        from .resume import preview
        return preview(p)
    if op in READERS:return READERS[op](p)
    if op == 'metric_series': return files.metric_series(p)
    if op == 'read_log' and p.get('path'):
        return files.read_file(dict(path=p['path'], name=p.get('name', 'train.log'),
                                    offset=p.get('offset', 0), limit=p.get('limit', 65536)))
    if op == 'external_status':
        return {'runs':external_runs(p.get('ssh_alias','gpu')), 'source':'gpu-groups'}
    root=Path(root or ROOT);store=Store(root)
    if op in ('adopt_external','pause_external','remove_external'):
        from . import adoption
        with store.transaction() as state:
            records = state.setdefault('adoptions', {})
            identity = p.get('run_id')
            record = records.get(identity)
            if op == 'adopt_external':
                run = next((r for r in external_runs() if r['id'] == identity), None)
                if not run:raise AgentError('RUN_NOT_FOUND','实验不在终端 GPU 分组中')
                record = dict(adoption.discover(run['remote_path']), id=identity)
                records[identity] = record
            elif op == 'remove_external':
                # Forget the adoption record only; run data and checkpoints stay on disk.
                if not record:raise AgentError('NOT_ADOPTED','没有此实验的接管记录')
                if record['status'] not in ('paused','external_exited'):raise AgentError('REMOVE_STATE','仅允许移除已暂停或已退出的接管实验')
                if p.get('confirmed') is not True:raise AgentError('CONFIRM_REQUIRED','移除记录需要确认')
                records.pop(identity,None)
                return {'id': identity,'removed': True}
            else:
                if p.get('confirmed') is not True:raise AgentError('CONFIRM_REQUIRED','暂停实验需要确认')
                if not record:raise AgentError('NOT_ADOPTED','请先接管实验')
                if record['status'] not in ('stopping','paused'):
                    adoption.pause(record)
            return {'id': identity, 'adopted': True, 'status': record['status']}
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
            result['gpus'] = []
        elif op=='events':result=[e for e in state['events'] if e['seq']>p.get('after',0)]
        elif op=='request_status':result=state['requests'].get(p['request_id'])
        elif op=='read_log':
            run=state['runs'].get(p.get('run_id'))
            if not run and p.get('path'):
                result=files.read_file(dict(path=p['path'],name=p.get('name','train.log'),offset=p.get('offset',0),limit=p.get('limit',65536)))
                return result
            if not run: raise AgentError('RUN_NOT_FOUND','实验不在工作台队列中')
            name=p.get('name','train.log');path=run['remote_path']
            failed_log = run.get('status') == 'failed' and run.get('attempt_dir') and (Path(run['attempt_dir'])/'launch.log').exists()
            if name=='launch.log' or failed_log or not (Path(path)/name).exists():
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
            schema=json_safe(projects.read_schema(dict(path=snapshot['path'],code={'kind':'working_tree'},python=project.get('python'),integration=project.get('integration'))))
            runs_root=Path(project.get('runs_root',settings()['remote_runs_root']))
            if not runs_root.is_absolute():raise AgentError('INVALID_PATH','实验根目录必须是绝对路径')
            output=runs_root/run_id;output.parent.mkdir(parents=True,exist_ok=True)
            if output.exists():raise AgentError('RUN_PATH_EXISTS','实验输出目录已存在')
            run=dict(p,id=run_id,status='queued',gpu_count=count,schema=schema,snapshot=snapshot,remote_path=str(output),code=p.get('code') or {'kind':'working_tree'},created_at=time.time())
            # Parser-level validation in selected environment, never run main or create a model.
            spec=build_launch(project,run,list(range(count)))
            run['resolved_parameters']=json_safe(validate_launch(spec))
            if p.get('resume'):
                from .resume import pin
                suffix=''.join(Path(p['resume']['path']).suffixes) or '.checkpoint'
                run['resume_path']=pin(p['resume'],root.parent/'checkpoints'/(run_id+suffix))
                try:
                    validate_checkpoint(run,run['resume_path'])
                except Exception:
                    Path(run['resume_path']).unlink(missing_ok=True)
                    raise
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
        elif op in ('stop','pause'):
            if p.get('confirmed') is not True:raise AgentError('CONFIRM_REQUIRED','停止实验需要确认')
            run=state['runs'].get(p['run_id'])
            if not run:raise AgentError('RUN_NOT_FOUND','此实验未由工作台管理，不能暂停或停止')
            if op=='pause' and run['status'] not in ('running','starting','stopping','paused'):
                raise AgentError('PAUSE_STATE','仅允许暂停正在运行的实验')
            if run['status'] in ('queued','running','starting'):
                run['stop_reason']='pause' if op=='pause' else 'stop'
                if p.get('pause_queue'):state['paused']=True;emit(state,'queue_paused',run)
                run['stop_requested']=time.time();emit(state,'stop_requested',run)
                if run['status']=='queued':state['queue'].remove(run['run_id']);run['status']='stopped';emit(state,'stopped',run)
                else:run['status']='stopping'
            result=run
        elif op=='resume':
            run=state['runs'][p['run_id']]
            if run['status'] not in ('failed','stopped','paused'):raise AgentError('RESUME_STATE','仅允许续跑已暂停、停止或失败的实验')
            check_start(state,p.get('mode','queue'),run['gpu_count'])
            validate_checkpoint(run)
            run['resume_path']=str(Path(run['remote_path'])/run['schema'].get('integration',{}).get('resume',{}).get('checkpoint','latest.pt'));run['status']='queued';run['stop_requested']=None;run.pop('stop_reason',None)
            state['queue'].append(run['run_id']);emit(state,'accepted',run,{'resume':True});result=run
        else:raise AgentError('UNKNOWN_OPERATION','未知操作')
        if op in MUTATIONS:state['requests'][request_id]={'digest':digest,'result':json.loads(json.dumps(result))}
    if op == 'status':
        try: result['external_runs'] = external_runs(p.get('ssh_alias', 'gpu'))
        except Exception as exc: result['external_runs'] = []; result['external_error'] = str(exc)
        from . import adoption
        with store.transaction() as state:
            records = state.get('adoptions', {})
            table = adoption.processes() if records else {}
            for record in records.values():
                adoption.observe(record, table)
                run = next((r for r in result['external_runs'] if r['id'] == record['id']), None)
                if run is None:
                    run = dict(id=record['id'], external=True, remote_path=record['remote_path'],
                               display_name=Path(record['remote_path']).name)
                    result['external_runs'].append(run)
                if not adoption.same(record['launcher'], table.get(record['launcher']['pid'])):
                    try:
                        adoption.discover(record['remote_path'], table)
                    except AgentError:
                        pass
                    else:
                        run.update(status='external_running', adopted=False)
                        continue
                run.update(status=record['status'], adopted=True, stop_tokens=record.get('stop_tokens'))
                # Adopted runs whose manifest row was replaced get no dashboard
                # details; compute progress from their own metrics like managed runs.
                if 'progress' not in run:
                    try: run.update(files.run_progress(run))
                    except Exception: pass
        # Registered platform runs also appear in the gpu-groups manifest; keep only
        # genuinely terminal-managed runs so the UI does not list them twice.
        managed = {r.get('remote_path','').rstrip('/') for r in result['runs']}
        result['external_runs'] = [r for r in result['external_runs'] if r.get('remote_path','').rstrip('/') not in managed]
        for r in result['runs']:
            try: r.update(files.run_progress(r))
            except Exception: pass
        if p.get('include_gpus', True):
            try: result['gpus'] = gpu_status()
            except Exception as exc: result['gpu_error'] = str(exc)
    if start_daemon and (op in MUTATIONS or op=='status') and not (root.parent/'read-only').exists():ensure_daemon(root)
    return result

def check_start(state,mode,count):
    if mode not in ('queue','start'):raise AgentError('MODE','无效提交方式')
    if mode=='start':
        if state['paused']:raise AgentError('QUEUE_PAUSED','队列已暂停')
        if state['queue']:raise AgentError('QUEUE_AHEAD','已有等待实验，请加入队列')
        reserved={g for r in state['runs'].values() if r['status'] in ('starting','running','stopping') for g in r.get('gpu_ids',[])}
        if choose_gpus(count,[d['index'] for d in gpu_status() if d['available'] and d['index'] not in reserved]) is None:raise AgentError('RESOURCE_UNAVAILABLE','GPU 资源不足，请加入队列')

def validate_launch(spec):
    profile = spec['integration']
    if 'parameters' in profile:
        return dict(spec['training'])
    from .parser_probe import resolve
    try:
        argv=spec['argv']
        arguments=argv[argv.index(profile['entrypoint'])+1:] if profile['entrypoint'] in argv else spec['parameter_argv']
        return resolve(spec['cwd'], arguments, profile['entrypoint'], profile['parser_function'])
    except (Exception, SystemExit) as exc:
        raise AgentError('PARAMETER_VALIDATION', '项目参数校验失败', str(exc)) from exc

def json_safe(value):
    """Keep the line protocol valid when argparse or metrics contain NaN/Infinity."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict): return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [json_safe(v) for v in value]
    return value
def validate_checkpoint(run, checkpoint_path=None):
    from .resume import validate
    from .snapshot import manifest
    if manifest(Path(run['snapshot']['path']),[]) != run['snapshot']['manifest']:
        raise AgentError('CODE_CHANGED','原代码快照已改变，禁止续跑')
    value = validate(run, checkpoint_path)
    run['resume_tokens'] = value.get('tokens_seen')

def main():
    request={}
    try:
        request=json.load(sys.stdin);result=handle(request)
        response=dict(version=1,request_id=request.get('request_id'),ok=True,result=json_safe(result),error=None)
    except Exception as exc:
        response=dict(version=1,request_id=request.get('request_id'),ok=False,result=None,error=dict(code=getattr(exc,'code','REMOTE_ERROR'),message=str(exc),details=getattr(exc,'details',None)))
    print(json.dumps(json_safe(response),ensure_ascii=False,allow_nan=False))
