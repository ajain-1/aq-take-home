"""
Task Runner

Drives a submission through prepare -> build -> waves of attempts -> collect -> cleanup.
A wave is one Indexed Job; the fixed strategy runs a single wave of n attempts, the
adaptive strategy keeps launching waves until the learnability class is decided.
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

from runner import bundle, docker_ops, learnability, results
from runner.config import RESOURCE_CLASSES, Settings, settings as default_settings
from runner.k8s import JobSnapshot, KubeClient, build_job_manifest, job_deadline_sec, job_name
from runner.models import (
    AttemptProgress,
    Phase,
    Progress,
    Status,
    Strategy,
    Submission,
    TaskSpec,
    Wave,
    utcnow,
)
from runner.store import SubmissionStore

logger = logging.getLogger(__name__)

WAIT_GRACE_SEC = 120
MODEL_FREE_AGENTS = {"oracle", "nop"}


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
    def __init__(self, store: SubmissionStore, kube: KubeClient, settings: Settings = default_settings):
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
            self._build(submission, spec, paths)
            self._sync_credentials()
            while wave := self._next_wave(submission_id, spec, paths):
                self._run_wave(submission_id, spec, paths, wave)
            outcome = self._collect(submission_id, spec, paths)
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

    def _build(self, submission: Submission, spec: TaskSpec, paths: SubmissionPaths) -> None:
        self._set_phase(submission.id, Phase.BUILDING_IMAGE)
        tag = task_image_tag(submission.id)
        with self._build_slots:
            self._raise_if_stopping()
            docker_ops.ensure_runner_image(paths.build_log, self._settings.build_timeout_sec)
            if not docker_ops.image_exists(tag):
                docker_ops.build_task_image(paths.tasks / spec.task_id, tag, paths.build_log, self._settings.build_timeout_sec)

    def _sync_credentials(self) -> None:
        credentials = {k: os.environ[k] for k in self._settings.llm_secret_keys if os.environ.get(k)}
        if credentials:
            self._kube.upsert_secret(self._settings.llm_secret_name, credentials)

    def _next_wave(self, submission_id: str, spec: TaskSpec, paths: SubmissionPaths) -> Wave | None:
        """The wave to run next: an unfinished one being resumed, or a newly planned one."""
        submission = self._store.get(submission_id)
        waves = submission.progress.waves
        if waves and not waves[-1].done:
            return waves[-1]

        launched = submission.progress.attempts_launched
        if submission.strategy == Strategy.FIXED:
            size = 0 if waves else submission.n_attempts
        else:
            outcomes = [results.attempt_resolved(paths.attempt(i), spec.task_id) for i in range(launched)]
            passes = sum(1 for outcome in outcomes if outcome is True)
            failures = sum(1 for outcome in outcomes if outcome is False)
            size = learnability.next_wave_size(
                passes,
                failures,
                launched,
                max_launches=learnability.TARGET_RUNS + self._settings.adaptive_extra_launches,
                max_wave=self._settings.adaptive_max_wave,
                confidence=submission.confidence,
            )
        if size == 0:
            return None

        wave = Wave(index=len(waves), offset=launched, size=size)

        def mutate(s: Submission) -> None:
            s.progress.waves.append(wave)
            s.progress.attempts_total = launched + size

        self._store.update(submission_id, mutate)
        return wave

    def _run_wave(self, submission_id: str, spec: TaskSpec, paths: SubmissionPaths, wave: Wave) -> None:
        submission = self._set_phase(submission_id, Phase.LAUNCHING)
        paths.runs.mkdir(parents=True, exist_ok=True)
        manifest = build_job_manifest(
            submission_id=submission_id,
            spec=spec,
            wave=wave,
            runner_image=docker_ops.ensure_runner_image(paths.build_log, self._settings.build_timeout_sec),
            task_root=paths.tasks,
            output_root=paths.runs,
            agent=submission.agent,
            model=submission.model,
            resources=RESOURCE_CLASSES[spec.resource_class],
            settings=self._settings,
        )
        self._kube.create_job(manifest)
        self._wait(submission_id, spec, wave)
        self._save_pod_logs(submission_id, paths, wave)

        def mark_done(s: Submission) -> None:
            s.progress.waves[wave.index].done = True

        self._store.update(submission_id, mark_done)
        self._kube.delete_job(job_name(submission_id, wave.index))

    def _wait(self, submission_id: str, spec: TaskSpec, wave: Wave) -> None:
        self._set_phase(submission_id, Phase.RUNNING_ATTEMPTS)
        name = job_name(submission_id, wave.index)
        deadline = time.monotonic() + job_deadline_sec(spec, self._settings) + WAIT_GRACE_SEC

        while True:
            snapshot = self._kube.snapshot(name, wave)
            self._record_attempts(submission_id, snapshot)
            if not snapshot.exists or snapshot.finished:
                return
            if reason := snapshot.fatal_reason:
                raise ExecutionError(f"attempt pods cannot start: {reason}")
            if time.monotonic() > deadline:
                logger.warning("submission %s exceeded its deadline; stopping job %s", submission_id, name)
                self._kube.delete_job(name)
                return
            if self._stopping.wait(self._settings.poll_interval_sec):
                raise Interrupted

    def _record_attempts(self, submission_id: str, snapshot: JobSnapshot) -> None:
        if not snapshot.attempts:
            return

        def mutate(s: Submission) -> None:
            updated = {attempt.index: attempt for attempt in snapshot.attempts}
            merged = {attempt.index: attempt for attempt in s.progress.attempts} | updated
            s.progress.attempts = [merged[index] for index in sorted(merged)]

        self._store.update(submission_id, mutate)

    def _save_pod_logs(self, submission_id: str, paths: SubmissionPaths, wave: Wave) -> None:
        submission = self._store.get(submission_id)
        for attempt in submission.progress.attempts:
            in_wave = wave.offset <= attempt.index < wave.offset + wave.size
            if in_wave and attempt.pod and (log := self._kube.pod_log(attempt.pod)):
                paths.attempt(attempt.index).mkdir(parents=True, exist_ok=True)
                (paths.attempt(attempt.index) / "pod.log").write_text(log)

    def _collect(self, submission_id: str, spec: TaskSpec, paths: SubmissionPaths) -> dict[str, Any]:
        submission = self._set_phase(submission_id, Phase.COLLECTING_RESULTS)
        progress = {a.index: a for a in submission.progress.attempts}
        attempts = [
            results.collect_attempt(
                paths.attempt(index), spec.task_id, progress.get(index, AttemptProgress(index=index)), self._settings.data_dir
            )
            for index in range(submission.progress.attempts_launched)
        ]

        finished_at = utcnow()
        outcome = {
            "submission_id": submission.id,
            "task_id": spec.task_id,
            "agent": submission.agent,
            "model": submission.model,
            **results.aggregate(attempts),
            "learnability": results.learnability(attempts, submission.strategy, submission.confidence, self._settings),
            "started_at": submission.started_at.isoformat() if submission.started_at else None,
            "finished_at": finished_at.isoformat(),
            "execution_time_sec": (
                round((finished_at - submission.started_at).total_seconds(), 2) if submission.started_at else None
            ),
            "waves": [wave.model_dump(exclude={"done"}) for wave in submission.progress.waves],
            "attempts": attempts,
        }
        all_errored = outcome["summary"]["completed_attempts"] == 0
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
        for step in (
            lambda: self._kube.delete_submission_jobs(submission_id),
            lambda: docker_ops.remove_labelled_resources(f"aq.submission={submission_id}"),
            lambda: docker_ops.remove_images(task_image_tag(submission_id), f"{task_image_tag(submission_id)}-base"),
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
    store = SubmissionStore(default_settings.db_path)
    runner = TaskRunner(store, KubeClient(default_settings.namespace))
    paths = runner.paths(submission_id)
    paths.root.mkdir(parents=True, exist_ok=True)
    if Path(zip_path).resolve() != paths.upload.resolve():
        shutil.copyfile(zip_path, paths.upload)
    try:
        store.get(submission_id)
    except KeyError:
        store.save(new_submission(submission_id, default_settings.default_attempts, default_settings.agent, default_settings))
    return runner.run(submission_id) or {}


def new_submission(
    submission_id: str,
    n_attempts: int,
    agent: str,
    settings: Settings,
    strategy: Strategy = Strategy.FIXED,
    confidence: float = 1.0,
) -> Submission:
    return Submission(
        id=submission_id,
        n_attempts=n_attempts,
        strategy=strategy,
        confidence=confidence,
        agent=agent,
        model=None if agent in MODEL_FREE_AGENTS else settings.model,
        progress=Progress(attempts_total=n_attempts if strategy == Strategy.FIXED else 0),
    )
