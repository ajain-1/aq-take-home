"""
Task Runner

Drives a submission through prepare -> build -> launch -> wait -> collect -> cleanup.
Every stage is idempotent, so a submission interrupted by an API restart can be
resumed by simply running it again with the same submission ID.
"""

import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kubernetes.client.exceptions import ApiException

from runner import bundle, docker_ops, results
from runner.config import RESOURCE_CLASSES, Settings
from runner.k8s import (
    JobSnapshot,
    KubeClient,
    api_error_message,
    build_job_manifest,
    job_deadline_sec,
    job_name,
)
from runner.models import AttemptProgress, AttemptState, Phase, Status, Submission, TaskSpec, utcnow
from runner.store import SubmissionNotFound, SubmissionStore

logger = logging.getLogger(__name__)

WAIT_GRACE_SEC = 120


class ExecutionError(RuntimeError):
    pass


class Interrupted(Exception):
    """Raised when the runner is shutting down; the submission is left resumable."""


@dataclass(frozen=True)
class SubmissionPaths:
    root: Path

    @property
    def upload(self) -> Path:
        return self.root / "upload.zip"

    @property
    def tasks(self) -> Path:
        return self.root / "tasks"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def build_log(self) -> Path:
        return self.root / "build.log"

    @property
    def results(self) -> Path:
        return self.root / "results.json"

    def attempt(self, index: int) -> Path:
        return self.runs / f"attempt-{index}"


def task_image_tag(submission_id: str) -> str:
    return f"aq-task-{submission_id}:latest"


class TaskRunner:
    def __init__(self, store: SubmissionStore, kube: KubeClient, settings: Settings):
        self._store = store
        self._kube = kube
        self._settings = settings
        self._build_slots = threading.Semaphore(settings.max_concurrent_builds)
        self._stopping = threading.Event()

    def stop(self) -> None:
        self._stopping.set()

    def paths(self, submission_id: str) -> SubmissionPaths:
        return SubmissionPaths(self._settings.submissions_dir / submission_id)

    def run(self, submission_id: str) -> dict[str, Any] | None:
        """Execute (or resume) a submission and return its structured results."""
        submission = self._store.update(submission_id, _mark_started)
        paths = self.paths(submission_id)
        try:
            spec = self._prepare(submission, paths)
            if submission.launched_at is None:
                runner_image = self._build(submission, spec, paths)
                self._launch(submission, spec, paths, runner_image)
            self._wait(submission, spec)
            outcome = self._collect(submission, spec, paths)
        except Interrupted:
            logger.info("submission %s interrupted; it will resume on restart", submission_id)
            return None
        except (bundle.InvalidTaskBundle, docker_ops.BuildError, ExecutionError) as e:
            outcome = self._fail(submission_id, str(e))
        except Exception as e:
            logger.exception("submission %s crashed", submission_id)
            outcome = self._fail(submission_id, f"internal error: {e}")

        self._cleanup(submission_id)
        return outcome

    def _set_phase(self, submission_id: str, phase: Phase) -> Submission:
        def mutate(s: Submission) -> None:
            s.status = Status.RUNNING
            s.progress.phase = phase

        return self._store.update(submission_id, mutate)

    def _prepare(self, submission: Submission, paths: SubmissionPaths) -> TaskSpec:
        self._set_phase(submission.id, Phase.PREPARING)
        already_prepared = submission.task_id and (paths.tasks / submission.task_id).is_dir()
        if not already_prepared:
            bundle.extract_zip(paths.upload, paths.tasks, self._settings.max_extracted_bytes)

        task_dir = bundle.locate_task_dir(paths.tasks)
        spec = bundle.load_task_spec(task_dir)
        if task_dir.parent != paths.tasks:
            shutil.move(task_dir, paths.tasks / spec.task_id)
            task_dir = paths.tasks / spec.task_id

        bundle.write_compose_file(
            task_dir, task_image_tag(submission.id), submission.id, RESOURCE_CLASSES[spec.resource_class]
        )
        self._store.update(submission.id, lambda s: setattr(s, "task_id", spec.task_id))
        return spec

    def _build(self, submission: Submission, spec: TaskSpec, paths: SubmissionPaths) -> str:
        """Build the task image and make sure the Job pod image exists; returns the latter."""
        self._set_phase(submission.id, Phase.BUILDING_IMAGE)
        tag = task_image_tag(submission.id)
        timeout = self._settings.build_timeout_sec
        with self._build_slots:
            self._raise_if_stopping()
            runner_image = self._settings.runner_image
            if runner_image is None:
                runner_image = docker_ops.ensure_runner_image(paths.build_log, timeout)
            if not docker_ops.image_exists(tag):
                docker_ops.build_task_image(paths.tasks / spec.task_id, tag, paths.build_log, timeout)
        return runner_image

    def _launch(
        self, submission: Submission, spec: TaskSpec, paths: SubmissionPaths, runner_image: str
    ) -> None:
        self._set_phase(submission.id, Phase.LAUNCHING)
        credentials = {k: os.environ[k] for k in self._settings.llm_secret_keys if os.environ.get(k)}
        if credentials:
            self._kube.upsert_secret(self._settings.llm_secret_name, credentials)

        paths.runs.mkdir(parents=True, exist_ok=True)
        manifest = build_job_manifest(
            submission_id=submission.id,
            spec=spec,
            n_attempts=submission.n_attempts,
            runner_image=runner_image,
            submission_root=paths.root,
            task_root=paths.tasks,
            output_root=paths.runs,
            agent=submission.agent,
            model=submission.model,
            resources=RESOURCE_CLASSES[spec.resource_class],
            settings=self._settings,
        )
        try:
            self._kube.create_job(manifest)
        except ApiException as e:
            raise ExecutionError(f"Kubernetes rejected the Job: {api_error_message(e)}") from e
        # Persisted so a resumed run re-attaches instead of re-running paid attempts,
        # even if the Job has since been garbage-collected.
        self._store.update(submission.id, lambda s: setattr(s, "launched_at", utcnow()))

    def _wait(self, submission: Submission, spec: TaskSpec) -> None:
        self._set_phase(submission.id, Phase.RUNNING_ATTEMPTS)
        name = job_name(submission.id)
        deadline = time.monotonic() + job_deadline_sec(spec, self._settings) + WAIT_GRACE_SEC

        while True:
            try:
                snapshot = self._kube.snapshot(name, submission.n_attempts)
            except Exception:
                logger.warning("could not read job %s; will retry", name, exc_info=True)
            else:
                self._record_attempts(submission.id, snapshot)
                if not snapshot.exists or snapshot.finished:
                    return
                if reason := snapshot.fatal_reason:
                    raise ExecutionError(f"attempt pods cannot start: {reason}")
            if time.monotonic() > deadline:
                logger.warning("submission %s exceeded its deadline; stopping job", submission.id)
                self._kube.delete_job(name)
                return
            if self._stopping.wait(self._settings.poll_interval_sec):
                raise Interrupted

    def _record_attempts(self, submission_id: str, snapshot: JobSnapshot) -> None:
        """Pods vanish when a Job fails (e.g. DeadlineExceeded), so merge each attempt with
        what earlier snapshots saw and attribute the Job's failure to unfinished attempts."""
        failure = snapshot.reason if snapshot.finished else None if snapshot.exists else "JobNotFound"

        def merge(attempt: AttemptProgress, previous: AttemptProgress | None) -> AttemptProgress:
            if previous is None:
                return attempt
            if not attempt.pods:
                return previous
            attempt.pods = previous.pods + [pod for pod in attempt.pods if pod not in previous.pods]
            return attempt

        def mutate(s: Submission) -> None:
            previous = {a.index: a for a in s.progress.attempts}
            attempts = [merge(a, previous.get(a.index)) for a in snapshot.attempts] or list(previous.values())
            if failure:
                for attempt in attempts:
                    if attempt.state != AttemptState.SUCCEEDED:
                        attempt.state, attempt.reason = AttemptState.FAILED, f"job failed: {failure}"
            s.progress.attempts = attempts

        if snapshot.attempts or failure:
            self._store.update(submission_id, mutate)

    def _collect(self, submission: Submission, spec: TaskSpec, paths: SubmissionPaths) -> dict[str, Any]:
        submission = self._set_phase(submission.id, Phase.COLLECTING_RESULTS)
        progress = {a.index: a for a in submission.progress.attempts}

        attempts = []
        for index in range(submission.n_attempts):
            attempt_progress = progress.get(index, AttemptProgress(index=index))
            self._save_pod_logs(attempt_progress, paths.attempt(index))
            attempt_dir = paths.attempt(index)
            attempts.append(
                results.collect_attempt(attempt_dir, spec.task_id, attempt_progress, self._settings.data_dir)
            )

        finished_at = utcnow()
        started_at = submission.started_at
        elapsed = round((finished_at - started_at).total_seconds(), 2) if started_at else None
        outcome = {
            "submission_id": submission.id,
            "task_id": spec.task_id,
            "agent": submission.agent,
            "model": submission.model,
            **results.aggregate(attempts),
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": finished_at.isoformat(),
            "execution_time_sec": elapsed,
            "attempts": attempts,
        }
        all_errored = outcome["summary"]["errored_attempts"] == len(attempts)
        status = Status.FAILED if all_errored else Status.COMPLETED
        outcome["status"] = status.value
        paths.results.write_text(json.dumps(outcome, indent=2))

        def mutate(s: Submission) -> None:
            s.status = status
            s.progress.phase = Phase.DONE
            s.results = outcome
            s.finished_at = finished_at
            if all_errored:
                s.error = "no attempt produced test results: " + "; ".join(
                    sorted({a.get("error") or "unknown" for a in attempts})
                )

        self._store.update(submission.id, mutate)
        return outcome

    def _save_pod_logs(self, attempt: AttemptProgress, attempt_dir: Path) -> None:
        """Keep the logs of every try, including retried pods, before the Job is deleted."""
        for try_number, pod in enumerate(attempt.pods):
            if log := self._kube.pod_log(pod):
                attempt_dir.mkdir(parents=True, exist_ok=True)
                (attempt_dir / f"pod-try-{try_number}.log").write_text(log)

    def _fail(self, submission_id: str, error: str) -> dict[str, Any]:
        logger.warning("submission %s failed: %s", submission_id, error)

        def mutate(s: Submission) -> None:
            s.status = Status.FAILED
            s.progress.phase = Phase.DONE
            s.error = error
            s.finished_at = utcnow()

        self._store.update(submission_id, mutate)
        return {"submission_id": submission_id, "status": Status.FAILED.value, "error": error}

    def _cleanup(self, submission_id: str) -> None:
        """Release cluster and Docker resources; safe to call repeatedly."""
        image = task_image_tag(submission_id)
        for step in (
            lambda: self._kube.delete_job(job_name(submission_id)),
            lambda: docker_ops.remove_labelled_resources(f"aq.submission={submission_id}"),
            lambda: docker_ops.remove_images(image, f"{image}-base"),
        ):
            try:
                step()
            except Exception:
                logger.exception("cleanup step failed for submission %s", submission_id)

    def _raise_if_stopping(self) -> None:
        if self._stopping.is_set():
            raise Interrupted


def _mark_started(submission: Submission) -> None:
    submission.status = Status.RUNNING
    submission.started_at = submission.started_at or utcnow()


def run_task(zip_path: str, submission_id: str) -> dict:
    """
    Execute a task and return structured test results.

    Args:
        zip_path: Absolute path to the task ZIP file
        submission_id: Unique submission identifier
    """
    settings = Settings.from_env()
    store = SubmissionStore(settings.db_path)
    runner = TaskRunner(store, KubeClient(settings.namespace), settings)
    paths = runner.paths(submission_id)
    paths.root.mkdir(parents=True, exist_ok=True)
    if Path(zip_path).resolve() != paths.upload.resolve():
        shutil.copyfile(zip_path, paths.upload)
    try:
        store.get(submission_id)
    except SubmissionNotFound:
        model = settings.model if settings.requires_model(settings.agent) else None
        store.save(Submission.create(submission_id, settings.default_attempts, settings.agent, model))
    return runner.run(submission_id) or {}
