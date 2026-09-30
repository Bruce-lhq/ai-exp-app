"""Real CPU training commands exercise the same integration used by remote jobs."""
import json
from pathlib import Path
import subprocess
import sys
import pytest
from ai_exp_remote.launcher import build_launch
from ai_exp_remote.projects import read_schema, validate_profile
from ai_exp_remote.resume import preview, validate
from ai_exp_remote.rpc import handle
from ai_exp_remote.state import AgentError


def make_run(tmp_path, profile, training):
    source = tmp_path/'project'
    source.mkdir()
    (source/'workbench.project.json').write_text(json.dumps(profile))
    schema = read_schema({'path':str(source)})
    run = dict(run_id='cpu',schema=schema,project={'path':str(source),'python':sys.executable},
               parameters={'training':training,'runtime':{'gpu_count':1}},gpu_count=1,
               snapshot={'path':str(source)},remote_path=str(tmp_path/'output'))
    return source, run


def test_arbitrary_entrypoint_launches_cpu_and_preserves_string_arguments(tmp_path):
    source, run = make_run(tmp_path,dict(version=1,command=['{python}','experiment.py','--output','{run_dir}'],
        parameters=[dict(name='message',type='string',flag='--message',default='hello')],environment={'CUSTOM':'present'}),
        {'message':'hello $(touch hacked) with spaces'})
    (source/'experiment.py').write_text('import argparse,json,os\nfrom pathlib import Path\np=argparse.ArgumentParser()\np.add_argument("--output")\np.add_argument("--message")\na=p.parse_args()\nout=Path(a.output);out.mkdir()\n(out/"result.json").write_text(json.dumps({"message":a.message,"custom":os.environ["CUSTOM"]}))\nprint("ordinary completion")\n')
    spec = build_launch(run['project'],run,[3])
    result = subprocess.run(spec['argv'],cwd=spec['cwd'],env=spec['env'],capture_output=True,text=True)
    assert result.returncode == 0
    value = json.loads((Path(run['remote_path'])/'result.json').read_text())
    assert value['message'] == run['parameters']['training']['message']
    assert value['custom'] == 'present'
    assert 'torch.distributed.run' not in spec['argv']
    assert not (source/'hacked').exists()


def test_json_config_program_has_no_invented_flags(tmp_path):
    source, run = make_run(tmp_path,dict(version=1,parameter_style='json',command=['{python}','job.py','{parameter_file}','{run_dir}'],
        parameters=[dict(name='iterations',type='integer',default=2)]),{'iterations':2})
    (source/'job.py').write_text('import json,sys\nfrom pathlib import Path\nconfig=json.loads(Path(sys.argv[1]).read_text());out=Path(sys.argv[2]);out.mkdir()\n(out/"metrics.jsonl").write_text(json.dumps({"step":config["iterations"],"accuracy":0.75})+"\\n")\n')
    spec = build_launch(run['project'],run,[0])
    result = subprocess.run(spec['argv'],cwd=spec['cwd'],env=spec['env'],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    assert '--iterations' not in spec['argv']
    assert json.loads((Path(run['remote_path'])/'metrics.jsonl').read_text())['accuracy'] == .75


def test_argparse_discovery_custom_entrypoint_never_imports_training(tmp_path):
    (tmp_path/'job.py').write_text('import unavailable_training_framework\nimport argparse\ndef options():\n p=argparse.ArgumentParser()\n p.add_argument("--epochs",type=int,default=3)\n return p\nraise RuntimeError("must not run")\n')
    (tmp_path/'workbench.project.json').write_text(json.dumps(dict(version=1,entrypoint='job.py',parser_function='options',command=['{python}','job.py'])))
    schema = read_schema({'path':str(tmp_path)})
    assert schema['fields'][0]['default'] == 3


def test_strict_resume_requires_declared_full_state_verifier(tmp_path):
    source, run = make_run(tmp_path,dict(version=1,command=['{python}','job.py'],parameters=[]),{})
    with pytest.raises(AgentError,match='未配置严格续跑'):
        preview({'path':str(tmp_path),'project':run['project']})


def test_strict_resume_hook_checks_full_state_parameters_and_card_count(tmp_path):
    profile = dict(version=1,command=['{python}','job.py'],parameters=[dict(name='lr',type='number',default=.1)],
                   resume=dict(flag='--restore',checkpoint='state.json',validator=['{python}','verify.py','{checkpoint}','{request}']))
    source, run = make_run(tmp_path,profile,{'lr':.1})
    (source/'verify.py').write_text('import json,sys\nfrom pathlib import Path\nc=json.loads(Path(sys.argv[1]).read_text());request=json.loads(Path(sys.argv[2]).read_text())\nassert request["phase"] in ("preview","validate")\nprint(json.dumps(c))\n')
    out = Path(run['remote_path']);out.mkdir()
    state = dict(strict=True,compatible=True,verified_state={key:True for key in ['model','optimizer','scheduler','rng','data_position']},
                 training={'lr':.1},runtime={'gpu_count':1},tokens_seen=123)
    checkpoint = out/'state.json';checkpoint.write_text(json.dumps(state))
    assert preview({'path':str(out),'project':run['project']})['training'] == {'lr':.1}
    assert validate(run)['tokens_seen'] == 123
    run['parameters']['training']['lr'] = .2
    with pytest.raises(AgentError,match='训练参数'):
        validate(run)
    run['parameters']['training']['lr'] = .1
    state['verified_state']['optimizer'] = False;checkpoint.write_text(json.dumps(state))
    with pytest.raises(AgentError,match='无法严格续跑'):
        validate(run)


@pytest.mark.parametrize('profile',[
    [], {'command':'python job.py'}, {'command':['{unknown}']},
    {'command':['job'],'parameters':[{'name':'x','type':'integer','default':'wrong'}]},
    {'command':['job'],'environment':{'bad=name':'value'}},
    {'command':['job'],'parameters':[{'name':'x','flags':'--x','default':1,'type':'integer'}]},
])
def test_invalid_profiles_rejected_before_queue(profile):
    with pytest.raises((AgentError,ValueError)):
        validate_profile(profile)


def test_monitoring_works_without_optional_terminal_wrappers(tmp_path,monkeypatch):
    monkeypatch.setattr('ai_exp_remote.rpc.shutil.which',lambda name:None)
    value=handle({'version':1,'request_id':'status','operation':'external_status','payload':{}},tmp_path,False)
    assert value['runs']==[]


def test_submission_persists_declarative_command_in_immutable_snapshot(tmp_path):
    project = tmp_path/'code';project.mkdir()
    profile = dict(version=1,command=['{python}','custom_job.py','--result','{run_dir}'],
                   parameters=[dict(name='run_dir',type='string',default='ordinary-user-param',flag='--label')])
    (project/'workbench.project.json').write_text(json.dumps(profile))
    (project/'custom_job.py').write_text('print("not executed by submission")\n')
    payload = dict(run_id='one',project={'path':str(project),'python':sys.executable,'runs_root':str(tmp_path/'runs')},
                   parameters={'training':{'run_dir':'display $(not a shell)'},'runtime':{'gpu_count':1}})
    run = handle({'version':1,'request_id':'submit','operation':'submit','payload':payload},tmp_path/'state',False)
    assert run['status']=='queued'
    assert run['resolved_parameters']=={'run_dir':'display $(not a shell)'}
    profile['command'] = ['must-not-be-used']
    (project/'workbench.project.json').write_text(json.dumps(profile))
    spec = build_launch(run['project'],run,[0])
    assert spec['argv'][1]=='custom_job.py'
    assert spec['argv'][-1]=='display $(not a shell)'


def test_completion_creates_missing_standard_history_files(tmp_path,monkeypatch):
    from ai_exp_remote import runtime
    from ai_exp_remote.state import Store,atomic_json
    _,run = make_run(tmp_path,dict(version=1,command=['{python}','job.py'],parameters=[]),{})
    run.update(id='cpu',project_id='p',status='running',attempt_id='a',attempt_started_at=0,
               attempt_dir=str(tmp_path/'state/attempts/a'))
    store=Store(tmp_path/'state')
    folder=Path(run['attempt_dir']);folder.mkdir(parents=True)
    (folder/'launch.log').write_text('Successful arbitrary CLI output\n')
    atomic_json(folder/'exit.json',{'exit_code':0})
    with store.transaction() as state:state['runs']['cpu']=run
    monkeypatch.setattr(runtime,'gpu_status',lambda:[])
    runtime.tick(store)
    output=Path(run['remote_path'])
    assert json.loads((output/'run.json').read_text())['status']=='completed'
    assert json.loads((output/'args.json').read_text())=={}
    assert (output/'train.log').read_text()=='Successful arbitrary CLI output\n'


def test_existing_cpu_training_strict_resume_matches_uninterrupted_result(tmp_path):
    """Project-owned hooks verify an unfamiliar checkpoint format and real continuation."""
    profile=dict(version=1,command=['{python}','job.py','--output','{run_dir}','--until','10'],
                 parameters=[dict(name='lr',type='number',default=.05)],
                 resume=dict(flag='--restore',checkpoint='state.json',validator=['{python}','verify.py','{checkpoint}','{request}']))
    source,run=make_run(tmp_path,profile,{'lr':.05})
    (source/'job.py').write_text('''import argparse,hashlib,json,random
from pathlib import Path
DATA_SHA=hashlib.sha256(b"synthetic-dataset-v1").hexdigest()
def tuples(value):
 return tuple(tuples(x) for x in value) if isinstance(value,list) else value
def main():
 p=argparse.ArgumentParser();p.add_argument("--output");p.add_argument("--until",type=int);p.add_argument("--lr",type=float);p.add_argument("--restore");a=p.parse_args()
 rng=random.Random(17)
 state={"model":.75,"optimizer":0.,"scheduler":0,"data_position":0}
 if a.restore:
  state=json.loads(Path(a.restore).read_text());rng.setstate(tuples(state["rng"]))
 for step in range(state["scheduler"],a.until):
  gradient=state["model"]+rng.random()+(state["data_position"]%3)*.01
  state["optimizer"]=.9*state["optimizer"]+gradient
  state["model"]-=a.lr/(1+step/10)*state["optimizer"]
  state["scheduler"]=step+1;state["data_position"]+=1
 state.update(rng=rng.getstate(),training={"lr":a.lr},world_size=1,code_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),data_sha=DATA_SHA)
 out=Path(a.output);out.mkdir(exist_ok=True);(out/"state.json").write_text(json.dumps(state))
if __name__=="__main__":main()
''')
    (source/'verify.py').write_text('''import hashlib,json,sys
from pathlib import Path
from job import DATA_SHA
c=json.loads(Path(sys.argv[1]).read_text());r=json.loads(Path(sys.argv[2]).read_text())
keys=["model","optimizer","scheduler","rng","data_position"]
valid={k:k in c for k in keys}
errors=[]
if c.get("code_sha")!=hashlib.sha256(Path("job.py").read_bytes()).hexdigest():errors.append("code changed")
if c.get("data_sha")!=DATA_SHA:errors.append("data changed")
if r["phase"]=="validate" and r["training"]!=c["training"]:errors.append("training changed")
print(json.dumps(dict(strict=True,compatible=not errors,errors=errors,verified_state=valid,training=c["training"],runtime={"gpu_count":c["world_size"]},tokens_seen=c["data_position"])))
''')
    def execute(output,resume=None,until=10):
        run['remote_path']=str(output)
        if resume:run['resume_path']=str(resume)
        else:run.pop('resume_path',None)
        spec=build_launch(run['project'],run,[0])
        spec['argv'][spec['argv'].index('--until')+1]=str(until)
        result=subprocess.run(spec['argv'],cwd=spec['cwd'],env=spec['env'],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        return json.loads((output/'state.json').read_text())
    uninterrupted=execute(tmp_path/'uninterrupted')
    execute(tmp_path/'partial',until=6)
    checkpoint=tmp_path/'partial/state.json'
    run['remote_path']=str(tmp_path/'partial')
    assert validate(run)['tokens_seen']==6
    restored=execute(tmp_path/'restored',resume=checkpoint)
    assert restored==uninterrupted
    value=json.loads(checkpoint.read_text());value['data_sha']='wrong dataset';checkpoint.write_text(json.dumps(value))
    with pytest.raises(AgentError,match='无法严格续跑'):
        validate(run,checkpoint)


def test_mixed_string_choice_or_numeric_value_in_explicit_profile(tmp_path):
    source, run = make_run(tmp_path, dict(command=['job'], parameters=[
        dict(name='width', type='number_or_choice', default='auto', choices=['auto', 'small'])]), {'width': 16000})
    spec = build_launch(run['project'], run, [0])
    assert spec['argv'][-2:] == ['--width', '16000']
    run['parameters']['training']['width'] = 'small'
    assert build_launch(run['project'], run, [0])['argv'][-1] == 'small'
