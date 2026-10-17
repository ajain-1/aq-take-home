"""Pre-submission validation: static checks -> image probe -> oracle and nop runs.

Cheap stages gate expensive ones: static errors stop the pipeline (unless forced)
before any image is built, and the oracle/nop runs reuse the regular submission
pipeline, so they get the same Jobs, retries, cleanup, and restart recovery.
"""

import logging
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from runner import bundle
from runner.config import Settings
from runner.models import Status, utcnow
from runner.paths import SubmissionPaths
from runner.run_task import TaskRunner
from runner.validation import image_probe, reference_runs, static_checks
from runner.validation.models import Stage, Validation, ValidationMode
from runner.validation.store import ValidationStore

logger = logging.getLogger(__name__)

ORACLE_ATTEMPTS = 2
STATIC_ERRORS_NOTE = "static checks failed; skipped image probe and reference runs"


class Validator:
    def __init__(self, store: ValidationStore, runner: TaskRunner, settings: Settings):
        self._store = store
        self._runner = runner
        self._settings = settings

    def get(self, validation_id: str) -> Validation:
        return self._store.get(validation_id)

    def list_unfinished(self) -> list[Validation]:
        return self._store.list_unfinished()

    def root(self, validation_id: str) -> Path:
        return self._settings.data_dir / "validations" / validation_id

    def create(
        self,
        archive: bytes,
        mode: ValidationMode,
        force: bool = False,
        gates_submission_id: str | None = None,
    ) -> Validation:
        """Run the static stage synchronously; raises InvalidTaskBundle for unreadable ZIPs.

        A gating validation is linked to its submission from the start, so a crash can
        never leave it running on its own for a submission that was never created."""
        validation = Validation(
            id=uuid.uuid4().hex[:12], mode=mode, force=force, gates_submission_id=gates_submission_id
        )
        paths = SubmissionPaths(self.root(validation.id))
        paths.root.mkdir(parents=True)
        paths.upload.write_bytes(archive)
        try:
            bundle.extract_zip(paths.upload, paths.tasks, self._settings.max_extracted_bytes)
            task_dir = bundle.locate_task_dir(paths.tasks)
        except bundle.InvalidTaskBundle:
            shutil.rmtree(paths.root, ignore_errors=True)
            raise

        _, findings = static_checks.run_static_checks(task_dir)
        validation.task_id = task_dir.name
        validation.findings = findings
        validation.stages_run = [Stage.STATIC]
        if mode == ValidationMode.STATIC or (validation.has_errors and not force):
            validation.status = Status.COMPLETED
            validation.finished_at = utcnow()
            if mode == ValidationMode.FULL:
                validation.note = STATIC_ERRORS_NOTE
        self._store.save(validation)
        return validation

    def active_child_submission_ids(self) -> set[str]:
        """Oracle/nop submissions owned by unfinished validations, which resume them."""
        return {
            child_id
            for validation in self._store.list_unfinished()
            for child_id in (validation.oracle_submission_id, validation.nop_submission_id)
            if child_id
        }

    def run(self, validation_id: str) -> Validation:
        """Run the remaining stages; idempotent and safe to resume after a restart."""
        validation = self._store.get(validation_id)
        if validation.status.is_terminal:
            return validation
        self._store.update(validation_id, lambda v: setattr(v, "status", Status.RUNNING))
        try:
            self._run_dynamic_stages(validation_id)
        except Exception as e:
            logger.exception("validation %s crashed", validation_id)
            return self._finish(validation_id, error=f"internal error: {e}")
        return self._store.get(validation_id)

    def _run_dynamic_stages(self, validation_id: str) -> None:
        validation = self._store.get(validation_id)
        task_dir = bundle.locate_task_dir(self.root(validation_id) / "tasks")
        context, _ = static_checks.load_context(task_dir)

        if validation.has_errors and not validation.force:
            self._finish(validation_id, note=STATIC_ERRORS_NOTE)
            return
        if context.spec is None:
            self._finish(validation_id, note="task.yaml is invalid; skipped image probe and reference runs")
            return

        if Stage.IMAGE_PROBE not in validation.stages_run:
            findings = list(
                image_probe.probe_image(
                    context,
                    f"aq-validate-{validation_id}:latest",
                    self.root(validation_id) / "build.log",
                    self._settings.build_timeout_sec,
                )
            )
            self._record(validation_id, [Stage.IMAGE_PROBE], findings)

        oracle_id, nop_id = self._reference_submissions(validation_id, context.solution is not None)
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"validate-{validation_id}") as pool:
            oracle = pool.submit(self._runner.run, oracle_id) if oracle_id else None
            nop = pool.submit(self._runner.run, nop_id)
            oracle_results, nop_results = (oracle.result() if oracle else None), nop.result()

        if (oracle and oracle_results is None) or nop_results is None:
            return  # runner is shutting down; the validation resumes on restart

        if oracle:
            self._record(
                validation_id,
                [Stage.ORACLE],
                list(reference_runs.oracle_findings(oracle_results, context.spec.max_test_timeout_sec)),
            )
        self._record(validation_id, [Stage.NOP], list(reference_runs.nop_findings(nop_results)))
        self._finish(validation_id)

    def _record(self, validation_id: str, stages: list[Stage], findings: list) -> None:
        def mutate(v: Validation) -> None:
            v.findings.extend(findings)
            v.stages_run.extend(stages)

        self._store.update(validation_id, mutate)

    def _reference_submissions(self, validation_id: str, has_solution: bool) -> tuple[str | None, str]:
        validation = self._store.get(validation_id)
        archive = SubmissionPaths(self.root(validation_id)).upload.read_bytes()
        oracle_id = validation.oracle_submission_id
        if has_solution and oracle_id is None:
            oracle_id = self._runner.create(archive, ORACLE_ATTEMPTS, "oracle").id
        nop_id = validation.nop_submission_id or self._runner.create(archive, 1, "nop").id

        def record(v: Validation) -> None:
            v.oracle_submission_id, v.nop_submission_id = oracle_id, nop_id

        self._store.update(validation_id, record)
        return oracle_id, nop_id

    def _finish(self, validation_id: str, note: str | None = None, error: str | None = None) -> Validation:
        """`note` explains skipped stages; `error` means the validation itself broke."""

        def mutate(v: Validation) -> None:
            v.status = Status.FAILED if error else Status.COMPLETED
            v.note, v.error = note, error
            v.finished_at = utcnow()

        return self._store.update(validation_id, mutate)
