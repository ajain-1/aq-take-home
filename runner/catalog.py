"""Read models for the UI: per-task and global aggregates over stored submissions.

Pure functions over Submission records, so they are easy to test. Aggregate pass
rates only count attempts by LLM agents; oracle/nop runs are infrastructure checks
and are listed but never pooled into a task's resolve rate.
"""

import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from runner.config import AGENTS, Settings
from runner.insights.analysis import LLM_FAILURE_MODES
from runner.insights.stats import wilson_interval
from runner.learnability import decide
from runner.models import Status, Strategy, Submission
from runner.paths import SubmissionPaths

TASK_SPEC_FIELDS = (
    "difficulty",
    "category",
    "tags",
    "resource_class",
    "max_agent_timeout_sec",
    "max_test_timeout_sec",
)


def outcome(submission: Submission) -> str:
    """One status word for humans: queued | running | passed | partial | failed | error."""
    if submission.status == Status.QUEUED:
        return "queued"
    if submission.status == Status.RUNNING:
        return "running"
    summary = (submission.results or {}).get("summary")
    if submission.status == Status.FAILED or not summary:
        return "error"
    resolved, total = summary["resolved_attempts"], summary["n_attempts"]
    if total and resolved == total:
        return "passed"
    return "partial" if resolved else "failed"


def attempt_category(attempt: dict[str, Any]) -> str:
    """Why an attempt ended the way it did, from its recorded result alone. A coarse
    version of the insights taxonomy (runner/insights), using the same names."""
    if attempt.get("resolved"):
        return "solved"
    if attempt.get("infrastructure_issues"):
        return "task_container_oom"
    if attempt.get("status") == "error":
        return "no_results"
    if attempt.get("status") == "tests_not_run":
        return "tests_not_run"
    mode = attempt.get("failure_mode") or "none"
    if mode in ("agent_timeout", "test_timeout"):
        return mode
    if mode in LLM_FAILURE_MODES:
        return "llm_error"
    return "tests_failed"


def with_categories(results: dict[str, Any]) -> dict[str, Any]:
    return {
        **results,
        "attempts": [{**a, "category": attempt_category(a)} for a in results.get("attempts", [])],
    }


def attempt_cost_usd(attempt: dict[str, Any], settings: Settings) -> float:
    return (
        (attempt.get("input_tokens") or 0) * settings.price_input_per_mtok
        + (attempt.get("output_tokens") or 0) * settings.price_output_per_mtok
    ) / 1e6


def model_short_name(model: str | None) -> str | None:
    return model.rsplit("/", 1)[-1] if model else None


def is_agent_run(submission: Submission) -> bool:
    return AGENTS.get(submission.agent, False)


def _attempts(submission: Submission) -> list[dict[str, Any]]:
    return (submission.results or {}).get("attempts", [])


def _scored(submission: Submission) -> list[dict[str, Any]]:
    """Attempts that count toward pass rates: finished trials, excluding infra errors."""
    return [a for a in _attempts(submission) if a.get("status") != "error"]


def pass_rate(passes: int, trials: int) -> dict[str, Any]:
    low, high = wilson_interval(passes, trials)
    return {
        "passes": passes,
        "trials": trials,
        "rate": round(passes / trials, 3) if trials else None,
        "interval_95": [low, high],
    }


def run_summary(submission: Submission) -> dict[str, Any]:
    results = submission.results or {}
    summary = results.get("summary") or {}
    adaptive = submission.strategy == Strategy.ADAPTIVE
    return {
        "submission_id": submission.id,
        "task_id": submission.task_id,
        "outcome": outcome(submission),
        "phase": submission.progress.phase,
        "agent": submission.agent,
        "model": model_short_name(submission.model),
        "strategy": submission.strategy,
        "attempts": summary.get("n_attempts", submission.progress.attempts_launched or submission.n_attempts),
        "resolved_attempts": summary.get("resolved_attempts"),
        "duration_sec": results.get("execution_time_sec"),
        "created_at": submission.created_at,
        "finished_at": submission.finished_at,
        "learnability": (results.get("learnability") or {}).get("classification") if adaptive else None,
        "error": submission.error,
    }


def _verdict(submissions: list[Submission], passes: int, failures: int) -> str:
    """Prefer the adaptive strategy's exact decision; otherwise apply the same exact
    10-run rule to the pooled attempts (undetermined until it is decided)."""
    for submission in sorted(submissions, key=lambda s: s.created_at, reverse=True):
        if submission.strategy == Strategy.ADAPTIVE and submission.results:
            return submission.results["learnability"]["classification"]
    return decide(passes, failures).value


def _failure_categories(attempts: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(attempt_category(a) for a in attempts if not a.get("resolved")))


def task_summary(task_id: str, submissions: list[Submission], settings: Settings) -> dict[str, Any]:
    agent_runs = [s for s in submissions if is_agent_run(s)]
    scored = [a for s in agent_runs for a in _scored(s)]
    passes = sum(1 for a in scored if a.get("resolved"))
    durations = [a["duration_sec"] for a in scored if a.get("duration_sec")]
    latest = max(submissions, key=lambda s: s.created_at)
    return {
        "task_id": task_id,
        "runs": len(submissions),
        "agent_runs": len(agent_runs),
        "attempts": len(scored),
        "pass_rate": pass_rate(passes, len(scored)),
        "learnability": _verdict(agent_runs, passes, len(scored) - passes) if scored else None,
        "median_attempt_sec": round(statistics.median(durations), 1) if durations else None,
        "failure_categories": _failure_categories(scored),
        "cost_usd": round(sum(attempt_cost_usd(a, settings) for s in agent_runs for a in _attempts(s)), 4),
        "last_run": run_summary(latest),
    }


def _by_task(submissions: list[Submission]) -> dict[str, list[Submission]]:
    grouped: dict[str, list[Submission]] = {}
    for submission in submissions:
        if submission.task_id:
            grouped.setdefault(submission.task_id, []).append(submission)
    return grouped


def task_summaries(submissions: list[Submission], settings: Settings) -> list[dict[str, Any]]:
    summaries = [task_summary(task_id, runs, settings) for task_id, runs in _by_task(submissions).items()]
    return sorted(summaries, key=lambda t: t["last_run"]["created_at"], reverse=True)


def dashboard(submissions: list[Submission], settings: Settings) -> dict[str, Any]:
    agent_attempts = [a for s in submissions if is_agent_run(s) for a in _attempts(s)]
    scored = [a for a in agent_attempts if a.get("status") != "error"]
    durations = [a["duration_sec"] for a in scored if a.get("duration_sec")]
    active = [s for s in submissions if not s.status.is_terminal]
    return {
        "tasks": len(_by_task(submissions)),
        "runs": len(submissions),
        "agent_attempts": len(agent_attempts),
        "pass_rate": pass_rate(sum(1 for a in scored if a.get("resolved")), len(scored)),
        "median_attempt_sec": round(statistics.median(durations), 1) if durations else None,
        "tokens": {
            "input": sum(a.get("input_tokens") or 0 for a in agent_attempts),
            "output": sum(a.get("output_tokens") or 0 for a in agent_attempts),
        },
        "cost_usd": round(sum(attempt_cost_usd(a, settings) for a in agent_attempts), 2),
        "failure_categories": _failure_categories(scored),
        "active_runs": [
            {
                **run_summary(s),
                "attempts_running": sum(1 for a in s.progress.attempts if a.state == "running"),
                "attempts_total": s.progress.attempts_launched or s.n_attempts,
            }
            for s in sorted(active, key=lambda s: s.created_at, reverse=True)
        ],
    }


def heatmap(submissions: list[Submission]) -> dict[str, Any]:
    """Tests x attempts (across agent runs, oldest first) so consistent failures stand out."""
    columns, cells = [], {}
    for submission in sorted(filter(is_agent_run, submissions), key=lambda s: s.created_at):
        for attempt in _scored(submission):
            column = len(columns)
            columns.append(
                {
                    "submission_id": submission.id,
                    "attempt": attempt["attempt"],
                    "resolved": attempt.get("resolved", False),
                    "created_at": submission.created_at,
                }
            )
            for test in attempt.get("tests", []):
                cells.setdefault(test["name"], {})[column] = test["status"]
    rows = [
        {
            "test": name,
            "cells": [statuses.get(column) for column in range(len(columns))],
            "pass_rate": round(sum(1 for s in statuses.values() if s == "passed") / len(statuses), 3),
        }
        for name, statuses in cells.items()
    ]
    rows.sort(key=lambda row: (row["pass_rate"], row["test"]))
    return {"columns": columns, "rows": rows}


def read_task_spec(task_dir: Path) -> dict[str, Any] | None:
    task_yaml = task_dir / "task.yaml"
    if not task_yaml.is_file():
        return None
    raw = yaml.safe_load(task_yaml.read_text()) or {}
    return {"instruction": raw.get("instruction"), **{key: raw.get(key) for key in TASK_SPEC_FIELDS}}


def task_detail(task_id: str, submissions: list[Submission], settings: Settings) -> dict[str, Any] | None:
    runs = _by_task(submissions).get(task_id)
    if not runs:
        return None
    latest = max(runs, key=lambda s: s.created_at)
    finished_agent_runs = [s for s in runs if is_agent_run(s) and s.status.is_terminal and s.results]
    latest_agent_run = max(finished_agent_runs, key=lambda s: s.created_at) if finished_agent_runs else None
    return {
        **task_summary(task_id, runs, settings),
        "spec": read_task_spec(SubmissionPaths(settings.submissions_dir / latest.id).task(task_id)),
        "heatmap": heatmap(runs),
        "runs_list": [run_summary(s) for s in sorted(runs, key=lambda s: s.created_at, reverse=True)],
        "latest_agent_run_id": latest_agent_run.id if latest_agent_run else None,
    }


def attempt_indices(submission: Submission) -> list[int]:
    """Attempts that actually exist: from results when finished, else launched pods.
    Adaptive runs may launch fewer (or more) attempts than n_attempts."""
    if attempts := _attempts(submission):
        return sorted(a["attempt"] for a in attempts)
    if submission.progress.attempts:
        return sorted(a.index for a in submission.progress.attempts)
    return list(range(submission.progress.attempts_launched))
