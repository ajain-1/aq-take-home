"""Turns N attempts of a task into evidence-backed insights."""

import json
from pathlib import Path
from typing import Any

from runner.insights.analysis import analyze
from runner.insights.narrative import summarize
from runner.insights.report import render_markdown

__all__ = ["analyze", "generate", "render_markdown"]


def generate(submission_dir: Path, narrative: bool = True) -> dict[str, Any]:
    """Analyze a finished submission and write insights.json / insights.md beside it."""
    report = analyze(submission_dir)
    if narrative and (summary := summarize(report)):
        report["summary"] = summary
    (submission_dir / "insights.json").write_text(json.dumps(report, indent=2))
    (submission_dir / "insights.md").write_text(render_markdown(report))
    return report
