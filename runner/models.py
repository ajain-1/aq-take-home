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
    VALIDATING = "validating"
    PREPARING = "preparing"
    BUILDING_IMAGE = "building_image"
    LAUNCHING = "launching"
    RUNNING_ATTEMPTS = "running_attempts"
    COLLECTING_RESULTS = "collecting_results"
    DONE = "done"


class Strategy(StrEnum):
    FIXED = "fixed"
    ADAPTIVE = "adaptive"


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


class Wave(BaseModel):
    """A batch of attempts launched together as one Indexed Job."""

    index: int
    offset: int
    size: int
    launched_at: datetime | None = None
    done: bool = False
    # Wall-clock seconds while any attempt was running, and while attempts were only
    # waiting for cluster capacity; persisted so deadlines survive a restart.
    running_sec: float = 0.0
    queued_sec: float = 0.0

    def advance_clock(self, attempts: list["AttemptProgress"], elapsed_sec: float) -> None:
        """Charge elapsed time to running if any attempt runs, else to queueing if any waits."""
        states = {attempt.state for attempt in attempts}
        if AttemptState.RUNNING in states:
            self.running_sec += elapsed_sec
        elif AttemptState.PENDING in states:
            self.queued_sec += elapsed_sec


class Progress(BaseModel):
    phase: Phase = Phase.QUEUED
    attempts_total: int
    attempts: list[AttemptProgress] = []
    waves: list[Wave] = []

    @property
    def attempts_launched(self) -> int:
        return sum(wave.size for wave in self.waves)

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
    strategy: Strategy = Strategy.FIXED
    confidence: float = 1.0
    agent: str
    model: str | None
    progress: Progress
    error: str | None = None
    results: dict[str, Any] | None = None
    validation_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    launched_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def create(
        cls,
        submission_id: str,
        n_attempts: int,
        agent: str,
        model: str | None,
        strategy: Strategy = Strategy.FIXED,
        confidence: float = 1.0,
    ) -> "Submission":
        return cls(
            id=submission_id,
            n_attempts=n_attempts,
            strategy=strategy,
            confidence=confidence,
            agent=agent,
            model=model,
            progress=Progress(attempts_total=n_attempts if strategy == Strategy.FIXED else 0),
        )
