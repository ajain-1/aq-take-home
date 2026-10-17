"""Task quality validation: standalone `/validate` runs and the optional gate on `/submit`."""

import logging
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum

from runner import bundle
from runner.config import Settings
from runner.models import Submission
from runner.validation.models import Validation, ValidationMode
from runner.validation.pipeline import Validator

logger = logging.getLogger(__name__)
MAX_CONCURRENT_VALIDATIONS = 2


class ValidationGate(StrEnum):
    NONE = "none"
    STATIC = "static"
    FULL = "full"


class ValidationRejected(ValueError):
    def __init__(self, message: str, report: dict | None = None):
        super().__init__(message)
        self.report = report


class ValidationService:
    def __init__(self, validator: Validator, settings: Settings):
        self._validator = validator
        self._settings = settings
        self._pool = ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_VALIDATIONS, thread_name_prefix="validation"
        )

    def validate(self, archive: bytes, mode: ValidationMode, force: bool = False) -> Validation:
        if len(archive) > self._settings.max_upload_bytes:
            raise ValidationRejected(f"upload exceeds {self._settings.max_upload_bytes} bytes")
        try:
            validation = self._validator.create(archive, mode, force)
        except bundle.InvalidTaskBundle as e:
            raise ValidationRejected(str(e)) from e
        if not validation.status.is_terminal:
            self._pool.submit(self._validator.run, validation.id)
        return validation

    def check_gate(self, archive: bytes, gate: ValidationGate) -> Validation | None:
        """Static errors reject the submission now; a full gate is attached and runs
        before the agents (see GatedTaskRunner)."""
        if gate == ValidationGate.NONE:
            return None
        mode = ValidationMode.STATIC if gate == ValidationGate.STATIC else ValidationMode.FULL
        try:
            validation = self._validator.create(archive, mode)
        except bundle.InvalidTaskBundle as e:
            raise ValidationRejected(str(e)) from e
        if validation.has_errors:
            raise ValidationRejected("task failed static validation", validation.report())
        return validation

    @staticmethod
    def pending_gate_id(validation: Validation | None) -> str | None:
        """The validation a submission must wait for, if any."""
        return validation.id if validation and not validation.status.is_terminal else None

    def mark_gating(self, submission: Submission) -> None:
        if submission.validation_id:
            self._validator.mark_gating(submission.validation_id, submission.id)

    def get(self, validation_id: str) -> Validation:
        return self._validator.get(validation_id)

    def resume_unfinished(self) -> None:
        for validation in self._validator.list_unfinished():
            if validation.gates_submission_id is None:
                logger.info("resuming validation %s", validation.id)
                self._pool.submit(self._validator.run, validation.id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
