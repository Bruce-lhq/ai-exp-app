"""Copy an existing workspace to the standalone app; preserve the original."""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing


def migrate(source, destination):
    source, destination = Path(source), Path(destination)
    if (destination / 'app.sqlite3').exists():
        raise ValueError('目标已有工作区，拒绝覆盖')
    destination.mkdir(parents=True, exist_ok=True)
    staging = destination / 'migration.sqlite3'
    with closing(sqlite3.connect(source / 'app.sqlite3')) as original, closing(sqlite3.connect(staging)) as copied:
        original.backup(copied)
        histories = copied.execute("SELECT id,data FROM documents WHERE kind='history'").fetchall()
        for identity, data in histories:
            record = json.loads(data)
            old = Path(record['cache_dir'])
            target = destination / 'gpu_downloads' / old.name
            if old.exists():
                shutil.copytree(old, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.checkpoint-*', '.download-*'))
            record['cache_dir'] = str(target)
            copied.execute("UPDATE documents SET data=? WHERE kind='history' AND id=?", (json.dumps(record,ensure_ascii=False),identity))
        copied.commit()
        copied.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        copied.execute('PRAGMA journal_mode=DELETE')
    staging.replace(destination / 'app.sqlite3')
    return len(histories)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print('Copied histories:', migrate(args.source, args.destination))
