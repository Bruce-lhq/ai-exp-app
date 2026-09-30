"""Build a standalone WebKit app with a bundled Python service and web UI."""
import plistlib
import subprocess
import shutil
import sys
import os
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dist" / "AI Experiment.app"
SDK = os.environ.get('SDKROOT') or str(next(iter(Path('/Library/Developer/CommandLineTools/SDKs').glob('MacOSX15.4.sdk')), Path(subprocess.check_output(['xcrun', '--show-sdk-path'], text=True).strip())))


def main():
    binary = APP / "Contents" / "MacOS"
    resources = APP / "Contents" / "Resources"
    binary.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    subprocess.run(['npm', 'run', 'build'], cwd=ROOT/'web', check=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
        '--name', 'ai-exp-server', '--paths', str(ROOT/'src'), '--collect-all', 'uvicorn',
        '--distpath', str(ROOT/'dist'/'frozen'), '--workpath', str(ROOT/'.local'/'freeze'),
        '--specpath', str(ROOT/'.local'), str(ROOT/'scripts'/'desktop_server.py')], check=True)
    for name, source in [('server', ROOT/'dist'/'frozen'/'ai-exp-server'), ('web', ROOT/'web'/'dist')]:
        target=resources/name
        if target.exists(): shutil.rmtree(target)
        shutil.copytree(source,target,symlinks=True)
    subprocess.run(["swiftc", "-sdk", SDK, '-target', platform.machine()+'-apple-macos13.0', "-swift-version", "5", "-framework", "AppKit", "-framework", "WebKit", "-framework", "UserNotifications", str(ROOT / "macos" / "AIExperiment" / "main.swift"), "-o", str(binary / "AIExperiment")], check=True)
    info = {"CFBundleName": "实验工作台", "CFBundleDisplayName": "实验工作台", "CFBundleIdentifier": "org.ai-experiment.workbench", "CFBundleExecutable": "AIExperiment", "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "0.2.0", "CFBundleVersion": "2", "NSHighResolutionCapable": True, "NSAppleEventsUsageDescription": "复用并聚焦已有的实验工作台网页，避免重复打开标签。", "AIExperimentRoot": str(ROOT), "CFBundleIconFile": "AppIcon"}
    (APP / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
    info.pop('AIExperimentRoot', None)
    info.pop('NSAppleEventsUsageDescription', None)
    info.update(CFBundleShortVersionString='0.2.0', CFBundleVersion='2', LSMinimumSystemVersion='13.0',
        NSAppTransportSecurity={'NSAllowsLocalNetworking': True})
    (APP / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(["swift", "-sdk", SDK, str(ROOT / "scripts" / "make_icon.swift"), str(resources)], check=True)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(APP)], check=True)
    staging=ROOT/'dist'/'installer'
    staging.mkdir(exist_ok=True)
    target=staging/APP.name
    if target.exists(): shutil.rmtree(target)
    shutil.copytree(APP,target,symlinks=True)
    link=staging/'Applications'
    if not link.exists(): link.symlink_to('/Applications')
    dmg=ROOT/'dist'/'AI-Experiment-macOS.dmg'
    if dmg.exists(): dmg.unlink()
    subprocess.run(['hdiutil','create','-volname','实验工作台','-srcfolder',str(staging),'-ov','-format','UDZO',str(dmg)],check=True)
    print(APP)
    print(dmg)


if __name__ == "__main__":
    main()
