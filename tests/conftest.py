"""Local clients are cross-platform; remote process/state contracts target Linux only."""
import sys
import pytest


REMOTE_PROCESS_MODULES = {
    'test_adoption.py', 'test_remote_core.py', 'test_remote_runtime.py',
    'test_remote_submission.py', 'test_generic_remote.py', 'test_snapshots.py',
    'test_gpu_inventory.py',
}
REMOTE_MIXED_TESTS = {
    'test_local_config.py': {
        'test_remote_agent_reads_configuration_beside_release_not_archive',
        'test_neutral_configuration_never_allows_deleting_unregistered_directory',
        'test_installer_publishes_valid_external_config_and_absolute_agent_symlink',
    },
    'test_history_resume.py': {
        'test_checkpoint_pin_rejects_new_version_and_keeps_independent_copy',
        'test_submission_pins_resume_before_queue_and_uses_new_output',
    },
    'test_desktop_packaging.py': {'test_debian_installs_native_launcher_and_keeps_user_data_out_of_package'},
}


def pytest_collection_modifyitems(items):
    if sys.platform.startswith('linux'):
        return
    remote_only = pytest.mark.skip(reason='Remote Linux agent state/process semantics are verified on Ubuntu CI')
    for item in items:
        filename = item.path.name
        if filename in REMOTE_PROCESS_MODULES or item.originalname in REMOTE_MIXED_TESTS.get(filename, set()):
            item.add_marker(remote_only)
