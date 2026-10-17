"""Turns terminal-bench trial output into structured per-attempt and aggregate results."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from runner.models import AttemptProgress

PYTEST_SESSION_MARKER = "test session starts"


def _seconds_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 2)


def _pytest_output(pane_path: Path) -> str | None:
    if not pane_path.exists():
        return None
    lines = pane_path.read_text(errors="replace").splitlines()
    start = next((i for i, line in enumerate(lines) if PYTEST_SESSION_MARKER in line), 0)
    return "\n".join(lines[start:]).strip()


def find_trial_dir(attempt_dir: Path, task_id: str) -> Path | None:
    matches = sorted(attempt_dir.glob(f"*/{task_id}/*/results.json"))
    return matches[-1].parent if matches else None


def collect_attempt(attempt_dir: Path, task_id: str, progress: AttemptProgress, data_dir: Path) -> dict[str, Any]:
    trial_dir = find_trial_dir(attempt_dir, task_id)
    if trial_dir is None:
        return {
            "attempt": progress.index,
            "status": "error",
            "resolved": False,
            "error": progress.reason or f"attempt produced no results (pod state: {progress.state})",
            "retries": progress.retries,
            "tests": [],
            "passed_tests": 0,
            "total_tests": 0,
        }

    trial = json.loads((trial_dir / "results.json").read_text())
    tests = [
        {"name": name, "status": status}
        for name, status in (trial.get("parser_results") or {}).items()
    ]
    return {
        "attempt": progress.index,
        "status": "completed",
        "resolved": bool(trial.get("is_resolved")),
        "failure_mode": trial.get("failure_mode"),
        "retries": progress.retries,
        "tests": tests,
        "passed_tests": sum(1 for test in tests if test["status"] == "passed"),
        "total_tests": len(tests),
        "started_at": trial.get("trial_started_at"),
        "finished_at": trial.get("trial_ended_at"),
        "duration_sec": _seconds_between(trial.get("trial_started_at"), trial.get("trial_ended_at")),
        "agent_duration_sec": _seconds_between(trial.get("agent_started_at"), trial.get("agent_ended_at")),
        "test_duration_sec": _seconds_between(trial.get("test_started_at"), trial.get("test_ended_at")),
        "input_tokens": trial.get("total_input_tokens"),
        "output_tokens": trial.get("total_output_tokens"),
        "artifacts_dir": str(trial_dir.relative_to(data_dir)),
        "pytest_output": _pytest_output(trial_dir / "panes" / "post-test.txt"),
    }


def aggregate(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize N attempts. The task counts as passed only if every attempt resolved it;
    per-test pass counts show how consistently each test was satisfied."""
    completed = [a for a in attempts if a["status"] == "completed"]
    per_test: dict[str, dict[str, int]] = {}
    for attempt in completed:
        for test in attempt["tests"]:
            counts = per_test.setdefault(test["name"], {"passed": 0, "failed": 0})
            counts[test["status"]] = counts.get(test["status"], 0) + 1

    resolved = sum(1 for a in attempts if a["resolved"])
    tests = [
        {"name": name, **counts, "pass_rate": round(counts["passed"] / len(completed), 3)}
        for name, counts in per_test.items()
    ]
    return {
        "passed": bool(attempts) and resolved == len(attempts),
        "passed_tests": sum(1 for test in tests if test["failed"] == 0 and test["passed"] == len(completed)),
        "total_tests": len(tests),
        "summary": {
            "n_attempts": len(attempts),
            "completed_attempts": len(completed),
            "errored_attempts": len(attempts) - len(completed),
            "resolved_attempts": resolved,
            "pass_rate": round(resolved / len(attempts), 3) if attempts else 0.0,
        },
        "tests": tests,
    }
