"""Build or deploy the same Linux agent from source, wheels or frozen clients."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
import zipfile
from .config import Config


def build_agent(output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    bundled = Path(getattr(sys, '_MEIPASS', '')) / 'agent.pyz'
    if getattr(sys, 'frozen', False) and bundled.is_file():
        output.write_bytes(bundled.read_bytes())
        return output
    spec = importlib.util.find_spec('ai_exp_remote')
    if spec is None or not spec.origin:
        raise RuntimeError('Remote agent sources are missing; use the matching source release')
    package = Path(spec.origin).parent
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('__main__.py', '\n'.join([
            'import sys',
            "if len(sys.argv)<2 or sys.argv[1]=='rpc':",
            '    from ai_exp_remote.rpc import main; main()',
            "elif sys.argv[1]=='daemon':",
            '    from ai_exp_remote.runtime import daemon; daemon(sys.argv[2])',
            "elif sys.argv[1]=='attempt':",
            '    from ai_exp_remote.runner import execute_attempt; execute_attempt(sys.argv[2])',
            "else: raise SystemExit('Unknown command')", '',
        ]))
        for path in sorted(package.rglob('*.py')):
            archive.write(path, 'ai_exp_remote/' + path.relative_to(package).as_posix())
    return output


def install_agent(config=None, read_only=False):
    config = config or Config.load()
    local = config.local_settings
    if local.get('connection_mode') == 'local':
        raise ValueError('本机模式复用既有代理，请先在 SSH 模式部署代理，再填写其绝对路径和既有状态目录')
    root = local['remote_root']
    output = build_agent(config.data_dir / 'agent.pyz')
    digest = hashlib.sha256(output.read_bytes()).hexdigest()[:16]
    wrapper = Path.home() / '.local/bin/ssh'
    ssh = str(wrapper) if wrapper.is_file() and sys.platform != 'win32' else 'ssh'
    settings = {**local, 'remote_state_dir': local['remote_state_dir'] or root + '/state'}
    install = '\n'.join([
        'import io, os, sys, zipfile, hashlib, json',
        'from pathlib import Path',
        'root=Path(' + repr(root) + ').expanduser().resolve(); target=root/"releases"/' + repr('agent-' + digest + '.pyz'),
        'data=sys.stdin.buffer.read()',
        'assert hashlib.sha256(data).hexdigest()[:16] == ' + repr(digest),
        'z=zipfile.ZipFile(io.BytesIO(data))',
        '[compile(z.read(n),n,"exec") for n in z.namelist() if n.endswith(".py")]',
        'target.parent.mkdir(parents=True, exist_ok=True)',
        'staging=target.with_suffix(".staging"); staging.write_bytes(data); os.replace(staging,target)',
        'config=root/"config.local.json"; config_tmp=root/"config.local.json.tmp"',
        'settings=' + repr(settings),
        'settings["remote_root"]=str(root)',
        'settings["remote_state_dir"]=str(Path(settings["remote_state_dir"]).expanduser().resolve())',
        'config_tmp.write_text(json.dumps(settings,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8"); config_tmp.chmod(0o600); os.replace(config_tmp,config)',
        'pointer=root/"agent.pyz"; temp=root/"agent.next"',
        'temp.unlink(missing_ok=True); temp.symlink_to(target); os.replace(temp,pointer)',
        '(root/"read-only").touch()' if read_only else '(root/"read-only").unlink(missing_ok=True)',
    ])
    command = shlex.quote(local['remote_python']) + ' -c ' + shlex.quote(install)
    try:
        subprocess.run([ssh, local['ssh_alias'], '-o', 'ConnectTimeout=12', command],
                       input=output.read_bytes(), capture_output=True, timeout=60, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError('Installation failed; retry without changing training state: ' + exc.stderr.decode(errors='replace')) from exc
    return {'installed': root.rstrip('/') + '/agent.pyz', 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'read_only': read_only}
