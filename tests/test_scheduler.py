import pytest
from ai_exp_remote.scheduler import schedule_head,choose_gpus

def test_fifo_blocks_small_follower():
    assert schedule_head([dict(run_id='a',gpu_count=4),dict(run_id='b',gpu_count=2)],[0,1],False) is None

def test_lowest_free_devices():
    assert schedule_head([dict(run_id='a',gpu_count=2)],[4,1,3],False)==dict(run_id='a',gpu_ids=[1,3])
    assert schedule_head([dict(run_id='a',gpu_count=2)],[1,2],True) is None

def test_invalid_count():
    with pytest.raises(ValueError):choose_gpus(0,[1])
