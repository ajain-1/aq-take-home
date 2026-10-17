"""Accepts submissions and runs them on a bounded worker pool, resuming any left
unfinished by a previous API process."""

import logging
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor

from runner import bundle
from runner.config import Settings
from runner.models import Submission
from runner.run_task import TaskRunner, new_submission
from runner.store import SubmissionStore

logger = logging.getLogger(__name__)

SUPPORTED_AGENTS = ("terminus-1", "oracle", "nop")


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

    def submit(self, archive: bytes, n_attempts: int | None, agent: str | None) -> Submission:
        n_attempts = self._settings.default_attempts if n_attempts is None else n_attempts
        agent = self._settings.agent if agent is None else agent
        if not 1 <= n_attempts <= self._settings.max_attempts:
            raise SubmissionRejected(f"n_attempts must be between 1 and {self._settings.max_attempts}")
        if agent not in SUPPORTED_AGENTS:
            raise SubmissionRejected(f"agent must be one of {', '.join(SUPPORTED_AGENTS)}")
        if len(archive) > self._settings.max_upload_bytes:
            raise SubmissionRejected(f"upload exceeds {self._settings.max_upload_bytes} bytes")

        submission = new_submission(uuid.uuid4().hex[:12], n_attempts, agent, self._settings)
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
