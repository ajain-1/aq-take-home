"""Accepts submissions and runs them on a bounded worker pool, resuming any left
unfinished by a previous API process."""

import logging
from concurrent.futures import ThreadPoolExecutor

from runner import bundle
from runner.config import AGENTS, Settings
from runner.learnability import TARGET_RUNS
from runner.models import Strategy, Submission
from runner.run_task import TaskRunner
from runner.store import SubmissionStore

logger = logging.getLogger(__name__)


class SubmissionRejected(ValueError):
    pass


class SubmissionService:
    def __init__(self, store: SubmissionStore, runner: TaskRunner, settings: Settings):
        self._store = store
        self._runner = runner
        self._settings = settings
        self._pool = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_submissions, thread_name_prefix="submission"
        )

    def submit(
        self,
        archive: bytes,
        n_attempts: int | None,
        agent: str | None,
        strategy: str | None = None,
        confidence: float | None = None,
        validation_id: str | None = None,
    ) -> Submission:
        agent = agent or self._settings.agent
        try:
            strategy = Strategy(strategy or Strategy.FIXED)
        except ValueError:
            raise SubmissionRejected(f"strategy must be one of {', '.join(Strategy)}") from None
        if strategy == Strategy.ADAPTIVE:
            if n_attempts is not None:
                raise SubmissionRejected("n_attempts is chosen by the adaptive strategy; omit it")
            n_attempts = TARGET_RUNS
        n_attempts = n_attempts or self._settings.default_attempts
        confidence = 1.0 if confidence is None else confidence
        if not 1 <= n_attempts <= self._settings.max_attempts:
            raise SubmissionRejected(f"n_attempts must be between 1 and {self._settings.max_attempts}")
        if not 0.5 < confidence <= 1.0:
            raise SubmissionRejected("confidence must be in (0.5, 1.0]; 1.0 means exact")
        if agent not in AGENTS:
            raise SubmissionRejected(f"agent must be one of {', '.join(AGENTS)}")
        if len(archive) > self._settings.max_upload_bytes:
            raise SubmissionRejected(f"upload exceeds {self._settings.max_upload_bytes} bytes")

        try:
            submission = self._runner.create(
                archive,
                n_attempts,
                agent,
                strategy=strategy,
                confidence=confidence,
                validation_id=validation_id,
            )
        except bundle.InvalidTaskBundle as e:
            raise SubmissionRejected(str(e)) from e

        self._enqueue(submission.id)
        return submission

    def resume_unfinished(self) -> None:
        for submission in self._store.list_unfinished():
            logger.info("resuming submission %s (phase %s)", submission.id, submission.progress.phase)
            self._enqueue(submission.id)

    def shutdown(self) -> None:
        self._runner.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _enqueue(self, submission_id: str) -> None:
        future = self._pool.submit(self._runner.run, submission_id)
        future.add_done_callback(lambda f: f.exception() and logger.error(
            "submission %s worker died", submission_id, exc_info=f.exception()
        ))
