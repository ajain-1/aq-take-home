"""
AfterQuery Task Executor API

A task execution system that accepts task ZIPs, runs them as
Kubernetes Jobs on Docker Desktop's built-in K8s cluster,
and returns structured test results.

Modeled on our production system, which runs on GKE with
10 parallel pods per submission.

Endpoints:
    POST /submit         - Submit a task ZIP for execution
    GET  /status/{id}    - Check execution status
    GET  /results/{id}   - Get final test results
    GET  /health         - Health check
    POST /validate       - Task quality checks (see api/validation_routes.py)
    GET  /ui             - Web UI (see api/ui_routes.py for its read-only endpoints)
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

# Allow `cd api && uvicorn main:app` as well as `uvicorn api.main:app` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

from api import insights_routes, ui_routes, validation_routes
from api.context import AppContext, Context, SubmissionDep, configure_logging, unprocessable
from api.service import SubmissionRejected
from runner import catalog, docker_ops
from runner.config import Settings
from runner.models import AttemptState
from runner.validation.models import ValidationMode


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    context = AppContext.create(Settings.from_env())
    app.state.context = context
    context.resume_unfinished()
    yield
    context.shutdown()


app = FastAPI(title="AQ Task Executor", lifespan=lifespan)
app.include_router(ui_routes.router)
app.include_router(insights_routes.router)
app.include_router(validation_routes.router)
app.mount("/ui/static", ui_routes.UIStaticFiles(directory=ui_routes.STATIC_DIR), name="ui-static")


@app.post("/submit", status_code=202)
def submit_task(
    context: Context,
    file: Annotated[UploadFile, File()],
    n_attempts: Annotated[int | None, Form()] = None,
    agent: Annotated[str | None, Form()] = None,
    strategy: Annotated[str | None, Form()] = None,
    confidence: Annotated[float | None, Form()] = None,
    validation: Annotated[ValidationMode | None, Form()] = None,
):
    """
    Accept a task ZIP and execute it as a K8s Job.

    The ZIP should contain a task directory with:
        - Dockerfile
        - run-tests.sh
        - solution.sh
        - tests/test_outputs.py
        - task.yaml
        - [task-specific files]

    Optional form fields: `n_attempts` (parallel agent runs) and `agent`
    (terminus-1, or oracle/nop for infrastructure checks). `strategy=adaptive`
    runs attempts in waves and stops once the 10-run learnability class is
    decided; `confidence` < 1.0 allows earlier, probabilistic stopping.
    `validation=static` rejects tasks with static quality errors; `validation=full`
    also runs oracle/nop checks before any agent and fails the submission on errors.
    Omit `validation` to skip the gate.
    """
    archive = file.file.read(context.settings.max_upload_bytes + 1)
    try:
        submission = context.service.submit(archive, n_attempts, agent, strategy, confidence, validation)
    except SubmissionRejected as e:
        return unprocessable(str(e), e.report)
    return {
        "submission_id": submission.id,
        "task_id": submission.task_id,
        "status": submission.status,
        "n_attempts": submission.n_attempts,
        "strategy": submission.strategy,
        "confidence": submission.confidence,
        "agent": submission.agent,
        "validation_id": submission.validation_id,
        "status_url": f"/status/{submission.id}",
        "results_url": f"/results/{submission.id}",
    }


@app.get("/status/{submission_id}")
def get_status(submission: SubmissionDep):
    """Current status, timestamps, and per-attempt progress for a submission."""
    progress = submission.progress
    return {
        "submission_id": submission.id,
        "task_id": submission.task_id,
        "status": submission.status,
        "agent": submission.agent,
        "model": submission.model,
        "n_attempts": submission.n_attempts,
        "strategy": submission.strategy,
        "confidence": submission.confidence,
        "error": submission.error,
        "created_at": submission.created_at,
        "started_at": submission.started_at,
        "launched_at": submission.launched_at,
        "finished_at": submission.finished_at,
        "updated_at": submission.updated_at,
        "progress": {
            "phase": progress.phase,
            "attempts_total": progress.attempts_total,
            **{state.value: progress.count(state) for state in AttemptState},
            "attempts": [
                {**attempt.model_dump(), "pod": attempt.pod, "retries": attempt.retries}
                for attempt in progress.attempts
            ],
            "waves": [wave.model_dump() for wave in progress.waves],
        },
    }


@app.get("/results/{submission_id}")
def get_results(submission: SubmissionDep):
    """Per-test pass/fail for every attempt, aggregate counts, timing, and raw pytest output."""
    if not submission.status.is_terminal:
        return JSONResponse(
            status_code=409,
            content={
                "submission_id": submission.id,
                "status": submission.status,
                "detail": "results not ready",
            },
        )
    if submission.results is None:
        return {
            "submission_id": submission.id,
            "task_id": submission.task_id,
            "status": submission.status,
            "error": submission.error,
            "passed": False,
            "passed_tests": 0,
            "total_tests": 0,
            "attempts": [],
        }
    return {**catalog.with_categories(submission.results), "error": submission.error}


@app.get("/health")
def health(context: Context):
    """Health check - verify API, Docker, and K8s are available."""
    return {
        "status": "ok",
        "docker_available": docker_ops.docker_available(),
        "k8s_available": context.kube.available(),
        "submissions_tracked": context.store.count(),
    }
