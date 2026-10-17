"""Deterministic analysis of N attempts. Every insight cites evidence; insights whose
evidence does not verify against the artifacts are withheld and listed as rejected."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

from runner.insights.artifacts import Attempt, Submission, load_submission
from runner.insights.evidence import EvidenceLedger
from runner.insights.stats import learnability_verdict, wilson_interval
from runner.test_literals import TestLiteral, required_literals

LLM_FAILURE_MODES = {"context_length_exceeded", "output_length_exceeded", "fatal_llm_parse_error"}
CONFIRMATION_WARNING = "TESTS FAILED! Are you sure you want to mark complete?"
LIMITATIONS = [
    "Pass-rate intervals are 95% Wilson intervals; with few attempts they are wide and verdicts say so.",
    "Attempt classification is rule-based on recorded artifacts; it does not infer the agent's intent.",
    "Hidden-requirement detection is lexical: a test literal counts as stated only if it appears "
    "(case-insensitively) in the instruction, and as discoverable only if the environment showed it to an "
    "agent before that agent typed it; tests that accept any of several alternatives may be over-reported.",
]


@dataclass
class Insight:
    category: str
    severity: str
    title: str
    detail: str
    evidence: list[str]
    attempts: list[int] = field(default_factory=list)


class Analyzer:
    def __init__(self, submission: Submission):
        self.s = submission
        self.ledger = EvidenceLedger(submission.root)
        self.insights: list[Insight] = []
        completed = [a for a in submission.attempts if a.status == "completed"]
        self.completed = completed
        self.test_names = sorted({name for a in completed for name in a.tests})

    def run(self) -> dict[str, Any]:
        attempts = [self._classify(attempt) for attempt in self.s.attempts]
        self._consistent_failures()
        self._hidden_requirements()
        self._divergences()

        accepted = [i for i in self.insights if self.ledger.all_verified(i.evidence)]
        rejected = [i for i in self.insights if not self.ledger.all_verified(i.evidence)]
        cited = {e for insight in accepted + rejected for e in insight.evidence}
        resolved = sum(a.resolved for a in self.s.attempts)
        errored = sum(a.status == "error" for a in self.s.attempts)
        failures = len(self.s.attempts) - errored - resolved
        return {
            "task_id": self.s.task_id,
            "outcome": {
                "resolved_attempts": resolved,
                "n_attempts": len(self.s.attempts),
                "learnability": learnability_verdict(resolved, failures, errored),
            },
            "tests": self._test_table(),
            "attempts": attempts,
            "attempt_stats": self._attempt_stats(),
            "insights": [asdict(i) for i in accepted],
            "rejected_insights": [asdict(i) for i in rejected],
            "evidence": {e: self.ledger.items[e].to_dict() for e in sorted(cited, key=lambda x: int(x[1:]))},
            "limitations": LIMITATIONS,
        }

    def _classify(self, attempt: Attempt) -> dict[str, Any]:
        category, evidence = self._attempt_category(attempt)
        failed = sorted(name for name, status in attempt.tests.items() if status != "passed")
        if category != "solved":
            detail = f"Attempt {attempt.index} ended as {category.replace('_', ' ')}"
            if failed:
                detail += f"; failing tests: {', '.join(failed)}"
            self.insights.append(
                Insight(
                    "attempt_failure",
                    "info",
                    f"Attempt {attempt.index}: {category}",
                    detail,
                    evidence,
                    [attempt.index],
                )
            )
        return {
            "attempt": attempt.index,
            "category": category,
            "resolved": attempt.resolved,
            "failed_tests": failed,
            "episodes": len(attempt.episodes),
            "declared_complete": attempt.declared_complete,
            "duration_sec": attempt.duration_sec,
            "input_tokens": attempt.input_tokens,
            "output_tokens": attempt.output_tokens,
        }

    def _attempt_category(self, attempt: Attempt) -> tuple[str, list[str]]:
        if attempt.infrastructure_issues and not attempt.resolved:
            return "infrastructure_issue", self._infrastructure_evidence(attempt)
        if attempt.status != "completed":
            category = "infrastructure_error" if attempt.status == "error" else attempt.status
            return category, [
                self.ledger.quote("results.json", attempt.error or attempt.status, attempt=attempt.index)
            ]
        trial_results = f"{attempt.trial_source}/results.json"
        mode = attempt.failure_mode or ""
        if attempt.resolved:
            return "solved", []
        if mode in ("agent_timeout", "test_timeout") or mode in LLM_FAILURE_MODES:
            category = "llm_error" if mode in LLM_FAILURE_MODES else mode
            return category, [self.ledger.quote(trial_results, mode, attempt=attempt.index)]
        if mode == "parse_error" or not attempt.tests:
            return "tests_unparseable", [
                self.ledger.quote(trial_results, mode or "failure_mode", attempt=attempt.index)
            ]

        failure_evidence = [
            self.ledger.quote(attempt.pane_source, f.text, line=f.line, attempt=attempt.index)
            for f in attempt.failures.values()
        ]
        if not attempt.declared_complete:
            last = attempt.episodes[-1] if attempt.episodes else None
            evidence = (
                [
                    self.ledger.quote(
                        last.source, last.state_analysis, attempt=attempt.index, episode=last.index
                    )
                ]
                if last
                else []
            )
            return "stopped_without_completing", evidence + failure_evidence

        final = attempt.episodes[-1]
        evidence = [
            self.ledger.quote(final.source, final.state_analysis, attempt=attempt.index, episode=final.index)
        ]
        warned = next((e for e in attempt.episodes if CONFIRMATION_WARNING in e.prompt), None)
        if warned:
            evidence.append(
                self.ledger.quote(
                    warned.prompt_source, CONFIRMATION_WARNING, attempt=attempt.index, episode=warned.index
                )
            )
            return "declared_done_despite_failure_warning", evidence + failure_evidence
        return "declared_done_with_failing_tests", evidence + failure_evidence

    def _infrastructure_evidence(self, attempt: Attempt) -> list[str]:
        """Cite the recorded container event itself, not the executor's summary of it."""
        if not attempt.events_source:
            return []
        lines = (self.s.root / attempt.events_source).read_text(errors="replace").splitlines()
        return [
            self.ledger.quote(attempt.events_source, line, line=number, attempt=attempt.index)
            for number, line in enumerate(lines, start=1)
            if '"oom"' in line
        ][:3]

    def _failed_in(self, test: str) -> list[Attempt]:
        return [a for a in self.completed if a.tests.get(test) not in (None, "passed")]

    def _passed_in(self, test: str) -> list[Attempt]:
        return [a for a in self.completed if a.tests.get(test) == "passed"]

    def _consistent_failures(self) -> None:
        for test in self.test_names:
            failed = self._failed_in(test)
            if len(self.completed) < 2 or len(failed) != len(self.completed):
                continue
            messages = {a.failures[test].message for a in failed if test in a.failures}
            identical = len(messages) == 1
            evidence = [
                self.ledger.quote(
                    a.pane_source, a.failures[test].text, line=a.failures[test].line, attempt=a.index
                )
                for a in failed
                if test in a.failures
            ]
            detail = f"{test} failed in all {len(failed)} completed attempts" + (
                " with the identical assertion message, which points at a systematic cause "
                "(a task/spec issue or a capability gap) rather than run-to-run noise."
                if identical
                else "."
            )
            self.insights.append(
                Insight(
                    "consistent_test_failure",
                    "high",
                    f"{test} never passes",
                    detail,
                    evidence,
                    [a.index for a in failed],
                )
            )

    def _literals(self) -> dict[str, list[TestLiteral]]:
        if not self.s.tests_source:
            return {}
        return required_literals((self.s.root / self.s.tests_source).read_text())

    def _discoverable(self, literal: str) -> bool:
        """True if the environment showed the agent this text before it typed it itself;
        echoes of the agent's own output do not count."""
        for attempt in self.s.attempts:
            for episode in attempt.episodes:
                if literal in episode.prompt:
                    return True
                if any(literal in k for k in episode.keystrokes):
                    break
        return False

    def _hidden_requirements(self) -> None:
        instruction = self.s.instruction.lower()
        for test, literals in self._literals().items():
            failed = self._failed_in(test)
            if not failed:
                continue
            unstated = [lit for lit in literals if lit.literal.lower() not in instruction]
            hidden = [lit for lit in unstated if not self._discoverable(lit.literal)]
            if not hidden:
                continue
            evidence = []
            for lit in hidden:
                evidence.append(self.ledger.quote(self.s.tests_source, lit.literal, line=lit.line))
                evidence.append(self.ledger.absence(self.s.instruction_source, lit.literal))
            quoted = ", ".join(f"'{lit.literal}'" for lit in hidden)
            severity = "high" if len(failed) == len(self.completed) else "medium"
            self.insights.append(
                Insight(
                    "hidden_requirement",
                    severity,
                    f"{test} checks for text the instruction never specifies",
                    f"{test} looks for {quoted}, but none of these appear in the instruction or in any "
                    f"terminal output the agents saw. It failed in {len(failed)}/{len(self.completed)} "
                    "completed attempts. "
                    "Either state the expected format in the instruction or relax the test.",
                    evidence,
                    [a.index for a in failed],
                )
            )

    def _divergences(self) -> None:
        for test, literals in self._literals().items():
            passed, failed = self._passed_in(test), self._failed_in(test)
            if not passed or not failed:
                continue
            for lit in literals:
                if not all(lit.literal in a.keystroke_text for a in passed):
                    continue
                if any(lit.literal in a.keystroke_text for a in failed):
                    continue
                evidence = []
                for attempt in passed:
                    episode = next(e for e in attempt.episodes if any(lit.literal in k for k in e.keystrokes))
                    evidence.append(
                        self.ledger.quote(
                            episode.source, lit.literal, attempt=attempt.index, episode=episode.index
                        )
                    )
                for attempt in failed:
                    if attempt.trial_source and '"' not in lit.literal and "\\" not in lit.literal:
                        evidence.append(
                            self.ledger.absence(f"{attempt.trial_source}/commands.txt", lit.literal)
                        )
                self.insights.append(
                    Insight(
                        "divergence",
                        "medium",
                        f"Passing attempts produced '{lit.literal}'; failing ones never did",
                        f"Every attempt that passed {test} ({_indices(passed)}) typed '{lit.literal}' "
                        f"into the terminal; none of the failing attempts ({_indices(failed)}) did. "
                        "This literal is what separates them.",
                        evidence,
                        [a.index for a in passed + failed],
                    )
                )

    def _test_table(self) -> list[dict[str, Any]]:
        rows = []
        for test in self.test_names:
            passed = len(self._passed_in(test))
            low, high = wilson_interval(passed, len(self.completed))
            rows.append(
                {
                    "name": test,
                    "passed": passed,
                    "failed": len(self.completed) - passed,
                    "pass_rate": round(passed / len(self.completed), 3),
                    "interval_95": [low, high],
                }
            )
        return rows

    def _attempt_stats(self) -> dict[str, Any]:
        def summarize(group: list[Attempt]) -> dict[str, Any]:
            if not group:
                return {"n": 0}
            return {
                "n": len(group),
                "mean_episodes": round(mean(len(a.episodes) for a in group), 1),
                "mean_duration_sec": round(mean(a.duration_sec or 0 for a in group), 1),
                "mean_input_tokens": round(mean(a.input_tokens or 0 for a in group)),
            }

        return {
            "resolved": summarize([a for a in self.completed if a.resolved]),
            "unresolved": summarize([a for a in self.completed if not a.resolved]),
            "note": "Descriptive only; differences at this sample size are not statistically meaningful.",
        }


def _indices(attempts: list[Attempt]) -> str:
    return ", ".join(f"#{a.index}" for a in attempts)


def analyze(submission_dir: Path) -> dict[str, Any]:
    return Analyzer(load_submission(submission_dir)).run()
