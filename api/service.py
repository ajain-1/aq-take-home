"""Accepts submissions and runs them on a bounded worker pool, resuming any left
unfinished by a previous API process."""

import logging
import shutil
import uuid
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

        model = self._settings.model if self._settings.requires_model(agent) else None
        submission = Submission.create(
            uuid.uuid4().hex[:12], n_attempts, agent, model, strategy=strategy, confidence=confidence
        )
        paths = self._runner.paths(submission.id)
        paths.root.mkdir(parents=True)
        paths.upload.write_bytes(archive)

        # Validate synchronously so a malformed task is rejected with a 4xx instead of
        # surfacing later as a failed submission.
        try:
            bundle.extract_zip(paths.upload, paths.tasks, self._settings.max_extracted_bytes)
            submission.task_id = bundle.load_task_spec(bundle.locate_task_dir(paths.tasks)).task_id
        except bundle.InvalidTaskBundle as e:
            shutil.rmtree(paths.root, ignore_errors=True)
            raise SubmissionRejected(str(e)) from e

        self._store.save(submission)
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
