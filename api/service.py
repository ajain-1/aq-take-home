"""Accepts submissions and validations and runs them on a bounded worker pool,
resuming any left unfinished by a previous API process."""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from typing import Any

from runner import bundle
from runner.config import Settings
from runner.models import Phase, Status, Submission, utcnow
from runner.run_task import TaskRunner
from runner.store import SubmissionStore
from runner.validation.models import Validation, ValidationMode
from runner.validation.pipeline import Validator

logger = logging.getLogger(__name__)

SUPPORTED_AGENTS = ("terminus-1", "oracle", "nop")


class ValidationGate(StrEnum):
    NONE = "none"
    STATIC = "static"
    FULL = "full"


class SubmissionRejected(ValueError):
    def __init__(self, message: str, report: dict[str, Any] | None = None):
        super().__init__(message)
        self.report = report


class SubmissionService:
    def __init__(self, store: SubmissionStore, runner: TaskRunner, validator: Validator, settings: Settings):
        self._store = store
        self._runner = runner
        self._validator = validator
        self._settings = settings
        self._pool = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_submissions, thread_name_prefix="submission"
        )

    def submit(
        self, archive: bytes, n_attempts: int | None, agent: str | None, gate: ValidationGate = ValidationGate.NONE
    ) -> Submission:
        n_attempts = n_attempts or self._settings.default_attempts
        agent = agent or self._settings.agent
        if not 1 <= n_attempts <= self._settings.max_attempts:
            raise SubmissionRejected(f"n_attempts must be between 1 and {self._settings.max_attempts}")
        if agent not in SUPPORTED_AGENTS:
            raise SubmissionRejected(f"agent must be one of {', '.join(SUPPORTED_AGENTS)}")
        self._check_size(archive)

        validation = None
        if gate != ValidationGate.NONE:
            mode = ValidationMode.STATIC if gate == ValidationGate.STATIC else ValidationMode.FULL
            validation = self._create_validation(archive, mode)
            if validation.has_errors:
                raise SubmissionRejected("task failed static validation", validation.report())

        try:
            submission = self._runner.create(archive, n_attempts, agent)
        except bundle.InvalidTaskBundle as e:
            raise SubmissionRejected(str(e)) from e

        if validation and validation.mode == ValidationMode.FULL:
            def link(s: Submission) -> None:
                s.validation_id = validation.id
                s.progress.phase = Phase.VALIDATING

            submission = self._store.update(submission.id, link)
        self._enqueue(self._run_submission, submission.id)
        return submission

    def validate(self, archive: bytes, mode: ValidationMode, force: bool) -> Validation:
        self._check_size(archive)
        validation = self._create_validation(archive, mode, force)
        if mode == ValidationMode.FULL:
            self._enqueue(self._validator.run, validation.id)
        return validation

    def resume_unfinished(self) -> None:
        gating = set()
        for submission in self._store.list_unfinished():
            logger.info("resuming submission %s (phase %s)", submission.id, submission.progress.phase)
            gating.add(submission.validation_id)
            self._enqueue(self._run_submission, submission.id)
        for validation in self._validator.list_unfinished():
            if validation.id not in gating:
                logger.info("resuming validation %s", validation.id)
                self._enqueue(self._validator.run, validation.id)

    def shutdown(self) -> None:
        self._runner.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _run_submission(self, submission_id: str) -> None:
        """Run the full validation gate first, if one is attached, then the agents."""
        submission = self._store.get(submission_id)
        if submission.validation_id and not submission.status.is_terminal:
            validation = self._validator.run(submission.validation_id)
            if not validation.status.is_terminal:
                return
            if not validation.passed:
                self._reject_after_validation(submission_id, validation)
                return
        self._runner.run(submission_id)

    def _reject_after_validation(self, submission_id: str, validation: Validation) -> None:
        def mutate(s: Submission) -> None:
            s.status = Status.FAILED
            s.progress.phase = Phase.DONE
            s.error = f"task failed validation; see /validations/{validation.id}"
            s.finished_at = utcnow()

        self._store.update(submission_id, mutate)

    def _create_validation(self, archive: bytes, mode: ValidationMode, force: bool = False) -> Validation:
        try:
            return self._validator.create(archive, mode, force)
        except bundle.InvalidTaskBundle as e:
            raise SubmissionRejected(str(e)) from e

    def _check_size(self, archive: bytes) -> None:
        if len(archive) > self._settings.max_upload_bytes:
            raise SubmissionRejected(f"upload exceeds {self._settings.max_upload_bytes} bytes")

    def _enqueue(self, work: Callable[[str], Any], item_id: str) -> None:
        future = self._pool.submit(work, item_id)
        future.add_done_callback(lambda f: f.exception() and logger.error(
            "worker for %s died", item_id, exc_info=f.exception()
        ))
