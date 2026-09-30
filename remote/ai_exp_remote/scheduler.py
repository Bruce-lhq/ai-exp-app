import subprocess
import json
from pathlib import Path
from .config import settings
from .state import AgentError

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
    config = settings()
    probe = config.get('remote_gpu_probe')
    if probe:
        if not Path(probe).is_absolute():
            raise AgentError('GPU_PROBE', 'GPU 检查脚本必须是远端绝对路径')
        try:
            response = subprocess.run([config['remote_python'], probe], text=True, capture_output=True, timeout=15, check=True)
            devices = json.loads(response.stdout)
            if not isinstance(devices, list):
                raise ValueError('返回值必须是 JSON 数组')
            indices = set()
            for device in devices:
                if not isinstance(device, dict) or type(device.get('index')) is not int or device['index'] < 0 or type(device.get('available')) is not bool or device['index'] in indices:
                    raise ValueError('每张卡需要唯一非负整数 index 和布尔 available')
                indices.add(device['index'])
            return devices
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise AgentError('GPU_PROBE', 'GPU 检查失败；请让接入 Agent 核对设备查询脚本', str(exc)) from exc
    devices=subprocess.check_output(['nvidia-smi','--query-gpu=index,uuid,memory.used,memory.total,utilization.gpu','--format=csv,noheader,nounits'],text=True,timeout=10)
    processes=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid','--format=csv,noheader,nounits'],text=True,timeout=10)
    busy={line.split(',')[0].strip() for line in processes.splitlines() if ',' in line}
    return [dict(index=int(v[0]),uuid=v[1],memory_used=int(v[2]),memory_total=int(v[3]),utilization=int(v[4]),available=v[1] not in busy) for line in devices.splitlines() if (v:=[x.strip() for x in line.split(',')]) and len(v)==5]
