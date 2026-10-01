"""Build host-native standalone CLI plus Windows/Linux desktop installers."""
import argparse
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='0.4.0'


def write_licenses(resources):
    resources.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'LICENSE',resources/'LICENSE')
    notices=['Third-party licenses from the build environment; not all packages are bundled.']
    for package in sorted(distributions(),key=lambda value:value.metadata['Name'].lower()):
        for file in package.files or []:
            source=package.locate_file(file)
            if source.is_file() and source.name.upper().startswith(('LICENSE','COPYING','NOTICE')):
                notices.append(f"\n## {package.metadata['Name']} {package.version}: {source.name}\n\n"+source.read_text(errors='replace'))
    for path,package in sorted(json.loads((ROOT/'web/package-lock.json').read_text())['packages'].items()):
        if not path or package.get('dev'):
            continue
        for source in sorted((ROOT/'web'/path).glob('*')):
            if source.is_file() and source.name.upper().startswith(('LICENSE','COPYING','NOTICE')):
                notices.append(f"\n## {path.removeprefix('node_modules/')} {package['version']}: {source.name}\n\n"+source.read_text(errors='replace'))
    python_license=Path(sysconfig.get_path('stdlib'))/'LICENSE.txt'
    if not python_license.exists():
        python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.exists():
        notices.append('\n## Python\n\n'+python_license.read_text(errors='replace'))
    (resources/'THIRD-PARTY-NOTICES.txt').write_text('\n'.join(notices),encoding='utf-8')


def make_icons(directory):
    from PIL import Image,ImageDraw
    directory.mkdir(parents=True,exist_ok=True)
    image=Image.new('RGBA',(1024,1024))
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((48,48,976,976),radius=200,fill=(31,66,143))
    points=[]
    for index in range(201):
        t=index/200;u=1-t
        points.append((u**3*230+3*u*u*t*320+3*u*t*t*510+t**3*790,
                       u**3*294+3*u*u*t*814+3*u*t*t*544+t**3*724))
    draw.line(points,fill='white',width=48)
    for x,y in [(230,294),(470,597),(790,724)]:
        draw.ellipse((x-45,y-45,x+45,y+45),fill=(117,214,201))
    image.resize((512,512),Image.Resampling.LANCZOS).save(directory/'AppIcon.png')
    image.save(directory/'AppIcon.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])


def freeze_cli(desktop=True):
    assets=ROOT/'.local/build-native'
    make_icons(assets)
    write_licenses(assets)
    sys.path.insert(0,str(ROOT/'src'))
    sys.path.insert(0,str(ROOT/'remote'))
    from ai_exp_app.remote_install import build_agent
    build_agent(assets/'agent.pyz')
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','ai-experiment',
             '--paths',str(ROOT/'src'),'--collect-all','uvicorn','--collect-submodules','ai_exp_app',
             '--hidden-import','matplotlib.backends.backend_agg','--add-data',str(ROOT/'web/dist')+os.pathsep+'web',
             '--add-data',str(assets)+os.pathsep+'native',
             '--add-data',str(assets/'agent.pyz')+os.pathsep+'.',
             '--add-data',str(ROOT/'skills/experiment-workbench-setup')+os.pathsep+'onboarding','--distpath',str(ROOT/'dist/frozen'),
             '--workpath',str(ROOT/'.local/freeze'),'--specpath',str(ROOT/'.local')]
    if desktop:
        command.extend(['--collect-all','webview'])
        if sys.platform.startswith('linux'):
            command.extend(['--hidden-import','PySide6.QtWebEngineWidgets','--hidden-import','PySide6.QtWebEngineCore',
                            '--exclude-module','PyQt5','--exclude-module','PyQt6','--exclude-module','PySide2'])
        elif sys.platform=='win32':
            command.extend(['--icon',str(assets/'AppIcon.ico'),'--collect-all','pythonnet','--collect-all','clr_loader'])
    command.append(str(ROOT/'scripts/desktop_entry.py'))
    subprocess.run(command,cwd=ROOT,check=True)
    result=ROOT/'dist/frozen/ai-experiment'
    for filename in ('LICENSE','THIRD-PARTY-NOTICES.txt'):
        shutil.copyfile(assets/filename,result/filename)
    return result


def archive_cli(bundle,target):
    if target.suffix=='.zip':
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(bundle.rglob('*')):
                if path.is_file():archive.write(path,str(Path(bundle.name)/path.relative_to(bundle)))
    else:
        with tarfile.open(target,'w:gz') as archive:
            archive.add(bundle,arcname=bundle.name)
    return target


def debian_layout(bundle,target,architecture):
    program=target/'opt/ai-experiment'
    program.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(bundle,program,symlinks=True)
    (target/'usr/bin').mkdir(parents=True)
    (target/'usr/bin/ai-experiment').symlink_to('/opt/ai-experiment/ai-experiment')
    applications=target/'usr/share/applications';applications.mkdir(parents=True)
    (applications/'ai-experiment.desktop').write_text('[Desktop Entry]\nType=Application\nName=AI Experiment\nComment=Training experiment workbench\nExec=/opt/ai-experiment/ai-experiment desktop\nIcon=ai-experiment\nTerminal=false\nCategories=Development;Science;\nStartupWMClass=ai-experiment\n')
    icons=target/'usr/share/icons/hicolor/512x512/apps';icons.mkdir(parents=True)
    shutil.copyfile(ROOT/'.local/build-native/AppIcon.png',icons/'ai-experiment.png')
    metadata=target/'DEBIAN';metadata.mkdir()
    dependencies='libc6 (>= 2.39), libstdc++6, libnotify-bin, libgl1, libegl1, libgbm1, libxcomposite1, libxdamage1, libxrandr2, libxtst6, libxfixes3, libxshmfence1, libxss1, libxi6, libnss3, libnspr4, libdbus-1-3, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-xinerama0, libxcb-xkb1, libxcb-shape0, libx11-xcb1, libfontconfig1, libfreetype6, libasound2t64 | libasound2'
    (metadata/'control').write_text(f'Package: ai-experiment\nVersion: {VERSION}\nArchitecture: {architecture}\nMaintainer: AI Experiment Contributors <contributors@example.invalid>\nDepends: {dependencies}\nSection: science\nPriority: optional\nDescription: Local training experiment workbench\n Bundled native window, local service and command-line tools.\n')
    for path in target.rglob('*'):
        if path.is_dir():path.chmod(0o755)
    return target


def build_windows(bundle,artifacts,architecture):
    if architecture!='x64':
        raise RuntimeError('Windows 安装器当前只验证 x64；请在 x64 runner 构建')
    nsis=shutil.which('makensis')
    if nsis is None:
        candidate=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'NSIS/makensis.exe'
        if candidate.exists():nsis=str(candidate)
    if nsis is None:raise RuntimeError('请安装 NSIS 后构建 Windows 安装器')
    bootstrap=ROOT/'.local/build-native/MicrosoftEdgeWebview2Setup.exe'
    if not bootstrap.exists():
        with urllib.request.urlopen('https://go.microsoft.com/fwlink/p/?LinkId=2124703',timeout=60) as response:
            bootstrap.write_bytes(response.read())
    # The official bootstrapper installs Microsoft's Evergreen runtime when needed.
    subprocess.run(['powershell','-NoProfile','-Command',
                    f"$signature = Get-AuthenticodeSignature -LiteralPath '{str(bootstrap).replace(chr(39),chr(39)*2)}'; if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {{ exit 1 }}"],check=True)
    installer=artifacts/f'AI-Experiment-Windows-{architecture}-Setup.exe'
    subprocess.run([nsis,'/V2',f'/DBUNDLE={bundle}',f'/DOUTPUT={installer}',f'/DVERSION={VERSION}',
                    f'/DBOOTSTRAP={bootstrap}',str(ROOT/'scripts/installers/windows.nsi')],check=True)
    archive_cli(bundle,artifacts/f'AI-Experiment-CLI-Windows-{architecture}.zip')
    return installer


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-web',action='store_true')
    args=parser.parse_args()
    if sys.platform=='darwin':
        raise SystemExit('macOS 请使用 scripts/build_macos.py')
    if not args.skip_web:
        subprocess.run(['npm.cmd' if sys.platform=='win32' else 'npm','run','build'],cwd=ROOT/'web',check=True)
    bundle=freeze_cli()
    artifacts=ROOT/'dist/releases';artifacts.mkdir(parents=True,exist_ok=True)
    machine=platform.machine().lower()
    if sys.platform=='win32':
        output=build_windows(bundle,artifacts,'x64' if machine in ('amd64','x86_64') else machine)
    else:
        architecture={'x86_64':'amd64','aarch64':'arm64','arm64':'arm64'}.get(machine,machine)
        stage=ROOT/'dist/debian'
        if stage.exists():shutil.rmtree(stage)
        debian_layout(bundle,stage,architecture)
        output=artifacts/f'AI-Experiment-Ubuntu-{architecture}.deb'
        subprocess.run(['dpkg-deb','--build','--root-owner-group',str(stage),str(output)],check=True)
        archive_cli(bundle,artifacts/f'AI-Experiment-CLI-Linux-{architecture}.tar.gz')
    print(output)


if __name__=='__main__':
    main()
