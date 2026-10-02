import json
import os
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from ai_exp_app.app import create_app
from ai_exp_app.config import Config, LOCAL_DEFAULTS
from ai_exp_remote import config as remote_config
from ai_exp_remote.deletion import inspect
from ai_exp_remote.state import AgentError


def test_clean_install_uses_neutral_defaults_and_remains_offline_available(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.get('/')
        result = client.get('/api/settings/local').json()
        assert result == {'local_settings': LOCAL_DEFAULTS, 'configured': False}
        assert client.get('/api/history').status_code == 200
        assert client.get('/api/analysis/templates').status_code == 200
    assert not (tmp_path / 'config.local.json').exists()


def test_local_settings_persist_without_bundled_machine_paths(tmp_path):
    config = Config.load(tmp_path)
    with TestClient(create_app(tmp_path)) as client:
        client.get('/')
        response = client.put('/api/settings/local', json={
            'remote_runs_root': '/srv/experiments/runs', 'remote_data_root': '/srv/datasets/training',
            'remote_import_root': '/srv/experiments/runs/', 'local_import_root': '~/Downloads/runs/'
        }, headers={'Origin': 'http://testserver'})
        assert response.status_code == 200
        assert response.json()['configured'] is True
    loaded = Config.load(tmp_path)
    assert loaded.local_settings['remote_import_root'] == '/srv/experiments/runs/'
    assert loaded.local_settings['remote_python'] == 'python3'
    if os.name != 'nt':  # Windows chmod does not implement POSIX owner/group permission bits.
        assert loaded.config_file.stat().st_mode & 0o777 == 0o600
    assert json.loads(config.config_file.read_text())['local_import_root'] == '~/Downloads/runs/'


def test_invalid_configuration_does_not_replace_existing_file(tmp_path):
    config = Config.load(tmp_path)
    config.save_local_settings({'remote_runs_root': '/srv/runs'})
    before = config.config_file.read_bytes()
    for values in ({'remote_runs_root': 'relative/runs'}, {'unknown': 'x'}, {'ssh_alias': '\0'}):
        with pytest.raises(ValueError):
            config.save_local_settings(values)
        assert config.config_file.read_bytes() == before


def test_remote_agent_reads_configuration_beside_release_not_archive(tmp_path, monkeypatch):
    root = tmp_path / 'deployment'
    release = root / 'releases/agent-test.pyz'
    release.parent.mkdir(parents=True)
    release.touch()
    settings = {'remote_state_dir': str(root / 'kept-state'), 'remote_runs_root': str(tmp_path / 'runs')}
    (root / 'config.local.json').write_text(json.dumps(settings))
    monkeypatch.delenv('AI_EXP_CONFIG_FILE', raising=False)
    monkeypatch.setattr(sys, 'argv', [str(release)])
    assert remote_config.settings()['remote_state_dir'] == str(root / 'kept-state')
    assert remote_config.settings()['remote_runs_root'] == str(tmp_path / 'runs')
    assert remote_config.settings()['remote_python'] == 'python3'


def test_neutral_configuration_never_allows_deleting_unregistered_directory(tmp_path, monkeypatch):
    monkeypatch.setattr('ai_exp_remote.deletion.settings', lambda: {'remote_runs_root': '/'})
    target = tmp_path / 'unregistered'
    target.mkdir()
    (target / 'args.json').write_text('{}')
    with pytest.raises(AgentError, match='没有已配置'):
        inspect(str(target), {'runs': {}})


def test_installer_publishes_valid_external_config_and_absolute_agent_symlink(tmp_path, monkeypatch):
    import importlib.util
    import io
    import shlex

    path = Path(__file__).resolve().parents[1] / 'scripts/install_remote.py'
    spec = importlib.util.spec_from_file_location('install_remote_test', path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    config = Config.load(tmp_path / 'local')
    config.save_local_settings({'remote_runs_root': '/srv/runs', 'remote_data_root': '/srv/data'})
    monkeypatch.setenv('AI_EXP_CONFIG_FILE', str(config.config_file))
    root = tmp_path / 'remote'
    monkeypatch.setattr(sys, 'argv', [str(path), '--remote-root', str(root), '--output', str(tmp_path / 'agent.pyz')])

    def install(argv, input, **kwargs):
        command = shlex.split(argv[-1])
        assert command[:2] == ['python3', '-c']
        monkeypatch.setattr(sys, 'stdin', type('Input', (), {'buffer': io.BytesIO(input)})())
        exec(compile(command[2], '<remote-install>', 'exec'), {})
        return None

    monkeypatch.setattr(installer.subprocess, 'run', install)
    installer.main()
    saved = json.loads((root / 'config.local.json').read_text())
    assert saved['remote_state_dir'] == str(root / 'state')
    assert saved['remote_runs_root'] == '/srv/runs'
    assert (root / 'agent.pyz').resolve().is_file()
    assert (root / 'config.local.json').stat().st_mode & 0o777 == 0o600


def test_setup_root_changes_keep_derived_agent_and_import_browser_consistent(tmp_path):
    config = Config.load(tmp_path)
    saved = config.save_local_settings({'remote_root': '/srv/workbench', 'remote_runs_root': '/srv/runs'})
    assert saved['remote_agent'] == '/srv/workbench/agent.pyz'
    assert saved['remote_import_root'] == '/srv/runs/'
    config.save_local_settings({'remote_agent': '/other/custom-agent.pyz', 'remote_import_root': '/other/imports/'})
    changed = config.save_local_settings({'remote_root': '/new/workbench', 'remote_runs_root': '/new/runs'})
    assert changed['remote_agent'] == '/other/custom-agent.pyz'
    assert changed['remote_import_root'] == '/other/imports/'


def test_dataset_directory_is_optional_for_generic_training(tmp_path):
    config = Config.load(tmp_path)
    config.save_local_settings({"remote_runs_root": "/srv/runs"})
    assert config.configured
    assert config.local_settings["remote_data_root"] == ""


def test_local_agent_mode_requires_explicit_absolute_agent_and_state(tmp_path):
    config = Config.load(tmp_path)
    with pytest.raises(ValueError, match='绝对路径'):
        config.save_local_settings({'connection_mode': 'local'})
    with pytest.raises(ValueError, match='连接方式'):
        config.save_local_settings({'connection_mode': 'other'})
    saved = config.save_local_settings({'connection_mode': 'local',
        'remote_agent': str(tmp_path / 'agent.pyz'), 'remote_python': str(tmp_path / 'python'),
        'remote_state_dir': str(tmp_path / 'shared-agent-state'), 'remote_runs_root': '/srv/runs'})
    assert saved['connection_mode'] == 'local'
    assert config.configured
