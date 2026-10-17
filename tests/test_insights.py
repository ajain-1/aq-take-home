import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner.insights.analysis import analyze
from runner.insights.evidence import Evidence, EvidenceLedger, verify
from runner.insights.narrative import summarize
from runner.insights.report import render_markdown
from runner.insights.stats import learnability_verdict, wilson_interval
from runner.test_literals import required_literals

TEST_SOURCE = '''
import re

def test_report_sections():
    """Docstring mentioning HIDDEN HEADER is not a requirement."""
    with open("report.txt", "r") as f:
        content = f.read()
    assert "REPORT HEADER" in content, "assertion message is not a requirement"
    assert re.search(r"Savings: ([\\d.]+)%", content)

def test_file_exists():
    assert open("report.txt").read()
'''


def write_attempt(root: Path, index: int, resolved: bool, keystrokes: str, final_analysis: str) -> dict:
    trial = root / "runs" / f"attempt-{index}" / f"run-{index}" / "demo-task" / f"demo-task.{index}"
    episode = trial / "agent-logs" / "episode-0"
    episode.mkdir(parents=True)
    (episode / "prompt.txt").write_text("root@box:/app# ls\nreport.txt\n")
    (episode / "response.json").write_text(
        json.dumps(
            {
                "state_analysis": final_analysis,
                "explanation": "write the report",
                "commands": [{"keystrokes": keystrokes, "is_blocking": True, "timeout_sec": 5}],
                "is_task_complete": True,
            }
        )
    )
    (trial / "commands.txt").write_text(repr(keystrokes) + "\n")
    status = "passed" if resolved else "failed"
    summary = "PASSED" if resolved else "FAILED"
    message = "" if resolved else " - AssertionError: assert 'REPORT HEADER' in ''"
    (trial / "panes").mkdir()
    (trial / "panes" / "post-test.txt").write_text(
        "=== short test summary info ===\n"
        f"{summary} ../tests/test_outputs.py::test_report_sections{message}\n"
        "PASSED ../tests/test_outputs.py::test_file_exists\n"
    )
    (trial / "results.json").write_text(json.dumps({"is_resolved": resolved, "failure_mode": "none"}))
    return {
        "attempt": index,
        "status": "completed",
        "resolved": resolved,
        "failure_mode": "none",
        "tests": [
            {"name": "test_report_sections", "status": status},
            {"name": "test_file_exists", "status": "passed"},
        ],
        "duration_sec": 10.0,
        "input_tokens": 100,
        "output_tokens": 10,
    }


@pytest.fixture
def submission(tmp_path: Path) -> Path:
    task = tmp_path / "tasks" / "demo-task"
    (task / "tests").mkdir(parents=True)
    (task / "tests" / "test_outputs.py").write_text(TEST_SOURCE)
    (task / "task.yaml").write_text(
        yaml.safe_dump({"instruction": "Write report.txt with a savings estimate.", "difficulty": "medium"})
    )
    attempts = [
        write_attempt(
            tmp_path, 0, True, "printf 'REPORT HEADER\\nSavings: 30%' > report.txt\n", "Report written."
        ),
        write_attempt(tmp_path, 1, False, "echo hello > report.txt\n", "The report is complete."),
        {
            "attempt": 2,
            "status": "error",
            "resolved": False,
            "error": "OOMKilled (exit code 137)",
            "tests": [],
        },
    ]
    (tmp_path / "results.json").write_text(json.dumps({"task_id": "demo-task", "attempts": attempts}))
    return tmp_path


def test_wilson_interval_is_wide_for_small_samples():
    assert wilson_interval(0, 5) == (0.0, 0.434)
    low, high = wilson_interval(5, 10)
    assert low < 0.5 < high


def test_learnability_uses_exact_rule_at_ten_and_hedges_below():
    assert learnability_verdict(4, 6)["verdict"] == "learnable"
    assert learnability_verdict(9, 1)["verdict"] == "too_easy"
    assert learnability_verdict(2, 3)["verdict"] == "learnable"  # decided early, as the adaptive runner
    assert learnability_verdict(8, 0)["verdict"] == "too_easy"
    assert learnability_verdict(0, 9)["verdict"] == "too_hard"
    assert learnability_verdict(5, 0)["verdict"] == "undetermined"
    assert "1 errored" in learnability_verdict(1, 1, errored=1)["basis"]


def test_literal_extraction_ignores_messages_docstrings_and_call_args():
    literals = {lit.literal for lit in required_literals(TEST_SOURCE)["test_report_sections"]}
    assert literals == {"REPORT HEADER", "Savings:"}
    assert required_literals(TEST_SOURCE)["test_file_exists"] == []


def test_verify_quotes_lines_json_and_yaml_fields(tmp_path: Path):
    (tmp_path / "pane.txt").write_text("first\nFAILED test_x - boom\n")
    (tmp_path / "r.json").write_text(json.dumps({"commands": [{"keystrokes": "cat > a.txt << 'EOF'\n"}]}))
    (tmp_path / "t.yaml").write_text(yaml.safe_dump({"instruction": "do it", "difficulty": "medium"}))

    def check(kind, source, quote, line=None):
        return verify(tmp_path, Evidence("E1", kind, source, quote, line=line))

    assert check("quote", "pane.txt", "FAILED test_x", line=2)
    assert not check("quote", "pane.txt", "FAILED test_x", line=1)
    assert not check("quote", "pane.txt", "fabricated output")
    assert check("quote", "r.json", "cat > a.txt << 'EOF'")
    assert check("absence", "t.yaml#instruction", "medium")
    assert not check("absence", "t.yaml", "medium")
    assert not check("quote", "missing.txt", "anything")


def test_unverifiable_insights_are_withheld(submission: Path, monkeypatch):
    original = EvidenceLedger.quote

    def tampered(self, source, quote, **location):
        return (
            original(self, source, quote + " (fabricated)", **location)
            if "post-test" in source
            else original(self, source, quote, **location)
        )

    monkeypatch.setattr(EvidenceLedger, "quote", tampered)
    report = analyze(submission)
    assert not any(i["title"] == "Attempt 1: declared_done_with_failing_tests" for i in report["insights"])
    assert any(
        i["title"] == "Attempt 1: declared_done_with_failing_tests" for i in report["rejected_insights"]
    )


def test_analysis_finds_hidden_requirement_divergence_and_errors(submission: Path):
    report = analyze(submission)
    by_category = {}
    for insight in report["insights"]:
        by_category.setdefault(insight["category"], []).append(insight)

    hidden = by_category["hidden_requirement"][0]
    assert "'REPORT HEADER'" in hidden["detail"] and "'Savings:'" in hidden["detail"]
    assert {"attempt_failure", "divergence"} <= by_category.keys()
    assert any("REPORT HEADER" in i["title"] for i in by_category["divergence"])
    assert all(e["verified"] for e in report["evidence"].values())
    assert {a["category"] for a in report["attempts"]} == {
        "solved",
        "declared_done_with_failing_tests",
        "infrastructure_error",
    }
    assert "REPORT HEADER" in render_markdown(report)


def test_narrative_drops_uncited_and_unsupported_sentences(submission: Path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    report = analyze(submission)
    hidden = next(i for i in report["insights"] if i["category"] == "hidden_requirement")
    response = json.dumps(
        {
            "sentences": [
                {"text": "The test expects an unstated REPORT HEADER.", "evidence": hidden["evidence"][:1]},
                {"text": "Agents fail 73% of the time.", "evidence": hidden["evidence"][:1]},
                {"text": "No citation here.", "evidence": []},
                {"text": "Cites a made-up ID.", "evidence": ["E999"]},
            ]
        }
    )
    summary = summarize(report, complete=lambda prompt, model, key: response)
    assert summary["kept_sentences"] == 1 and summary["dropped_sentences"] == 3
    assert "REPORT HEADER" in summary["text"] and "73%" not in summary["text"]


def test_infrastructure_issues_and_tests_not_run_are_their_own_categories(submission: Path):
    results = json.loads((submission / "results.json").read_text())
    results["attempts"][1]["infrastructure_issues"] = ["task container was OOM-killed"]
    results["attempts"][2] = {"attempt": 2, "status": "tests_not_run", "resolved": False, "tests": []}
    (submission / "results.json").write_text(json.dumps(results))
    (submission / "runs" / "attempt-1" / "task-container-events.jsonl").write_text(
        json.dumps({"status": "oom", "Action": "oom", "id": "abc"}) + "\n"
    )

    report = analyze(submission)
    categories = {a["attempt"]: a["category"] for a in report["attempts"]}
    assert categories[1] == "infrastructure_issue" and categories[2] == "tests_not_run"
    infra = next(i for i in report["insights"] if i["title"] == "Attempt 1: infrastructure_issue")
    sources = [report["evidence"][e]["source"] for e in infra["evidence"]]
    assert sources and all(source.endswith("task-container-events.jsonl") for source in sources)
