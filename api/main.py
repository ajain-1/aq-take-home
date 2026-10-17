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
    POST /validate       - Check a task ZIP for quality problems before running agents
    GET  /validations/{id} - Validation report
    GET  /health         - Health check
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Allow `cd api && uvicorn main:app` as well as `uvicorn api.main:app` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from api.service import SubmissionRejected, SubmissionService, ValidationGate
from runner import docker_ops
from runner.config import settings
from runner.k8s import KubeClient
from runner.models import AttemptState, Submission
from runner.run_task import TaskRunner
from runner.store import SubmissionNotFound, SubmissionStore
from runner.validation.models import ValidationMode
from runner.validation.pipeline import Validator
from runner.validation.store import ValidationNotFound, ValidationStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

store = SubmissionStore(settings.db_path)
kube = KubeClient(settings.namespace)
runner = TaskRunner(store, kube, settings)
validator = Validator(ValidationStore(settings.db_path), runner, settings)
service = SubmissionService(store, runner, validator, settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    service.resume_unfinished()
    yield
    service.shutdown()


app = FastAPI(title="AQ Task Executor", lifespan=lifespan)


def _get_submission(submission_id: str) -> Submission:
    try:
        return store.get(submission_id)
    except SubmissionNotFound:
        raise HTTPException(status_code=404, detail=f"submission {submission_id} not found")


@app.post("/submit", status_code=202)
def submit_task(
    file: UploadFile = File(...),
    n_attempts: int | None = Form(None),
    agent: str | None = Form(None),
    validation: ValidationGate = Form(ValidationGate.NONE),
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

    Optional form fields: `n_attempts` (parallel agent runs), `agent`
    (terminus-1, or oracle/nop for infrastructure checks), and `validation`
    (none, static: reject on static errors, full: run oracle/nop checks before
    any agent and fail the submission if they find errors).
    """
    try:
        submission = service.submit(file.file.read(), n_attempts, agent, validation)
    except SubmissionRejected as e:
        raise HTTPException(status_code=422, detail=e.report or str(e))
    return {
        "submission_id": submission.id,
        "task_id": submission.task_id,
        "status": submission.status,
        "n_attempts": submission.n_attempts,
        "agent": submission.agent,
        "validation_id": submission.validation_id,
        "status_url": f"/status/{submission.id}",
        "results_url": f"/results/{submission.id}",
    }


@app.get("/status/{submission_id}")
def get_status(submission_id: str):
    """Current status, timestamps, and per-attempt progress for a submission."""
    submission = _get_submission(submission_id)
    progress = submission.progress
    return {
        "submission_id": submission.id,
        "task_id": submission.task_id,
        "status": submission.status,
        "agent": submission.agent,
        "model": submission.model,
        "n_attempts": submission.n_attempts,
        "error": submission.error,
        "created_at": submission.created_at,
        "started_at": submission.started_at,
        "finished_at": submission.finished_at,
        "updated_at": submission.updated_at,
        "progress": {
            "phase": progress.phase,
            "attempts_total": progress.attempts_total,
            **{state.value: progress.count(state) for state in AttemptState},
            "attempts": [attempt.model_dump() for attempt in progress.attempts],
        },
    }


@app.get("/results/{submission_id}")
def get_results(submission_id: str):
    """Per-test pass/fail for every attempt, aggregate counts, timing, and raw pytest output."""
    submission = _get_submission(submission_id)
    if not submission.status.is_terminal:
        return JSONResponse(
            status_code=409,
            content={"submission_id": submission.id, "status": submission.status, "detail": "results not ready"},
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
    return {**submission.results, "error": submission.error}


@app.post("/validate")
def validate_task(
    file: UploadFile = File(...),
    mode: ValidationMode = Form(ValidationMode.FULL),
    force: bool = Form(False),
):
    """
    Check a task before spending agent compute on it.

    `static` returns the report immediately. `full` (202) also builds the image,
    probes it, and runs the oracle (twice) and nop agents as Jobs; poll
    /validations/{id}. `force` runs the dynamic stages even if static checks fail.
    """
    try:
        validation = service.validate(file.file.read(), mode, force)
    except SubmissionRejected as e:
        raise HTTPException(status_code=422, detail=str(e))
    status_code = 200 if validation.status.is_terminal else 202
    return JSONResponse(status_code=status_code, content=jsonable_encoder(validation.report()))


@app.get("/validations/{validation_id}")
def get_validation(validation_id: str):
    try:
        return validator.get(validation_id).report()
    except ValidationNotFound:
        raise HTTPException(status_code=404, detail=f"validation {validation_id} not found")


@app.get("/health")
def health():
    """Health check - verify API, Docker, and K8s are available."""
    return {
        "status": "ok",
        "docker_available": docker_ops.docker_available(),
        "k8s_available": kube.available(),
        "submissions_tracked": store.count(),
    }
