import importlib.util
import os
from pathlib import Path
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('desktop_builder',ROOT/'scripts/build_desktop.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_cli_archives_include_runtime_with_executable_mode(tmp_path):
    bundle=tmp_path/'ai-experiment';bundle.mkdir()
    (bundle/'ai-experiment').write_text('executable');(bundle/'ai-experiment').chmod(0o755)
    (bundle/'_internal').mkdir();(bundle/'_internal/runtime.dat').write_bytes(b'runtime')
    archive=builder.archive_cli(bundle,tmp_path/'cli.tar.gz')
    with tarfile.open(archive) as stream:
        member=stream.getmember('ai-experiment/ai-experiment')
        if os.name != 'nt':
            assert member.mode&0o111
        assert stream.extractfile('ai-experiment/_internal/runtime.dat').read()==b'runtime'
    archive=builder.archive_cli(bundle,tmp_path/'cli.zip')
    with zipfile.ZipFile(archive) as stream:
        assert stream.read('ai-experiment/_internal/runtime.dat')==b'runtime'


def test_debian_installs_native_launcher_and_keeps_user_data_out_of_package(tmp_path,monkeypatch):
    root=tmp_path/'source';(root/'.local/build-native').mkdir(parents=True)
    (root/'.local/build-native/AppIcon.png').write_bytes(b'icon')
    monkeypatch.setattr(builder,'ROOT',root)
    bundle=tmp_path/'bundle';bundle.mkdir();(bundle/'ai-experiment').write_text('cli')
    stage=builder.debian_layout(bundle,tmp_path/'debian','amd64')
    desktop=(stage/'usr/share/applications/ai-experiment.desktop').read_text()
    assert 'ai-experiment desktop' in desktop and 'Terminal=false' in desktop
    assert (stage/'usr/bin/ai-experiment').is_symlink()
    assert 'Architecture: amd64' in (stage/'DEBIAN/control').read_text()
    assert not (stage/'home').exists()
    assert not (stage/'DEBIAN/postrm').exists()


def test_windows_uninstaller_preserves_shared_workspace():
    source=(ROOT/'scripts/installers/windows.nsi').read_text()
    uninstall=source.split('Section "Uninstall"',1)[1]
    assert 'RMDir /r "$INSTDIR\\_internal"' in uninstall
    assert 'RMDir /r "$LOCALAPPDATA' not in uninstall
    assert 'RequestExecutionLevel user' in source
    assert 'WebView2Setup.exe' in source
