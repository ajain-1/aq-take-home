"""Runs one agent attempt inside a Kubernetes Job pod.

The attempt index comes from the Indexed Job (JOB_COMPLETION_INDEX). A retried pod
starts from a clean slate: leftover task containers and partial output from the
previous try are removed before `tb run` starts.
"""

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

# OOM events for the task container, read by the executor: terminal-bench reports an
# OOM-killed task container only as a generic agent or test failure.
TASK_CONTAINER_EVENTS_FILE = "task-container-events.jsonl"


def _label_filters(labels: dict[str, str]) -> list[str]:
    return [arg for key, value in labels.items() for arg in ("--filter", f"label={key}={value}")]


def _ids(list_command: list[str]) -> list[str]:
    return subprocess.run(list_command, capture_output=True, text=True, check=True).stdout.split()


def remove_leftovers(labels: dict[str, str]) -> None:
    filters = _label_filters(labels)
    if container_ids := _ids(["docker", "ps", "--all", "--quiet", *filters]):
        subprocess.run(["docker", "rm", "--force", *container_ids], capture_output=True)
    if network_ids := _ids(["docker", "network", "ls", "--quiet", *filters]):
        subprocess.run(["docker", "network", "rm", *network_ids], capture_output=True)


def watch_task_container(labels: dict[str, str], events_path: Path) -> subprocess.Popen:
    command = [
        "docker", "events",
        "--filter", "type=container",
        "--filter", "event=oom",
        *_label_filters(labels),
        "--format", "{{json .}}",
    ]
    return subprocess.Popen(command, stdout=events_path.open("w"), stderr=subprocess.DEVNULL)


def tb_command(submission_id: str, attempt: str, attempt_dir: Path) -> list[str]:
    command = [
        "python", "-m", "terminal_bench.cli.tb.main", "run",
        "--dataset-path", os.environ["AQ_TASK_ROOT"],
        "--task-id", os.environ["AQ_TASK_ID"],
        "--agent", os.environ["AQ_AGENT"],
        "--output-path", str(attempt_dir),
        "--run-id", f"{submission_id}-attempt-{attempt}",
        "--n-attempts", "1",
        "--n-concurrent", "1",
        "--no-rebuild",
        "--no-cleanup",
    ]
    if model := os.environ.get("AQ_MODEL"):
        command += ["--model", model]
    return command


def main() -> int:
    submission_id = os.environ["AQ_SUBMISSION_ID"]
    attempt = os.environ["JOB_COMPLETION_INDEX"]
    os.environ["AQ_ATTEMPT"] = attempt
    labels = {"aq.submission": submission_id, "aq.attempt": attempt}

    remove_leftovers(labels)

    attempt_dir = Path(os.environ["AQ_OUTPUT_ROOT"]) / f"attempt-{attempt}"
    shutil.rmtree(attempt_dir, ignore_errors=True)
    attempt_dir.mkdir(parents=True)

    watcher = watch_task_container(labels, attempt_dir / TASK_CONTAINER_EVENTS_FILE)
    harness = subprocess.Popen(tb_command(submission_id, attempt, attempt_dir))
    # As PID 1 we would otherwise ignore SIGTERM; pass it on so tb can wind down.
    signal.signal(signal.SIGTERM, lambda *_: harness.terminate())
    try:
        return harness.wait()
    finally:
        watcher.terminate()


if __name__ == "__main__":
    sys.exit(main())
