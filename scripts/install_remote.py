#!/usr/bin/env python3
"""Build a standard-library zipapp and atomically install in an isolated location."""
import argparse
import hashlib
from pathlib import Path
import shlex
import subprocess
import zipapp

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--alias',default='gpu');parser.add_argument('--read-only',action='store_true')
    parser.add_argument('--build-only',action='store_true');parser.add_argument('--output',default='.local/agent.pyz')
    parser.add_argument('--remote-root',default='/your_exp/ai_exp_app')
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1];output=Path(args.output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    zipapp.create_archive(repo/'remote',output,interpreter='/usr/bin/env python3',filter=lambda p: '__pycache__' not in p.parts and p.suffix != '.pyc')
    if args.build_only:print(output);return
    root=args.remote_root;digest=hashlib.sha256(output.read_bytes()).hexdigest()[:16]
    target=root+'/releases/agent-'+digest+'.pyz'
    wrapper=Path.home()/'.local/bin/ssh';ssh=str(wrapper) if wrapper.exists() else 'ssh'
    def run(command,data=None):
        return subprocess.run([ssh,args.alias,'-o','ControlMaster=no','-o','ControlPath=none','-o','ConnectTimeout=12',command],input=data,capture_output=True,timeout=60,check=True)
    # Only trusted installation paths are interpolated, with shell quoting.
    # One connection: a dropped upload cannot publish an incomplete release.
    install = '\n'.join([
        'import io, os, sys, zipfile, hashlib',
        'from pathlib import Path',
        'root=Path('+repr(root)+'); target=Path('+repr(target)+')',
        'data=sys.stdin.buffer.read()',
        'assert hashlib.sha256(data).hexdigest()[:16] == '+repr(digest),
        'z=zipfile.ZipFile(io.BytesIO(data))',
        '[compile(z.read(n),n,"exec") for n in z.namelist() if n.endswith(".py")]',
        'target.parent.mkdir(parents=True, exist_ok=True)',
        'staging=target.with_suffix(".staging"); staging.write_bytes(data); os.replace(staging,target)',
        'pointer=root/"agent.pyz"; temp=root/"agent.next"',
        'temp.unlink(missing_ok=True); temp.symlink_to(target); os.replace(temp,pointer)',
        '(root/"read-only").touch()' if args.read_only else '(root/"read-only").unlink(missing_ok=True)',
    ])
    try:
        run('python3 -c '+shlex.quote(install),output.read_bytes())
    except subprocess.CalledProcessError as exc:
        raise SystemExit('安装失败，原版本仍可重试：'+exc.stderr.decode(errors='replace')) from exc
    print('Installed '+root+'/agent.pyz')
if __name__=='__main__':main()
