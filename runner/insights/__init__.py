"""Turns N attempts of a task into evidence-backed insights."""

import json
from pathlib import Path
from typing import Any

from runner.insights.analysis import analyze
from runner.insights.narrative import summarize
from runner.insights.report import render_markdown
from runner.paths import SubmissionPaths

__all__ = ["analyze", "build", "generate", "render_markdown"]


def build(submission_dir: Path, narrative_model: str | None = None) -> dict[str, Any]:
    """Analyze a finished submission; with a model, add a citation-checked summary."""
    report = analyze(submission_dir)
    if narrative_model and (summary := summarize(report, narrative_model)):
        report["summary"] = summary
    return report


def generate(submission_dir: Path, narrative_model: str | None = None) -> dict[str, Any]:
    """Build the report and write insights.json / insights.md beside the submission."""
    report = build(submission_dir, narrative_model)
    paths = SubmissionPaths(submission_dir)
    paths.insights_json.write_text(json.dumps(report, indent=2))
    paths.insights_markdown.write_text(render_markdown(report))
    return report
