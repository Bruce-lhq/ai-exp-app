"""Build a small local-only macOS Dock launcher; no remote side effects."""
import plistlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dist" / "AI Experiment.app"
SDK = "/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk"


def main():
    binary = APP / "Contents" / "MacOS"
    resources = APP / "Contents" / "Resources"
    binary.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    subprocess.run(["swiftc", "-sdk", SDK, "-swift-version", "5", "-framework", "AppKit", "-framework", "UserNotifications", str(ROOT / "macos" / "AIExperiment" / "main.swift"), "-o", str(binary / "AIExperiment")], check=True)
    info = {"CFBundleName": "实验工作台", "CFBundleDisplayName": "实验工作台", "CFBundleIdentifier": "org.ai-experiment.workbench", "CFBundleExecutable": "AIExperiment", "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "0.1.0", "CFBundleVersion": "1", "NSHighResolutionCapable": True, "NSAppleEventsUsageDescription": "复用并聚焦已有的实验工作台网页，避免重复打开标签。", "AIExperimentRoot": str(ROOT), "CFBundleIconFile": "AppIcon"}
    (APP / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
    subprocess.run(["swift", "-sdk", SDK, str(ROOT / "scripts" / "make_icon.swift"), str(resources)], check=True)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(APP)], check=True)
    print(APP)


if __name__ == "__main__":
    main()
