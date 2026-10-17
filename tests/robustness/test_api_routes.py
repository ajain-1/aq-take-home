from dataclasses import replace

import pytest
from conftest import make_zip, task_zip
from fastapi.testclient import TestClient

from api import main
from api.context import AppContext
from runner import docker_ops
from runner.k8s import KubeClient
from runner.models import Status
from runner.run_task import TaskRunner


@pytest.fixture
def api(settings, monkeypatch):
    """The real app and wiring, with execution stubbed out so submissions stay queued."""
    executed: list[str] = []
    monkeypatch.setattr(TaskRunner, "run", lambda self, submission_id: executed.append(submission_id))
    monkeypatch.setattr(docker_ops, "docker_available", lambda: True)
    monkeypatch.setattr(KubeClient, "available", lambda self: True)
    context = AppContext.create(replace(settings, max_upload_bytes=100_000))
    main.app.state.context = context
    yield TestClient(main.app), context, executed
    context.service.shutdown()


def _submit(client, archive: bytes, **fields):
    return client.post("/submit", files={"file": ("task.zip", archive)}, data=fields)


def test_submit_accepts_a_valid_task(api):
    client, context, _ = api
    response = _submit(client, task_zip(), agent="oracle", n_attempts="2")
    assert response.status_code == 202
    body = response.json()
    assert (body["task_id"], body["n_attempts"], body["agent"]) == ("tiny-task", 2, "oracle")
    assert context.store.get(body["submission_id"]).status == Status.QUEUED


@pytest.mark.parametrize(
    ("archive", "fields", "detail"),
    [
        (b"not a zip", {}, "not a valid ZIP"),
        (make_zip({"../evil": "x"}), {}, "unsafe path"),
        (task_zip(), {"n_attempts": "0"}, "n_attempts must be between"),
        (task_zip(), {"agent": "evil"}, "agent must be one of"),
        (b"x" * 100_001, {}, "upload exceeds"),
    ],
)
def test_submit_rejects_invalid_input_with_422(api, archive, fields, detail):
    client, context, executed = api
    response = _submit(client, archive, **fields)
    assert response.status_code == 422
    assert detail in str(response.json()["detail"])
    assert context.store.count() == 0 and executed == []


def test_submit_rejects_non_integer_attempts(api):
    client, *_ = api
    assert _submit(client, task_zip(), n_attempts="abc").status_code == 422


def test_status_and_results_lifecycle(api):
    client, context, _ = api
    submission_id = _submit(client, task_zip(), agent="oracle").json()["submission_id"]

    status = client.get(f"/status/{submission_id}").json()
    assert status["status"] == "queued" and status["progress"]["attempts_total"] == 1
    pending = client.get(f"/results/{submission_id}")
    assert pending.status_code == 409 and pending.json()["detail"] == "results not ready"

    def finish(s):
        s.status = Status.COMPLETED
        s.results = {
            "submission_id": s.id,
            "passed": True,
            "passed_tests": 1,
            "total_tests": 1,
            "attempts": [],
        }

    context.store.update(submission_id, finish)
    results = client.get(f"/results/{submission_id}")
    assert results.status_code == 200
    assert (results.json()["passed"], results.json()["passed_tests"]) == (True, 1)


def test_failed_submission_without_results_still_reports(api):
    client, context, _ = api
    submission_id = _submit(client, task_zip(), agent="oracle").json()["submission_id"]

    def fail(s):
        s.status, s.error = Status.FAILED, "docker build failed"

    context.store.update(submission_id, fail)
    body = client.get(f"/results/{submission_id}").json()
    assert (body["status"], body["passed"], body["error"]) == ("failed", False, "docker build failed")


def test_unknown_submission_is_404(api):
    client, *_ = api
    assert client.get("/status/nope").status_code == 404
    assert client.get("/results/nope").status_code == 404


def test_health_reports_dependencies_and_tracked_count(api):
    client, *_ = api
    _submit(client, task_zip(), agent="oracle")
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["docker_available"] and body["k8s_available"]
    assert body["submissions_tracked"] == 1
