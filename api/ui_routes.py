"""Read-only endpoints backing the web UI: submission listing and agent trajectories."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.context import AppContext, Context
from runner import trajectory
from runner.paths import SubmissionPaths
from runner.store import SubmissionNotFound

STATIC_DIR = Path(__file__).parent / "static"
PANES = ("pre-agent", "post-agent", "post-test")

router = APIRouter()


def _read_text(path: Path) -> str | None:
    return path.read_text(errors="replace") if path.is_file() else None


def _episodes(trial_dir: Path) -> list[dict]:
    episodes = trajectory.load_episodes(trial_dir)
    return [
        {
            "index": episode.index,
            "prompt": episode.prompt or None,
            "response": episode.response or episode.raw_response or None,
            "observation": episodes[position + 1].prompt if position + 1 < len(episodes) else None,
        }
        for position, episode in enumerate(episodes)
    ]


def _trial_dir(context: AppContext, submission_id: str, attempt: int) -> Path:
    try:
        submission = context.store.get(submission_id)
    except SubmissionNotFound:
        raise HTTPException(status_code=404, detail=f"submission {submission_id} not found") from None
    if not 0 <= attempt < submission.n_attempts or submission.task_id is None:
        raise HTTPException(status_code=404, detail=f"attempt {attempt} not found")
    paths = SubmissionPaths(context.settings.submissions_dir / submission.id)
    # A running trial has no results.json yet, but its agent logs already stream in.
    found = paths.trial(attempt, submission.task_id, finished_only=False)
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
        "episodes": _episodes(directory),
        "panes": {pane: _read_text(directory / "panes" / f"{pane}.txt") for pane in PANES},
    }
