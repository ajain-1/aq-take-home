from datetime import UTC, datetime, timedelta
from pathlib import Path

from runner import catalog
from runner.config import Settings
from runner.models import AttemptProgress, Status, Strategy, Submission, Wave

START = datetime(2026, 10, 1, tzinfo=UTC)
SETTINGS = Settings(price_input_per_mtok=5.0, price_output_per_mtok=25.0)


def attempt(index, resolved, tests=(), status="completed", **extra):
    return {
        "attempt": index,
        "status": status,
        "resolved": resolved,
        "tests": [{"name": name, "status": result} for name, result in tests],
        "duration_sec": 60.0 + index,
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        **extra,
    }


def submission(sid, task_id, attempts, agent="terminus-1", minutes=0, status=Status.COMPLETED, **extra):
    resolved = sum(1 for a in attempts if a["resolved"])
    model = None if agent == "oracle" else "openrouter/x/model-a"
    s = Submission.create(sid, len(attempts) or 1, agent, model)
    s.task_id = task_id
    s.status = status
    s.created_at = START + timedelta(minutes=minutes)
    if status.is_terminal:
        s.results = {
            "attempts": attempts,
            "summary": {"n_attempts": len(attempts), "resolved_attempts": resolved},
            **extra,
        }
    return s


def test_outcome_vocabulary():
    assert catalog.outcome(submission("a", "t", [attempt(0, True)])) == "passed"
    assert catalog.outcome(submission("b", "t", [attempt(0, True), attempt(1, False)])) == "partial"
    assert catalog.outcome(submission("c", "t", [attempt(0, False)])) == "failed"
    assert catalog.outcome(submission("d", "t", [], status=Status.RUNNING)) == "running"
    assert catalog.outcome(submission("e", "t", [], status=Status.FAILED)) == "error"


def test_attempt_categories_match_insights_names():
    assert catalog.attempt_category(attempt(0, True)) == "solved"
    assert catalog.attempt_category(attempt(0, False, status="error")) == "no_results"
    oom = attempt(0, False, infrastructure_issues=["task container was OOM-killed"])
    assert catalog.attempt_category(oom) == "task_container_oom"
    assert catalog.attempt_category(attempt(0, False, status="tests_not_run")) == "tests_not_run"
    assert catalog.attempt_category(attempt(0, False, failure_mode="agent_timeout")) == "agent_timeout"
    assert catalog.attempt_category(attempt(0, False, failure_mode="context_length_exceeded")) == "llm_error"
    assert catalog.attempt_category(attempt(0, False, failure_mode="none")) == "tests_failed"
    annotated = catalog.with_categories({"attempts": [attempt(0, True)], "passed": True})
    assert annotated["attempts"][0]["category"] == "solved" and annotated["passed"] is True


def test_task_pass_rate_pools_agent_attempts_and_ignores_oracle_and_errors():
    runs = [
        submission("a", "t", [attempt(0, True), attempt(1, False)]),
        submission("b", "t", [attempt(0, False), attempt(1, False, status="error")], minutes=5),
        submission("c", "t", [attempt(0, True), attempt(1, True)], agent="oracle", minutes=10),
    ]
    summary = catalog.task_summary("t", runs, SETTINGS)
    assert summary["runs"] == 3 and summary["agent_runs"] == 2
    assert summary["pass_rate"]["passes"] == 1 and summary["pass_rate"]["trials"] == 3
    assert summary["failure_categories"] == {"tests_failed": 2}
    assert summary["learnability"] == "undetermined"
    assert summary["last_run"]["submission_id"] == "c"
    # 4 agent attempts x (1M in * $5 + 0.1M out * $25) / 1M
    assert summary["cost_usd"] == 30.0


def test_adaptive_decision_wins_over_pooled_rule():
    passes = [attempt(i, True) for i in range(8)]
    adaptive = submission("a", "t", passes, learnability={"classification": "too_easy"})
    adaptive.strategy = Strategy.ADAPTIVE
    summary = catalog.task_summary("t", [adaptive], SETTINGS)
    assert summary["learnability"] == "too_easy"
    assert catalog.run_summary(adaptive)["learnability"] == "too_easy"
    fixed = submission("b", "t", [attempt(0, True)], learnability={"classification": "undetermined"})
    assert catalog.run_summary(fixed)["learnability"] is None


def test_heatmap_orders_columns_by_run_and_sorts_hardest_tests_first():
    runs = [
        submission("b", "t", [attempt(0, False, [("x", "failed"), ("y", "passed")])], minutes=5),
        submission("a", "t", [attempt(0, True, [("x", "passed"), ("y", "passed")])]),
    ]
    grid = catalog.heatmap(runs)
    assert [c["submission_id"] for c in grid["columns"]] == ["a", "b"]
    assert [r["test"] for r in grid["rows"]] == ["x", "y"]
    assert grid["rows"][0]["cells"] == ["passed", "failed"] and grid["rows"][0]["pass_rate"] == 0.5


def test_dashboard_counts_active_runs_and_tasks():
    running = submission("r", "u", [], status=Status.RUNNING, minutes=20)
    running.progress.waves = [Wave(index=0, offset=0, size=3)]
    running.progress.attempts = [AttemptProgress(index=0, state="running")]
    data = catalog.dashboard([submission("a", "t", [attempt(0, True)]), running], SETTINGS)
    assert data["tasks"] == 2 and data["runs"] == 2 and data["agent_attempts"] == 1
    assert data["pass_rate"]["rate"] == 1.0
    assert data["active_runs"][0]["attempts_running"] == 1 and data["active_runs"][0]["attempts_total"] == 3


def test_attempt_indices_follow_what_actually_ran():
    finished = submission("a", "t", [attempt(0, True), attempt(1, False)])
    assert catalog.attempt_indices(finished) == [0, 1]
    adaptive = submission("b", "t", [], status=Status.RUNNING)
    adaptive.n_attempts = 10
    adaptive.progress.waves = [Wave(index=0, offset=0, size=5)]
    assert catalog.attempt_indices(adaptive) == [0, 1, 2, 3, 4]


def test_task_detail_reads_spec_from_latest_submission(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    task_dir = settings.submissions_dir / "a" / "tasks" / "t"
    task_dir.mkdir(parents=True)
    (task_dir / "task.yaml").write_text("instruction: Do it.\ndifficulty: easy\nresource_class: small\n")
    detail = catalog.task_detail("t", [submission("a", "t", [attempt(0, True)])], settings)
    assert detail["spec"]["instruction"] == "Do it." and detail["spec"]["difficulty"] == "easy"
    assert detail["latest_agent_run_id"] == "a"
    assert catalog.task_detail("missing", [], settings) is None
