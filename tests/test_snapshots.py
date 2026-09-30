from pathlib import Path
import pytest
from ai_exp_remote.snapshot import create_snapshot
from ai_exp_remote.state import AgentError

def test_plain_directory_freezes_code(tmp_path):
    source=tmp_path/'src';source.mkdir();(source/'train.py').write_text('one')
    create_snapshot(source,tmp_path/'snap',{'kind':'working_tree'},[])
    (source/'train.py').write_text('two')
    assert (tmp_path/'snap/train.py').read_text()=='one'

def test_external_link_rejected(tmp_path):
    source=tmp_path/'src';source.mkdir();(source/'link').symlink_to('/etc/passwd')
    with pytest.raises(AgentError):create_snapshot(source,tmp_path/'snap',{},[])


def test_git_ref_freezes_selected_commit_without_switching_source(tmp_path):
    import subprocess
    source = tmp_path/'git'; source.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()
    git('init', '-b', 'main')
    (source/'train.py').write_text('committed')
    git('add', '.')
    git('-c', 'user.name=QA', '-c', 'user.email=qa@example.invalid', 'commit', '-m', 'fixture')
    commit = git('rev-parse', 'HEAD')
    git('branch', 'saved')
    (source/'train.py').write_text('uncommitted')
    (source/'extra.py').write_text('untracked')
    ref = create_snapshot(source, tmp_path/'ref', {'kind': 'branch', 'ref': 'saved'}, [])
    work = create_snapshot(source, tmp_path/'work', {'kind': 'working_tree'}, [])
    assert ref['commit'] == commit
    assert (tmp_path/'ref/train.py').read_text() == 'committed'
    assert not (tmp_path/'ref/extra.py').exists()
    assert (tmp_path/'work/train.py').read_text() == 'uncommitted'
    assert (tmp_path/'work/extra.py').read_text() == 'untracked'
    assert git('branch', '--show-current') == 'main'
    (source/'train.py').write_text('changed again')
    assert (tmp_path/'work/train.py').read_text() == 'uncommitted'


def test_source_packages_are_not_excluded_by_dataset_or_run_names(tmp_path):
    source = tmp_path/'source'
    for name in ('package/data/loader.py', 'runs/entry.py', 'checkpoints/restore.py'):
        path = source/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# genuine source\n')
    snapshot = create_snapshot(source, tmp_path/'snapshot', {'kind':'working_tree'}, [])
    assert set(snapshot['manifest']) == {'package/data/loader.py', 'runs/entry.py', 'checkpoints/restore.py'}


def test_git_snapshot_respects_explicit_artifact_exclusions(tmp_path):
    import subprocess
    source = tmp_path/'source'; source.mkdir()
    (source/'data').mkdir(); (source/'data/loader.py').write_text('# source\n')
    (source/'artifacts').mkdir(); (source/'artifacts/output.bin').write_bytes(b'not source')
    subprocess.run(['git','init','-b','main',str(source)], check=True, capture_output=True)
    subprocess.run(['git','-C',str(source),'add','.'], check=True)
    subprocess.run(['git','-C',str(source),'-c','user.name=QA','-c','user.email=qa@example.invalid','commit','-m','fixture'], check=True, capture_output=True)
    snapshot = create_snapshot(source, tmp_path/'snapshot', {'kind':'ref','ref':'HEAD'}, ['artifacts', 'artifacts/**'])
    assert set(snapshot['manifest']) == {'data/loader.py'}
    assert not (tmp_path/'snapshot/artifacts').exists()
