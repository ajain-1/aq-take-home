import threading
from dataclasses import replace

import pytest
from conftest import FakeKube, finished_snapshot, make_zip, task_files, task_zip

from api.service import SubmissionRejected, SubmissionService
from runner.models import Phase, Status, Submission
from runner.run_task import TaskRunner
from runner.store import SubmissionNotFound, SubmissionStore
from runner.validation.models import Finding, Severity, Stage, Validation, ValidationMode
from runner.validation.pipeline import Validator
from runner.validation.store import ValidationStore


def test_store_survives_reopen_and_tracks_unfinished(settings):
    store = SubmissionStore(settings.db_path)
    for submission_id in ("a", "b"):
        store.save(Submission.create(submission_id, 1, "oracle", None))
    store.update("a", lambda s: setattr(s, "status", Status.COMPLETED))

    reopened = SubmissionStore(settings.db_path)
    assert reopened.get("a").status == Status.COMPLETED
    assert [s.id for s in reopened.list_unfinished()] == ["b"]
    assert reopened.count() == 2
    with pytest.raises(SubmissionNotFound):
        reopened.get("missing")


class RecordingRunner(TaskRunner):
    """Real submission creation; execution is replaced by a blocking recorder."""

    def __init__(self, store, settings):
        super().__init__(store, FakeKube([finished_snapshot()]), settings)
        self.ran: list[str] = []
        self.release = threading.Event()

    def run(self, submission_id):
        self.ran.append(submission_id)
        self.release.wait(5)

    def stop(self):
        self.release.set()


@pytest.fixture
def service(settings):
    settings = replace(settings, max_concurrent_submissions=1, max_upload_bytes=50_000)
    store = SubmissionStore(settings.db_path)
    runner = RecordingRunner(store, settings)
    validator = Validator(ValidationStore(settings.db_path), runner, settings)
    yield SubmissionService(store, runner, validator, settings), store, runner, settings
    runner.stop()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"n_attempts": 0}, "n_attempts must be between"),
        ({"n_attempts": 11}, "n_attempts must be between"),
        ({"agent": "rm -rf"}, "agent must be one of"),
        ({"agent": ""}, "agent must be one of"),
    ],
)
def test_invalid_parameters_are_rejected(service, kwargs, message):
    svc, store, _, _ = service
    with pytest.raises(SubmissionRejected, match=message):
        svc.submit(task_zip(), kwargs.get("n_attempts"), kwargs.get("agent"))
    assert store.count() == 0


def test_oversized_upload_is_rejected(service):
    svc, *_ = service
    with pytest.raises(SubmissionRejected, match="upload exceeds"):
        svc.submit(b"x" * 50_001, None, None)


def test_invalid_bundle_is_rejected_and_leaves_nothing_behind(service):
    svc, store, _, settings = service
    with pytest.raises(SubmissionRejected, match="unsafe path"):
        svc.submit(make_zip({"../evil": "x"}), None, "oracle")
    assert store.count() == 0
    assert not any(settings.submissions_dir.iterdir())


def test_worker_pool_bounds_active_submissions(service):
    svc, store, runner, _ = service
    first = svc.submit(task_zip(), 1, "oracle")
    second = svc.submit(task_zip(), 1, "oracle")
    threading.Event().wait(0.2)
    assert runner.ran == [first.id]
    assert store.get(second.id).status == Status.QUEUED


def test_concurrent_updates_are_not_lost(settings):
    store = SubmissionStore(settings.db_path)
    store.save(Submission.create("a", 1, "oracle", None))

    def bump():
        for _ in range(25):
            store.update("a", lambda s: setattr(s.progress, "attempts_total", s.progress.attempts_total + 1))

    threads = [threading.Thread(target=bump) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert store.get("a").progress.attempts_total == 1 + 8 * 25


def zip_without_workdir() -> bytes:
    files = task_files() | {"Dockerfile": "FROM python:3.12-slim\n"}
    return make_zip({f"tiny-task/{name}": content for name, content in files.items()})


@pytest.mark.parametrize("mode", [ValidationMode.STATIC, ValidationMode.FULL])
def test_gate_with_static_errors_rejects_and_leaves_nothing_pending(service, mode):
    svc, store, runner, settings = service
    with pytest.raises(SubmissionRejected) as rejected:
        svc.submit(zip_without_workdir(), 1, "oracle", validation=mode)
    assert any(f["check"] == "workdir" for f in rejected.value.report["findings"])
    assert store.count() == 0 and runner.ran == []
    assert ValidationStore(settings.db_path).list_unfinished() == []


def test_full_gate_is_linked_to_its_submission_from_creation(service, monkeypatch):
    svc, store, _, settings = service
    monkeypatch.setattr(svc, "_enqueue", lambda submission_id: None)
    submission = svc.submit(task_zip(), 1, "oracle", validation=ValidationMode.FULL)
    gate = ValidationStore(settings.db_path).get(submission.validation_id)
    assert gate.gates_submission_id == submission.id and not gate.status.is_terminal
    assert store.get(submission.id).progress.phase == Phase.VALIDATING


def test_failed_gate_fails_the_submission_without_running_agents(service, monkeypatch):
    svc, store, runner, settings = service
    monkeypatch.setattr(svc, "_enqueue", lambda submission_id: None)
    submission = svc.submit(task_zip(), 1, "oracle", validation=ValidationMode.FULL)
    failed = Validation(
        id=submission.validation_id,
        mode=ValidationMode.FULL,
        status=Status.COMPLETED,
        findings=[Finding(check="oracle_passes", stage=Stage.ORACLE, severity=Severity.ERROR, message="x")],
    )
    monkeypatch.setattr(svc._validator, "run", lambda validation_id: failed)
    svc._execute(submission.id)
    stored = store.get(submission.id)
    assert stored.status == Status.FAILED and "failed validation" in stored.error
    assert runner.ran == []


def test_resume_leaves_validation_children_to_their_validation(service, monkeypatch):
    svc, store, _, settings = service
    for submission_id in ("oracle-child", "nop-child", "standalone"):
        store.save(Submission.create(submission_id, 1, "oracle", None))
    ValidationStore(settings.db_path).save(
        Validation(
            id="v1",
            mode=ValidationMode.FULL,
            oracle_submission_id="oracle-child",
            nop_submission_id="nop-child",
        )
    )
    enqueued = []
    monkeypatch.setattr(svc, "_enqueue", enqueued.append)
    svc.resume_unfinished()
    assert enqueued == ["standalone"]
