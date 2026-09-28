import subprocess

def choose_gpus(count,available):
    if isinstance(count,bool) or not isinstance(count,int) or count<1:
        raise ValueError('GPU 卡数必须为正整数')
    ordered=sorted(set(available))
    return ordered[:count] if len(ordered)>=count else None

def schedule_head(queue,available,paused):
    if paused or not queue:return None
    ids=choose_gpus(queue[0]['gpu_count'],available)
    return None if ids is None else dict(run_id=queue[0]['run_id'],gpu_ids=ids)

def gpu_status():
    devices=subprocess.check_output(['nvidia-smi','--query-gpu=index,uuid,memory.used,memory.total,utilization.gpu','--format=csv,noheader,nounits'],text=True,timeout=10)
    processes=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid','--format=csv,noheader,nounits'],text=True,timeout=10)
    busy={line.split(',')[0].strip() for line in processes.splitlines() if ',' in line}
    return [dict(index=int(v[0]),uuid=v[1],memory_used=int(v[2]),memory_total=int(v[3]),utilization=int(v[4]),available=v[1] not in busy) for line in devices.splitlines() if (v:=[x.strip() for x in line.split(',')]) and len(v)==5]
