"""Small transactional document store; identity never depends on display names."""
import json
import sqlite3
import threading
from pathlib import Path
from contextlib import contextmanager


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS documents (kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(kind,id))")

    @contextmanager
    def connection(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=10)
            try:
                with db:
                    yield db
            finally:
                db.close()

    def get(self, kind: str, id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT data FROM documents WHERE kind=? AND id=?", (kind, id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT data FROM documents WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, kind: str, id: str, data: dict) -> dict:
        encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
        with self.connection() as db:
            db.execute("INSERT INTO documents VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data", (kind, id, encoded))
        return json.loads(encoded)

    def delete(self, kind: str, id: str) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM documents WHERE kind=? AND id=?", (kind, id))


def connect_database(path: Path):
    return Store(path)
