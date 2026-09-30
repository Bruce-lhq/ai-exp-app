import importlib.util
from pathlib import Path
import pytest
from ai_exp_app.db import Store

spec = importlib.util.spec_from_file_location('desktop_migration', Path(__file__).parents[1] / 'scripts/migrate_desktop.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_migration_copies_cache_and_preserves_original(tmp_path):
    source = tmp_path / 'old'
    store = Store(source / 'app.sqlite3')
    cache = tmp_path / 'cached' / '实验'
    cache.mkdir(parents=True)
    (cache / 'args.json').write_text('{"lr":1}')
    (cache / '.checkpoint-partial').write_bytes(b'partial')
    store.put('history', 'h', {'id': 'h', 'cache_dir': str(cache)})
    target = tmp_path / 'installed'
    assert module.migrate(source, target) == 1
    record = Store(target / 'app.sqlite3').get('history', 'h')
    assert Path(record['cache_dir']) == target / 'gpu_downloads' / '实验'
    assert (Path(record['cache_dir']) / 'args.json').read_text() == '{"lr":1}'
    assert not (Path(record['cache_dir']) / '.checkpoint-partial').exists()
    assert store.get('history', 'h')['cache_dir'] == str(cache)
    with pytest.raises(ValueError): module.migrate(source, target)
