"""On-disk layout of a submission, including the terminal-bench output written by its pods.

Every module that reads or writes submission artifacts goes through this one definition.
"""

from dataclasses import dataclass
from pathlib import Path

from runner.trial_entrypoint import TASK_CONTAINER_EVENTS_FILE


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

    @property
    def insights_json(self) -> Path:
        return self.root / "insights.json"

    @property
    def insights_markdown(self) -> Path:
        return self.root / "insights.md"

    def task(self, task_id: str) -> Path:
        return self.tasks / task_id

    def attempt(self, index: int) -> Path:
        return self.runs / f"attempt-{index}"

    def task_container_events(self, index: int) -> Path:
        return self.attempt(index) / TASK_CONTAINER_EVENTS_FILE

    def trial(self, index: int, task_id: str, finished_only: bool = True) -> Path | None:
        """The terminal-bench trial directory of an attempt. A finished trial has a
        results.json; a running one already streams its agent logs."""
        return find_trial_dir(self.attempt(index), task_id, finished_only)


def find_trial_dir(attempt_dir: Path, task_id: str, finished_only: bool = True) -> Path | None:
    finished = sorted(attempt_dir.glob(f"*/{task_id}/*/results.json"))
    if finished:
        return finished[-1].parent
    if finished_only:
        return None
    return next((p for p in sorted(attempt_dir.glob(f"*/{task_id}/*")) if p.is_dir()), None)
