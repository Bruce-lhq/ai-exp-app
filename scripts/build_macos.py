"""Build a standalone WebKit app with a bundled Python service and web UI."""
import argparse
import plistlib
import subprocess
import shutil
import os
import platform
from ai_exp_app import __version__
from build_desktop import archive_cli, freeze_cli, write_licenses
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dist" / "AI Experiment.app"
SDK = os.environ.get('SDKROOT') or str(next(iter(Path('/Library/Developer/CommandLineTools/SDKs').glob('MacOSX15.4.sdk')), Path(subprocess.check_output(['xcrun', '--show-sdk-path'], text=True).strip())))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch',choices=['arm64','x86_64'],default=platform.machine())
    parser.add_argument('--skip-web',action='store_true')
    args=parser.parse_args()
    if args.arch != platform.machine():
        raise SystemExit('请在目标架构的 macOS runner/Python 上构建，不能跨架构冻结 Python')
    binary = APP / "Contents" / "MacOS"
    resources = APP / "Contents" / "Resources"
    binary.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    if not args.skip_web:
        subprocess.run(['npm','run','build'],cwd=ROOT/'web',check=True)
    frozen=freeze_cli(desktop=False)
    for name, source in [('server', frozen), ('web', ROOT/'web'/'dist')]:
        target=resources/name
        if target.exists(): shutil.rmtree(target)
        shutil.copytree(source,target,symlinks=True)
    write_licenses(resources)
    subprocess.run(["swiftc", "-sdk", SDK, '-target', args.arch+'-apple-macos13.0', "-swift-version", "5", "-framework", "AppKit", "-framework", "WebKit", "-framework", "UserNotifications", str(ROOT / "macos" / "AIExperiment" / "main.swift"), "-o", str(binary / "AIExperiment")], check=True)
    info = {"CFBundleName": "实验工作台", "CFBundleDisplayName": "实验工作台", "CFBundleIdentifier": "org.ai-experiment.workbench", "CFBundleExecutable": "AIExperiment", "CFBundlePackageType": "APPL", "CFBundleShortVersionString": __version__, "CFBundleVersion": "5", "NSHighResolutionCapable": True, "NSAppleEventsUsageDescription": "复用并聚焦已有的实验工作台网页，避免重复打开标签。", "AIExperimentRoot": str(ROOT), "CFBundleIconFile": "AppIcon"}
    (APP / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
    info.pop('AIExperimentRoot', None)
    info.pop('NSAppleEventsUsageDescription', None)
    info.update(CFBundleShortVersionString=__version__, CFBundleVersion='5', LSMinimumSystemVersion='13.0',
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
    artifacts=ROOT/'dist/releases';artifacts.mkdir(parents=True,exist_ok=True)
    archive_cli(frozen,artifacts/('AI-Experiment-CLI-macOS-'+args.arch+'.tar.gz'))
    dmg=artifacts/('AI-Experiment-macOS-'+args.arch+'.dmg')
    if dmg.exists(): dmg.unlink()
    subprocess.run(['hdiutil','create','-volname','实验工作台','-srcfolder',str(staging),'-ov','-format','UDZO',str(dmg)],check=True)
    print(APP)
    print(dmg)


if __name__ == "__main__":
    main()
