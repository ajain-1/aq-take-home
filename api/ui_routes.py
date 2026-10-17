"""Read-only endpoints backing the web UI: submission listing and agent trajectories."""

import json
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api.context import AppContext, get_context
from runner.results import find_trial_dir
from runner.run_task import SubmissionPaths
from runner.store import SubmissionNotFound

STATIC_DIR = Path(__file__).parent / "static"
EPISODE_DIR_PATTERN = re.compile(r"^episode-(\d+)$")
PANES = ("pre-agent", "post-agent", "post-test")

router = APIRouter()
Context = Annotated[AppContext, Depends(get_context)]


def _read_text(path: Path) -> str | None:
    return path.read_text(errors="replace") if path.is_file() else None


def _read_json(path: Path) -> dict | str | None:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _episodes(agent_logs: Path) -> list[dict]:
    """Each episode is one LLM turn. The terminal output the agent saw after its
    commands is the next episode's prompt."""
    if not agent_logs.is_dir():
        return []
    indexed = sorted(
        (int(match.group(1)), path)
        for path in agent_logs.iterdir()
        if path.is_dir() and (match := EPISODE_DIR_PATTERN.match(path.name))
    )

    episodes = []
    for position, (index, path) in enumerate(indexed):
        has_next = position + 1 < len(indexed)
        next_prompt = _read_text(indexed[position + 1][1] / "prompt.txt") if has_next else None
        episodes.append(
            {
                "index": index,
                "prompt": _read_text(path / "prompt.txt"),
                "response": _read_json(path / "response.json"),
                "observation": next_prompt,
            }
        )
    return episodes


def _trial_dir(context: AppContext, submission_id: str, attempt: int) -> Path:
    try:
        submission = context.store.get(submission_id)
    except SubmissionNotFound:
        raise HTTPException(status_code=404, detail=f"submission {submission_id} not found") from None
    if not 0 <= attempt < submission.n_attempts or submission.task_id is None:
        raise HTTPException(status_code=404, detail=f"attempt {attempt} not found")
    attempt_dir = SubmissionPaths(context.settings.submissions_dir / submission.id).attempt(attempt)
    # A running trial has no results.json yet, but its agent logs already stream in.
    found = find_trial_dir(attempt_dir, submission.task_id) or next(
        (p for p in sorted(attempt_dir.glob(f"*/{submission.task_id}/*")) if p.is_dir()), None
    )
    if found is None:
        raise HTTPException(status_code=404, detail="attempt has no artifacts yet")
    return found


@router.get("/ui", include_in_schema=False)
def ui():
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/submissions")
def list_submissions(context: Context, limit: int = 50):
    """Most recent submissions first, with enough detail to render a list."""
    return [
        {
            "submission_id": s.id,
            "task_id": s.task_id,
            "status": s.status,
            "phase": s.progress.phase,
            "agent": s.agent,
            "n_attempts": s.n_attempts,
            "created_at": s.created_at,
            "finished_at": s.finished_at,
            "summary": (s.results or {}).get("summary"),
            "passed": (s.results or {}).get("passed"),
        }
        for s in context.store.list_recent(min(max(limit, 1), 200))
    ]


@router.get("/submissions/{submission_id}/attempts/{attempt}/episodes")
def get_episodes(context: Context, submission_id: str, attempt: int):
    """The agent's turn-by-turn trajectory plus terminal snapshots for one attempt."""
    directory = _trial_dir(context, submission_id, attempt)
    return {
        "submission_id": submission_id,
        "attempt": attempt,
        "episodes": _episodes(directory / "agent-logs"),
        "panes": {pane: _read_text(directory / "panes" / f"{pane}.txt") for pane in PANES},
    }
