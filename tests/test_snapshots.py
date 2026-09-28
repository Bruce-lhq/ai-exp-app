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
