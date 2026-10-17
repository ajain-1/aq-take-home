"""Loads one submission's per-attempt artifacts into a form the analysis can reason over.

All locations are kept relative to the submission directory so evidence can cite them
and reports stay valid when the directory is copied elsewhere.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TASK_CONTAINER_EVENTS_FILE = "task-container-events.jsonl"
SUMMARY_LINE = re.compile(r"^(?:FAILED|ERROR) \S*::(?P<name>[^\s\[]+)\S*(?: - (?P<message>.*))?$")


@dataclass
class Episode:
    index: int
    source: str
    prompt_source: str
    state_analysis: str
    keystrokes: list[str]
    is_task_complete: bool
    prompt: str


@dataclass
class TestFailure:
    name: str
    message: str
    line: int
    text: str


@dataclass
class Attempt:
    index: int
    status: str
    resolved: bool
    failure_mode: str | None
    tests: dict[str, str]
    error: str | None = None
    trial_source: str | None = None
    pane_source: str | None = None
    episodes: list[Episode] = field(default_factory=list)
    failures: dict[str, TestFailure] = field(default_factory=dict)
    duration_sec: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    infrastructure_issues: list[str] = field(default_factory=list)
    events_source: str | None = None

    @property
    def declared_complete(self) -> bool:
        return bool(self.episodes) and self.episodes[-1].is_task_complete

    @property
    def keystroke_text(self) -> str:
        return "\n".join(k for episode in self.episodes for k in episode.keystrokes)


@dataclass
class Submission:
    root: Path
    task_id: str
    instruction: str
    instruction_source: str
    tests_source: str | None
    attempts: list[Attempt]


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def _load_episodes(root: Path, trial_dir: Path) -> list[Episode]:
    episode_dirs = sorted(
        (trial_dir / "agent-logs").glob("episode-*"), key=lambda p: int(p.name.split("-")[1])
    )
    episodes = []
    for episode_dir in episode_dirs:
        response_path, prompt_path = episode_dir / "response.json", episode_dir / "prompt.txt"
        if not response_path.exists():
            continue
        try:
            response = json.loads(response_path.read_text())
        except json.JSONDecodeError:
            response = {}
        episodes.append(
            Episode(
                index=int(episode_dir.name.split("-")[1]),
                source=_relative(root, response_path),
                prompt_source=_relative(root, prompt_path),
                state_analysis=response.get("state_analysis", ""),
                keystrokes=[c.get("keystrokes", "") for c in response.get("commands", [])],
                is_task_complete=bool(response.get("is_task_complete")),
                prompt=prompt_path.read_text(errors="replace") if prompt_path.exists() else "",
            )
        )
    return episodes


def _load_failures(pane: Path) -> dict[str, TestFailure]:
    failures = {}
    for number, line in enumerate(pane.read_text(errors="replace").splitlines(), start=1):
        if match := SUMMARY_LINE.match(line.strip()):
            name = match["name"]
            failures[name] = TestFailure(name, (match["message"] or "").strip(), number, line.strip())
    return failures


def _find_trial_dir(root: Path, index: int, task_id: str) -> Path | None:
    matches = sorted((root / "runs" / f"attempt-{index}").glob(f"*/{task_id}/*/results.json"))
    return matches[-1].parent if matches else None


def load_submission(root: Path) -> Submission:
    results = json.loads((root / "results.json").read_text())
    task_id = results["task_id"]
    task_dir = root / "tasks" / task_id
    task_yaml = yaml.safe_load((task_dir / "task.yaml").read_text())
    tests_path = task_dir / "tests" / "test_outputs.py"

    attempts = []
    for summary in results.get("attempts", []):
        attempt = Attempt(
            index=summary["attempt"],
            status=summary["status"],
            resolved=bool(summary.get("resolved")),
            failure_mode=summary.get("failure_mode"),
            tests={t["name"]: t["status"] for t in summary.get("tests", [])},
            error=summary.get("error"),
            duration_sec=summary.get("duration_sec"),
            input_tokens=summary.get("input_tokens"),
            output_tokens=summary.get("output_tokens"),
            infrastructure_issues=summary.get("infrastructure_issues") or [],
        )
        events = root / "runs" / f"attempt-{attempt.index}" / TASK_CONTAINER_EVENTS_FILE
        if events.exists():
            attempt.events_source = _relative(root, events)
        if trial_dir := _find_trial_dir(root, attempt.index, task_id):
            attempt.trial_source = _relative(root, trial_dir)
            attempt.episodes = _load_episodes(root, trial_dir)
            pane = trial_dir / "panes" / "post-test.txt"
            if pane.exists():
                attempt.pane_source = _relative(root, pane)
                attempt.failures = _load_failures(pane)
        attempts.append(attempt)

    return Submission(
        root=root,
        task_id=task_id,
        instruction=task_yaml.get("instruction", ""),
        instruction_source=f"{_relative(root, task_dir / 'task.yaml')}#instruction",
        tests_source=_relative(root, tests_path) if tests_path.exists() else None,
        attempts=attempts,
    )
