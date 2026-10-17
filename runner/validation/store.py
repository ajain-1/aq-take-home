import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

from runner.models import Status, utcnow
from runner.validation.models import Validation


class ValidationNotFound(KeyError):
    pass


class ValidationStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS validations (id TEXT PRIMARY KEY, status TEXT NOT NULL, doc TEXT NOT NULL)"
        )

    def save(self, validation: Validation) -> None:
        validation.updated_at = utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO validations (id, status, doc) VALUES (?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET status = excluded.status, doc = excluded.doc",
                (validation.id, validation.status, validation.model_dump_json()),
            )

    def get(self, validation_id: str) -> Validation:
        with self._lock:
            row = self._conn.execute("SELECT doc FROM validations WHERE id = ?", (validation_id,)).fetchone()
        if row is None:
            raise ValidationNotFound(validation_id)
        return Validation.model_validate_json(row[0])

    def update(self, validation_id: str, mutate: Callable[[Validation], None]) -> Validation:
        validation = self.get(validation_id)
        mutate(validation)
        self.save(validation)
        return validation

    def list_unfinished(self) -> list[Validation]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT doc FROM validations WHERE status NOT IN (?, ?)", (Status.COMPLETED, Status.FAILED)
            ).fetchall()
        return [Validation.model_validate_json(row[0]) for row in rows]
