"""Accepts submissions and runs them on a bounded worker pool, resuming any left
unfinished by a previous API process."""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from runner import bundle
from runner.config import AGENTS, Settings
from runner.learnability import TARGET_RUNS
from runner.models import Phase, Strategy, Submission
from runner.run_task import TaskRunner, new_submission_id
from runner.store import SubmissionStore
from runner.validation.models import Validation, ValidationMode
from runner.validation.pipeline import Validator

logger = logging.getLogger(__name__)


class SubmissionRejected(ValueError):
    def __init__(self, message: str, report: dict | None = None):
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
        self,
        archive: bytes,
        n_attempts: int | None = None,
        agent: str | None = None,
        strategy: str | None = None,
        confidence: float | None = None,
        validation: ValidationMode | None = None,
    ) -> Submission:
        """Check every parameter before creating anything, then create the submission
        (and its gating validation, if any) and queue it."""
        agent = self._settings.agent if agent is None else agent
        try:
            strategy = Strategy(strategy or Strategy.FIXED)
        except ValueError:
            raise SubmissionRejected(f"strategy must be one of {', '.join(Strategy)}") from None
        if strategy == Strategy.ADAPTIVE:
            if n_attempts is not None:
                raise SubmissionRejected("n_attempts is chosen by the adaptive strategy; omit it")
            n_attempts = TARGET_RUNS
        n_attempts = self._settings.default_attempts if n_attempts is None else n_attempts
        confidence = 1.0 if confidence is None else confidence
        if not 1 <= n_attempts <= self._settings.max_attempts:
            raise SubmissionRejected(f"n_attempts must be between 1 and {self._settings.max_attempts}")
        if not 0.5 < confidence <= 1.0:
            raise SubmissionRejected("confidence must be in (0.5, 1.0]; 1.0 means exact")
        if agent not in AGENTS:
            raise SubmissionRejected(f"agent must be one of {', '.join(AGENTS)}")
        if len(archive) > self._settings.max_upload_bytes:
            raise SubmissionRejected(f"upload exceeds {self._settings.max_upload_bytes} bytes")

        submission_id = new_submission_id()
        try:
            gate = self._create_gate(archive, validation, submission_id) if validation else None
            submission = self._runner.create(
                archive,
                n_attempts,
                agent,
                strategy=strategy,
                confidence=confidence,
                submission_id=submission_id,
            )
        except bundle.InvalidTaskBundle as e:
            raise SubmissionRejected(str(e)) from e

        if gate and not gate.status.is_terminal:

            def attach_gate(s: Submission) -> None:
                s.validation_id = gate.id
                s.progress.phase = Phase.VALIDATING

            submission = self._store.update(submission.id, attach_gate)
        self._enqueue(submission.id)
        return submission

    def resume_unfinished(self) -> None:
        # Oracle/nop runs of unfinished validations are resumed by their validation.
        owned_by_validations = self._validator.active_child_submission_ids()
        for submission in self._store.list_unfinished():
            if submission.id in owned_by_validations:
                continue
            logger.info("resuming submission %s (phase %s)", submission.id, submission.progress.phase)
            self._enqueue(submission.id)

    def shutdown(self) -> None:
        self._runner.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _create_gate(self, archive: bytes, mode: ValidationMode, submission_id: str) -> Validation:
        """Static errors reject the submission now; a full validation runs before the agents."""
        gates = submission_id if mode == ValidationMode.FULL else None
        gate = self._validator.create(archive, mode, gates_submission_id=gates)
        if gate.has_errors:
            raise SubmissionRejected("task failed static validation", gate.report())
        return gate

    def _execute(self, submission_id: str) -> dict[str, Any] | None:
        submission = self._store.get(submission_id)
        if submission.validation_id and not submission.status.is_terminal:
            gate = self._validator.run(submission.validation_id)
            if not gate.status.is_terminal:
                return None  # shutting down; resumes on restart
            if gate.error:
                return self._runner.fail(submission_id, f"validation could not complete: {gate.error}")
            if not gate.passed:
                return self._runner.fail(submission_id, f"task failed validation; see /validations/{gate.id}")
        return self._runner.run(submission_id)

    def _enqueue(self, submission_id: str) -> None:
        future = self._pool.submit(self._execute, submission_id)
        future.add_done_callback(
            lambda f: f.exception()
            and logger.error("submission %s worker died", submission_id, exc_info=f.exception())
        )
