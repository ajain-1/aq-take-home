"""Runs one agent attempt inside a Kubernetes Job pod.

The attempt index comes from the Indexed Job (JOB_COMPLETION_INDEX). A retried pod
starts from a clean slate: leftover task containers and partial output from the
previous try are removed before `tb run` starts.
"""

import os
import shutil
import subprocess
from pathlib import Path


def _docker_ids(kind: str, labels: dict[str, str]) -> list[str]:
    filters = [arg for key, value in labels.items() for arg in ("--filter", f"label={key}={value}")]
    command = ["docker", kind, "ls", "-q", *filters]
    if kind == "container":
        command.insert(3, "-a")
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout.split()


def remove_leftovers(labels: dict[str, str]) -> None:
    if container_ids := _docker_ids("container", labels):
        subprocess.run(["docker", "rm", "-f", *container_ids], capture_output=True)
    if network_ids := _docker_ids("network", labels):
        subprocess.run(["docker", "network", "rm", *network_ids], capture_output=True)


def main() -> None:
    submission_id = os.environ["AQ_SUBMISSION_ID"]
    attempt = os.environ["JOB_COMPLETION_INDEX"]
    os.environ["AQ_ATTEMPT"] = attempt

    remove_leftovers({"aq.submission": submission_id, "aq.attempt": attempt})

    attempt_dir = Path(os.environ["AQ_OUTPUT_ROOT"]) / f"attempt-{attempt}"
    shutil.rmtree(attempt_dir, ignore_errors=True)
    attempt_dir.mkdir(parents=True)

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

    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
