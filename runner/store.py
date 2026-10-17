"""Durable submission state backed by SQLite, so tracking survives API restarts."""

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

from runner.models import Status, Submission, utcnow


class SubmissionNotFound(KeyError):
    pass


class SubmissionStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS submissions ("
            " id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, doc TEXT NOT NULL)"
        )

    def save(self, submission: Submission) -> None:
        submission.updated_at = utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO submissions (id, status, created_at, doc) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET status = excluded.status, doc = excluded.doc",
                (
                    submission.id,
                    submission.status,
                    submission.created_at.isoformat(),
                    submission.model_dump_json(),
                ),
            )

    def get(self, submission_id: str) -> Submission:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc FROM submissions WHERE id = ?", (submission_id,)
            ).fetchone()
        if row is None:
            raise SubmissionNotFound(submission_id)
        return Submission.model_validate_json(row[0])

    def update(self, submission_id: str, mutate: Callable[[Submission], None]) -> Submission:
        """Atomically read-modify-write a submission; callers mutate the model in place."""
        with self._lock:
            submission = self.get(submission_id)
            mutate(submission)
            self.save(submission)
        return submission

    def list_unfinished(self) -> list[Submission]:
        terminal = [status.value for status in Status if status.is_terminal]
        with self._lock:
            rows = self._conn.execute(
                f"SELECT doc FROM submissions WHERE status NOT IN ({','.join('?' * len(terminal))})"
                " ORDER BY created_at",
                terminal,
            ).fetchall()
        return [Submission.model_validate_json(row[0]) for row in rows]

    def list_recent(self, limit: int) -> list[Submission]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT doc FROM submissions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Submission.model_validate_json(row[0]) for row in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
