"""Prevent installers and frontend metadata from drifting from the backend version."""
import importlib.util
import json
from pathlib import Path
import tomllib
from packaging.version import Version
from ai_exp_app import __version__


def test_release_versions_agree():
    root = Path(__file__).resolve().parents[1]
    expected = Version(__version__)
    assert Version(tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']) == expected
    assert Version(json.loads((root / 'web/package.json').read_text())['version']) == expected
    lock = json.loads((root / 'web/package-lock.json').read_text())
    assert Version(lock['version']) == expected
    assert Version(lock['packages']['']['version']) == expected
    spec = importlib.util.spec_from_file_location('release_builder', root / 'scripts/build_desktop.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    assert Version(builder.VERSION) == expected
