import importlib.util
from pathlib import Path
import tarfile
import pytest


def builder():
    path = Path(__file__).resolve().parents[1] / 'scripts/build_gpu_web.py'
    spec = importlib.util.spec_from_file_location('gpu_web_bundle', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_bundle


def checkout(root):
    for name in ('pyproject.toml', 'requirements.lock', 'README.md', 'LICENSE',
                 'src/ai_exp_app/app.py', 'remote/__main__.py', 'web/dist/index.html', 'docs/mobile-web.md'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('public source', encoding='utf-8')
    (root / 'config.local.json').write_text('PRIVATE CONFIG')
    (root / 'src/ai_exp_app/__pycache__').mkdir()
    (root / 'src/ai_exp_app/__pycache__/private.py').write_text('PRIVATE CACHE')


def test_source_bundle_has_no_private_config_cache_or_owner(tmp_path):
    root = tmp_path / 'checkout'; root.mkdir(); checkout(root)
    bundle = builder()(root, tmp_path / 'bundle.tar.gz')
    with tarfile.open(bundle) as archive:
        assert {m.name for m in archive.getmembers()} == {
            'ai-experiment-web/' + name for name in ('pyproject.toml', 'requirements.lock', 'README.md',
            'LICENSE', 'src/ai_exp_app/app.py', 'remote/__main__.py', 'web/dist/index.html', 'docs/mobile-web.md')}
        assert all(m.uid == m.gid == 0 and not m.uname and not m.gname for m in archive.getmembers())


def test_bundle_refuses_external_symlink(tmp_path):
    root = tmp_path / 'checkout'; root.mkdir(); checkout(root)
    external = tmp_path / 'secret'; external.write_text('PRIVATE')
    (root / 'web/dist/private').symlink_to(external)
    with pytest.raises(ValueError, match='symbolic'):
        builder()(root, tmp_path / 'bundle.tar.gz')
