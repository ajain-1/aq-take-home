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
"""

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import uuid
import os
import shutil
from datetime import datetime
from pathlib import Path

app = FastAPI(title="AQ Task Executor")

# Storage paths
UPLOAD_DIR = Path("./uploads")
RESULTS_DIR = Path("./results")
UPLOAD_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

# You'll need to track submissions. How you store them — and whether
# they survive restarts — is a design decision you should make.


@app.post("/submit")
async def submit_task(file: UploadFile = File(...)):
    """
    Accept a task ZIP and execute it as a K8s Job.

    The ZIP should contain a task directory with:
        - Dockerfile
        - run-tests.sh
        - solution.sh
        - tests/test_outputs.py
        - task.yaml
        - [task-specific files]

    Returns a submission_id and URLs for polling status/results.
    """
    # TODO: Implement
    return JSONResponse(
        status_code=501,
        content={"error": "Not implemented"},
    )


@app.get("/status/{submission_id}")
async def get_status(submission_id: str):
    """
    Return execution status for a submission.

    Should include: submission identity, current status, timestamps,
    and a progress object with the current phase and — for parallel
    runs — completion counts. Design the response shape yourself.
    """
    # TODO: Implement
    return JSONResponse(
        status_code=501,
        content={"error": "Not implemented"},
    )


@app.get("/results/{submission_id}")
async def get_results(submission_id: str):
    """
    Return final test results for a completed submission.

    Should include per-test pass/fail granularity, summary counts,
    execution time, and the raw pytest output. Design the response
    shape yourself.
    """
    # TODO: Implement
    return JSONResponse(
        status_code=501,
        content={"error": "Not implemented"},
    )


@app.get("/health")
async def health():
    """Health check - verify API, Docker, and K8s are available."""
    return {
        "status": "ok",
        "docker_available": _check_docker(),
        "k8s_available": _check_k8s(),
        "submissions_tracked": 0,  # TODO: wire up to your tracking store
    }


def _check_docker() -> bool:
    """Check if Docker daemon is reachable."""
    try:
        import subprocess

        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_k8s() -> bool:
    """Check if Kubernetes cluster is reachable."""
    try:
        import subprocess

        result = subprocess.run(
            ["kubectl", "cluster-info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False
