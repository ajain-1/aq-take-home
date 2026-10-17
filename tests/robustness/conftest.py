import io
import sys
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runner.config import Settings  # noqa: E402
from runner.k8s import JobSnapshot  # noqa: E402
from runner.models import AttemptProgress, AttemptState  # noqa: E402

TASK_YAML = """\
instruction: Write ok to /app/out.txt
difficulty: easy
max_agent_timeout_sec: {agent_timeout}
max_test_timeout_sec: {test_timeout}
resource_class: {resource_class}
"""


def task_files(
    agent_timeout: float = 30, test_timeout: float = 30, resource_class: str = "small"
) -> dict[str, str]:
    return {
        "task.yaml": TASK_YAML.format(
            agent_timeout=agent_timeout, test_timeout=test_timeout, resource_class=resource_class
        ),
        "Dockerfile": "FROM python:3.12-slim\nWORKDIR /app\n",
        "run-tests.sh": "#!/bin/bash\npytest $TEST_DIR/test_outputs.py -rA\n",
        "solution.sh": "#!/bin/bash\necho ok > /app/out.txt\n",
        "tests/test_outputs.py": "def test_ok():\n    assert True\n",
    }


def make_zip(entries: dict[str, str], symlinks: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o120777 << 16
            archive.writestr(info, target)
    return buffer.getvalue()


def task_zip(task_id: str = "tiny-task", **kwargs) -> bytes:
    return make_zip({f"{task_id}/{name}": content for name, content in task_files(**kwargs).items()})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return replace(
        Settings(),
        data_dir=tmp_path / "data",
        poll_interval_sec=0.01,
        attempt_overhead_sec=0,
        retries_per_attempt=0,
        max_concurrent_builds=1,
        runner_image="aq-runner:test",
    )


class FakeKube:
    """Stands in for KubeClient; snapshots are served from a scripted sequence."""

    def __init__(self, snapshots: list = ()):
        self.snapshots = list(snapshots)
        self.created: list[dict] = []
        self.deleted: list[str] = []

    def upsert_secret(self, name, data):
        pass

    def create_job(self, manifest):
        self.created.append(manifest)

    def delete_job(self, name):
        self.deleted.append(name)

    def pod_log(self, pod_name):
        return None

    def snapshot(self, name, n_attempts):
        item = self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]
        if isinstance(item, Exception):
            raise item
        return item


def running_snapshot(n_attempts: int = 1) -> JobSnapshot:
    return JobSnapshot(
        exists=True,
        attempts=[AttemptProgress(index=i, state=AttemptState.RUNNING) for i in range(n_attempts)],
    )


def finished_snapshot(n_attempts: int = 1) -> JobSnapshot:
    return JobSnapshot(
        exists=True,
        finished=True,
        attempts=[AttemptProgress(index=i, state=AttemptState.SUCCEEDED) for i in range(n_attempts)],
    )
