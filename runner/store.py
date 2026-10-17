"""Durable state backed by SQLite, so tracking survives API restarts."""

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

from runner.models import Status, Submission, utcnow

# Stored models carry `id`, `status`, `created_at` and `updated_at`.
Document = TypeVar("Document", bound=BaseModel)


class DocumentNotFound(KeyError):
    pass


class SubmissionNotFound(DocumentNotFound):
    pass


class DocumentStore(Generic[Document]):
    """JSON documents keyed by id, with status and creation time indexed for queries."""

    def __init__(self, db_path: Path, table: str, model: type[Document], not_found: type[DocumentNotFound]):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._table = table
        self._model = model
        self._not_found = not_found
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} ("
            " id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, doc TEXT NOT NULL)"
        )

    def save(self, document: Document) -> None:
        document.updated_at = utcnow()
        with self._lock:
            self._conn.execute(
                f"INSERT INTO {self._table} (id, status, created_at, doc) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET status = excluded.status, doc = excluded.doc",
                (document.id, document.status, document.created_at.isoformat(), document.model_dump_json()),
            )

    def get(self, document_id: str) -> Document:
        with self._lock:
            row = self._conn.execute(f"SELECT doc FROM {self._table} WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            raise self._not_found(document_id)
        return self._model.model_validate_json(row[0])

    def update(self, document_id: str, mutate: Callable[[Document], None]) -> Document:
        """Atomically read-modify-write a document; callers mutate the model in place."""
        with self._lock:
            document = self.get(document_id)
            mutate(document)
            self.save(document)
        return document

    def list_unfinished(self) -> list[Document]:
        terminal = [status.value for status in Status if status.is_terminal]
        placeholders = ",".join("?" * len(terminal))
        return self._select(f"WHERE status NOT IN ({placeholders}) ORDER BY created_at", terminal)

    def list_recent(self, limit: int) -> list[Document]:
        return self._select("ORDER BY created_at DESC LIMIT ?", [limit])

    def count(self) -> int:
        with self._lock:
            return self._conn.execute(f"SELECT COUNT(*) FROM {self._table}").fetchone()[0]

    def _select(self, clause: str, params: list) -> list[Document]:
        with self._lock:
            rows = self._conn.execute(f"SELECT doc FROM {self._table} {clause}", params).fetchall()
        return [self._model.model_validate_json(row[0]) for row in rows]


class SubmissionStore(DocumentStore[Submission]):
    def __init__(self, db_path: Path):
        super().__init__(db_path, "submissions", Submission, SubmissionNotFound)
