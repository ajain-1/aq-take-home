"""Standalone task quality validation (`/validate`). Gating a submission on a validation
is handled by SubmissionService."""

import logging
from concurrent.futures import ThreadPoolExecutor

from runner import bundle
from runner.config import Settings
from runner.validation.models import Validation, ValidationMode
from runner.validation.pipeline import Validator

logger = logging.getLogger(__name__)


class ValidationRejected(ValueError):
    pass


class ValidationService:
    def __init__(self, validator: Validator, settings: Settings):
        self._validator = validator
        self._settings = settings
        self._pool = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_validations, thread_name_prefix="validation"
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

    def get(self, validation_id: str) -> Validation:
        return self._validator.get(validation_id)

    def resume_unfinished(self) -> None:
        for validation in self._validator.list_unfinished():
            # A gating validation is resumed by the submission it gates.
            if validation.gates_submission_id is None:
                logger.info("resuming validation %s", validation.id)
                self._pool.submit(self._validator.run, validation.id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
