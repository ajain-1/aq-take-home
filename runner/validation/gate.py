from typing import Any

from runner.config import Settings
from runner.k8s import KubeClient
from runner.models import Phase, Status, Submission, utcnow
from runner.run_task import TaskRunner
from runner.store import SubmissionStore
from runner.validation.pipeline import Validator
from runner.validation.store import ValidationStore


class GatedTaskRunner(TaskRunner):
    """A TaskRunner that, for submissions linked to a full validation, runs the
    validation first and only spends agent compute if it passes."""

    def __init__(
        self, store: SubmissionStore, kube: KubeClient, validations: ValidationStore, settings: Settings
    ):
        super().__init__(store, kube, settings)
        self.validator = Validator(validations, self, settings)

    def run(self, submission_id: str) -> dict[str, Any] | None:
        submission = self._store.get(submission_id)
        if submission.validation_id and not submission.status.is_terminal:
            validation = self.validator.run(submission.validation_id)
            if not validation.status.is_terminal:
                return None
            if not validation.passed:
                return self._reject(submission_id, validation.id)
        return super().run(submission_id)

    def _reject(self, submission_id: str, validation_id: str) -> None:
        def mutate(s: Submission) -> None:
            s.status = Status.FAILED
            s.progress.phase = Phase.DONE
            s.error = f"task failed validation; see /validations/{validation_id}"
            s.finished_at = utcnow()

        self._store.update(submission_id, mutate)
