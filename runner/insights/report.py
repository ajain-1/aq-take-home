from typing import Any

SEVERITY_ORDER = {"high": 0, "medium": 1, "info": 2}


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _evidence_line(evidence: dict[str, Any]) -> str:
    location = evidence["source"]
    if "line" in evidence:
        location += f":{evidence['line']}"
    tags = [f"attempt {evidence['attempt']}" if "attempt" in evidence else None,
            f"episode {evidence['episode']}" if "episode" in evidence else None]
    scope = ", ".join(t for t in tags if t)
    status = "verified" if evidence["verified"] else "NOT VERIFIED"
    if evidence["kind"] == "absence":
        return f"- **{evidence['id']}** ({status}) `{_cell(evidence['quote'])}` does **not** occur in `{location}`"
    prefix = f"{scope}, " if scope else ""
    return f"- **{evidence['id']}** ({status}) {prefix}`{location}`: \"{_cell(evidence['quote'])}\""


def render_markdown(report: dict[str, Any]) -> str:
    outcome, learnability = report["outcome"], report["outcome"]["learnability"]
    low, high = learnability["interval_95"]
    lines = [
        f"# Insights: {report['task_id']}",
        "",
        f"**{outcome['resolved_attempts']}/{outcome['n_attempts']} attempts resolved the task** "
        f"(95% interval for the true pass rate: {low:.0%}-{high:.0%}).",
        f"Learnability verdict: **{learnability['verdict']}** ({learnability['basis']}).",
        "",
        "Every finding below cites evidence that was re-checked verbatim against the run artifacts. "
        "Findings whose evidence did not verify are withheld and listed at the end.",
        "",
        "## Findings",
        "",
    ]
    insights = sorted(report["insights"], key=lambda i: SEVERITY_ORDER.get(i["severity"], 9))
    if not insights:
        all_resolved = outcome["resolved_attempts"] == outcome["n_attempts"]
        lines += ["No failures to explain: every attempt resolved the task." if all_resolved
                  else "No findings with verifiable evidence.", ""]
    for insight in insights:
        lines += [f"### [{insight['severity']}] {insight['title']}", "", insight["detail"], "", "Evidence:"]
        lines += [_evidence_line(report["evidence"][e]) for e in insight["evidence"]]
        lines.append("")

    lines += ["## Per-test pass rates", "", "| Test | Passed | Failed | 95% interval |", "|---|---|---|---|"]
    for test in report["tests"]:
        t_low, t_high = test["interval_95"]
        lines.append(f"| {test['name']} | {test['passed']} | {test['failed']} | {t_low:.0%}-{t_high:.0%} |")

    lines += ["", "## Attempts", "", "| # | Outcome | Episodes | Duration (s) | Failed tests |", "|---|---|---|---|---|"]
    for attempt in report["attempts"]:
        lines.append(
            f"| {attempt['attempt']} | {attempt['category']} | {attempt['episodes']} | "
            f"{attempt['duration_sec'] or '-'} | {', '.join(attempt['failed_tests']) or '-'} |"
        )

    stats = report["attempt_stats"]
    lines += ["", f"Resolved vs unresolved (descriptive): {stats['resolved']} vs {stats['unresolved']}. {stats['note']}"]

    if summary := report.get("summary"):
        lines += ["", "## Narrative summary (LLM, citation-checked)", "", summary["text"], "",
                  f"_{summary['note']}_"]

    if report["rejected_insights"]:
        lines += ["", "## Withheld findings (evidence did not verify)", ""]
        lines += [f"- {i['title']}" for i in report["rejected_insights"]]

    lines += ["", "## Limitations", ""] + [f"- {item}" for item in report["limitations"]]
    return "\n".join(lines) + "\n"
