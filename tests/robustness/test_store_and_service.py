import threading
from dataclasses import replace

import pytest
from conftest import FakeKube, finished_snapshot, make_zip, task_zip

from api.service import SubmissionRejected, SubmissionService
from runner.models import Status, Submission
from runner.run_task import TaskRunner
from runner.store import SubmissionNotFound, SubmissionStore


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
    yield SubmissionService(store, runner, settings), store, runner, settings
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
