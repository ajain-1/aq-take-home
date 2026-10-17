"""Interprets oracle and nop runs, executed through the normal submission pipeline.

The oracle (reference solution) must pass every test, consistently across attempts;
the nop agent (no changes) must not. Together they show the environment builds, the
tests are satisfiable and deterministic, and the tests actually require work.
"""

from collections.abc import Iterator
from typing import Any

from runner.validation.models import Finding, Severity, Stage

SLOW_TEST_FRACTION = 0.5


def _finding(stage: Stage, check: str, severity: Severity, message: str, **details) -> Finding:
    return Finding(check=check, stage=stage, severity=severity, message=message, details=details or None)


def _failed_tests(attempt: dict[str, Any]) -> list[str]:
    return sorted(test["name"] for test in attempt["tests"] if test["status"] != "passed")


def oracle_findings(results: dict[str, Any] | None, max_test_timeout_sec: float) -> Iterator[Finding]:
    stage = Stage.ORACLE
    if not results or not results.get("attempts"):
        error = (results or {}).get("error", "no results")
        yield _finding(stage, "oracle_runs", Severity.ERROR, f"oracle run did not produce results: {error}")
        return

    attempts = results["attempts"]
    for attempt in attempts:
        if attempt["status"] != "completed":
            yield _finding(stage, "oracle_runs", Severity.ERROR,
                           f"oracle attempt {attempt['attempt']} errored: {attempt.get('error')}")
        elif not attempt["total_tests"]:
            yield _finding(stage, "oracle_tests_parse", Severity.ERROR,
                           f"oracle attempt {attempt['attempt']} produced no parseable test results "
                           f"(failure mode {attempt.get('failure_mode')})")

    completed = [a for a in attempts if a["status"] == "completed" and a["total_tests"]]
    failures = {a["attempt"]: _failed_tests(a) for a in completed}
    failing_everywhere = set.intersection(*(set(f) for f in failures.values())) if failures else set()
    if failing_everywhere:
        yield _finding(stage, "oracle_passes", Severity.ERROR,
                       f"reference solution fails {len(failing_everywhere)} test(s): {', '.join(sorted(failing_everywhere))}",
                       failed_tests=sorted(failing_everywhere))

    if len({tuple(f) for f in failures.values()}) > 1:
        yield _finding(stage, "oracle_deterministic", Severity.ERROR,
                       "reference solution results differ between attempts (flaky tests or environment)",
                       failed_tests_by_attempt=failures)

    slowest = max((a.get("test_duration_sec") or 0 for a in completed), default=0)
    if slowest > SLOW_TEST_FRACTION * max_test_timeout_sec:
        yield _finding(stage, "test_timeout_headroom", Severity.WARNING,
                       f"tests took {slowest:.0f}s with the reference solution, over half of "
                       f"max_test_timeout_sec ({max_test_timeout_sec:.0f}s); they may time out under load",
                       test_duration_sec=slowest)


def nop_findings(results: dict[str, Any] | None) -> Iterator[Finding]:
    stage = Stage.NOP
    attempt = ((results or {}).get("attempts") or [None])[0]
    if attempt is None or attempt["status"] != "completed":
        yield _finding(stage, "nop_runs", Severity.WARNING,
                       f"nop run did not produce results: {(attempt or results or {}).get('error')}")
        return
    if not attempt["total_tests"]:
        yield _finding(stage, "nop_tests_parse", Severity.ERROR,
                       "tests produce no parseable results on the untouched environment "
                       f"(failure mode {attempt.get('failure_mode')})")
        return
    if attempt["resolved"]:
        yield _finding(stage, "nop_fails", Severity.ERROR,
                       "every test passes without any changes; the task can be 'solved' by doing nothing")
        return

    passing = sorted(test["name"] for test in attempt["tests"] if test["status"] == "passed")
    if passing:
        yield _finding(stage, "tests_require_work", Severity.INFO,
                       f"{len(passing)}/{attempt['total_tests']} test(s) pass on the untouched environment "
                       f"and don't measure the agent's work: {', '.join(passing)}",
                       passing_tests=passing)
