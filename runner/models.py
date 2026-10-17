from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class Status(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (Status.COMPLETED, Status.FAILED)


class Phase(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    BUILDING_IMAGE = "building_image"
    LAUNCHING = "launching"
    RUNNING_ATTEMPTS = "running_attempts"
    COLLECTING_RESULTS = "collecting_results"
    DONE = "done"


class AttemptState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AttemptProgress(BaseModel):
    index: int
    state: AttemptState = AttemptState.PENDING
    pods: list[str] = []
    reason: str | None = None

    @property
    def pod(self) -> str | None:
        return self.pods[-1] if self.pods else None

    @property
    def retries(self) -> int:
        return max(len(self.pods) - 1, 0)


class Progress(BaseModel):
    phase: Phase = Phase.QUEUED
    attempts_total: int
    attempts: list[AttemptProgress] = []

    def count(self, state: AttemptState) -> int:
        return sum(1 for attempt in self.attempts if attempt.state == state)


class TaskSpec(BaseModel):
    """The subset of task.yaml the executor relies on."""

    task_id: str
    instruction: str
    max_agent_timeout_sec: float = 360.0
    max_test_timeout_sec: float = 60.0
    resource_class: str = "medium"


class Submission(BaseModel):
    id: str
    task_id: str | None = None
    status: Status = Status.QUEUED
    n_attempts: int
    agent: str
    model: str | None
    progress: Progress
    error: str | None = None
    results: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    launched_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def create(cls, submission_id: str, n_attempts: int, agent: str, model: str | None) -> "Submission":
        return cls(
            id=submission_id,
            n_attempts=n_attempts,
            agent=agent,
            model=model,
            progress=Progress(attempts_total=n_attempts),
        )
