"""Read-only endpoints backing the web UI: dashboard, task pages, and agent trajectories."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from api.context import Context, SubmissionDep
from runner import catalog, trajectory
from runner.models import Submission
from runner.paths import SubmissionPaths

STATIC_DIR = Path(__file__).parent / "static"
PANES = ("pre-agent", "post-agent", "post-test")
RECORDING = Path("sessions") / "agent.cast"
# The UI is unbundled ES modules, so browsers must revalidate them or keep running stale code.
REVALIDATE = {"Cache-Control": "no-cache"}

router = APIRouter()


class UIStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers.update(REVALIDATE)
        return response


def _read_text(path: Path) -> str | None:
    return path.read_text(errors="replace") if path.is_file() else None


def _episodes(trial_dir: Path) -> list[dict]:
    """Each episode is one LLM turn; the terminal output the agent saw after its
    commands is the next episode's prompt."""
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


def _trial_dir(context: Context, submission: Submission, attempt: int) -> Path:
    """The artifacts of an attempt that actually ran; never built from request paths."""
    if submission.task_id is None or attempt not in catalog.attempt_indices(submission):
        raise HTTPException(status_code=404, detail=f"attempt {attempt} not found")
    paths = SubmissionPaths(context.settings.submissions_dir / submission.id)
    # A running trial has no results.json yet, but its agent logs already stream in.
    found = paths.trial(attempt, submission.task_id, finished_only=False)
    if found is None:
        raise HTTPException(status_code=404, detail="attempt has no artifacts yet")
    return found


@router.get("/ui", include_in_schema=False)
def ui():
    return FileResponse(STATIC_DIR / "index.html", headers=REVALIDATE)


@router.get("/dashboard")
def get_dashboard(context: Context):
    """Global metrics across every run, plus the runs still in flight."""
    return catalog.dashboard(context.store.list_all(), context.settings)


@router.get("/tasks")
def list_tasks(context: Context):
    """One row per task: pass rate across agent attempts, learnability, last run."""
    return catalog.task_summaries(context.store.list_all(), context.settings)


@router.get("/tasks/{task_id}")
def get_task(context: Context, task_id: str):
    """A task's spec, aggregate results across all its runs, and a per-test heatmap."""
    detail = catalog.task_detail(task_id, context.store.list_all(), context.settings)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} has no runs")
    validation = context.validations.latest_for_task(task_id)
    return {**detail, "latest_validation": validation.report() if validation else None}


@router.get("/submissions")
def list_submissions(context: Context, limit: int = 50):
    """Most recent submissions first."""
    return [catalog.run_summary(s) for s in context.store.list_recent(min(max(limit, 1), 200))]


@router.get("/submissions/{submission_id}/attempts/{attempt}/episodes")
def get_episodes(context: Context, submission: SubmissionDep, attempt: int):
    """The agent's turn-by-turn trajectory plus terminal snapshots for one attempt."""
    directory = _trial_dir(context, submission, attempt)
    return {
        "submission_id": submission.id,
        "attempt": attempt,
        "episodes": _episodes(directory),
        "panes": {pane: _read_text(directory / "panes" / f"{pane}.txt") for pane in PANES},
        "has_recording": (directory / RECORDING).is_file(),
    }


@router.get("/submissions/{submission_id}/attempts/{attempt}/recording")
def get_recording(context: Context, submission: SubmissionDep, attempt: int):
    """The attempt's asciinema recording, with the agent's turns merged in as markers."""
    recording = _trial_dir(context, submission, attempt) / RECORDING
    if not recording.is_file():
        raise HTTPException(status_code=404, detail="attempt has no recording")
    return Response(trajectory.read_recording(recording), media_type="application/x-asciicast")
