from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from runner.models import Status, utcnow


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Stage(StrEnum):
    STATIC = "static"
    IMAGE_PROBE = "image_probe"
    ORACLE = "oracle"
    NOP = "nop"


class Finding(BaseModel):
    check: str
    stage: Stage
    severity: Severity
    message: str
    details: dict[str, Any] | None = None


class ValidationMode(StrEnum):
    STATIC = "static"
    FULL = "full"


class Validation(BaseModel):
    """A validation run: static checks, then optionally an image probe and
    oracle/nop runs executed as ordinary submissions."""

    id: str
    task_id: str | None = None
    mode: ValidationMode
    force: bool = False
    status: Status = Status.QUEUED
    findings: list[Finding] = []
    stages_run: list[Stage] = []
    oracle_submission_id: str | None = None
    nop_submission_id: str | None = None
    gates_submission_id: str | None = None
    note: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None

    @property
    def passed(self) -> bool:
        return self.status == Status.COMPLETED and not self.has_errors

    @property
    def has_errors(self) -> bool:
        return any(finding.severity == Severity.ERROR for finding in self.findings)

    def report(self) -> dict[str, Any]:
        counts = {severity.value: 0 for severity in Severity}
        for finding in self.findings:
            counts[finding.severity] += 1
        return {
            "validation_id": self.id,
            "task_id": self.task_id,
            "mode": self.mode,
            "status": self.status,
            "passed": self.passed,
            "counts": counts,
            "stages_run": self.stages_run,
            "findings": [finding.model_dump(exclude_none=True) for finding in self.findings],
            "oracle_submission_id": self.oracle_submission_id,
            "nop_submission_id": self.nop_submission_id,
            "gates_submission_id": self.gates_submission_id,
            "note": self.note,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
