import json
import threading
import time

import pytest
from conftest import FakeKube, finished_snapshot, running_snapshot, task_zip

from runner import docker_ops, run_task
from runner.k8s import JobSnapshot
from runner.models import AttemptProgress, Status, Submission, Wave, utcnow
from runner.run_task import TaskRunner
from runner.store import SubmissionStore


class Harness:
    def __init__(self, settings, kube, monkeypatch):
        self.settings = settings
        self.kube = kube
        self.store = SubmissionStore(settings.db_path)
        self.runner = TaskRunner(self.store, kube, settings)
        self.removed: list[tuple] = []
        self.builds = {"active": 0, "max": 0}
        self.build_error: Exception | None = None
        lock = threading.Lock()

        def fake_build(task_dir, tag, log_path, timeout):
            with lock:
                self.builds["active"] += 1
                self.builds["max"] = max(self.builds["max"], self.builds["active"])
            time.sleep(0.05)
            with lock:
                self.builds["active"] -= 1
            if self.build_error:
                raise self.build_error

        monkeypatch.setattr(docker_ops, "ensure_runner_image", lambda log_path, timeout: "aq-runner:test")
        monkeypatch.setattr(docker_ops, "image_exists", lambda tag: False)
        monkeypatch.setattr(docker_ops, "build_task_image", fake_build)
        monkeypatch.setattr(
            docker_ops, "remove_labelled_resources", lambda label: self.removed.append(("labels", label))
        )
        monkeypatch.setattr(docker_ops, "remove_images", lambda *tags: self.removed.append(("images", tags)))
        monkeypatch.setattr(run_task, "WAIT_GRACE_SEC", 0)

    def submit(self, submission_id="sub1", n_attempts=1, archive=None, **task_kwargs):
        submission = Submission.create(submission_id, n_attempts, "oracle", None)
        paths = self.runner.paths(submission_id)
        paths.root.mkdir(parents=True)
        paths.upload.write_bytes(archive if archive is not None else task_zip(**task_kwargs))
        self.store.save(submission)
        return submission

    def write_trial_result(self, submission_id="sub1", attempt=0, resolved=True):
        trial_dir = self.runner.paths(submission_id).attempt(attempt) / "run" / "tiny-task" / "trial"
        trial_dir.mkdir(parents=True)
        trial_dir.joinpath("results.json").write_text(
            json.dumps(
                {"parser_results": {"test_ok": "passed" if resolved else "failed"}, "is_resolved": resolved}
            )
        )


def launched_wave(size: int) -> Wave:
    return Wave(index=0, offset=0, size=size, launched_at=utcnow())


@pytest.fixture
def harness(settings, monkeypatch):
    return lambda snapshots: Harness(settings, FakeKube(snapshots), monkeypatch)


def test_happy_path_completes_and_cleans_up(harness):
    h = harness([running_snapshot(), finished_snapshot()])
    h.submit()
    h.write_trial_result()
    outcome = h.runner.run("sub1")
    assert outcome["status"] == "completed" and outcome["passed"] is True
    assert len(h.kube.created) == 1 and h.kube.deleted == ["aq-sub1-w0"]
    assert h.kube.deleted_submissions == ["sub1"]
    assert ("labels", "aq.submission=sub1") in h.removed
    assert h.store.get("sub1").launched_at is not None


def test_transient_kubernetes_errors_do_not_fail_the_submission(harness):
    h = harness(
        [RuntimeError("apiserver blip"), RuntimeError("again"), running_snapshot(), finished_snapshot()]
    )
    h.submit()
    h.write_trial_result()
    assert h.runner.run("sub1")["status"] == "completed"


def test_unstartable_pods_fail_fast(harness):
    stuck = JobSnapshot(
        exists=True, attempts=[AttemptProgress(index=0, reason="ErrImageNeverPull: not present")]
    )
    h = harness([stuck])
    h.submit()
    outcome = h.runner.run("sub1")
    assert outcome["status"] == "failed" and "ErrImageNeverPull" in outcome["error"]
    assert h.kube.deleted_submissions == ["sub1"]


def test_job_deadline_is_attributed_to_attempts_whose_pods_vanished(harness):
    running = JobSnapshot(
        exists=True, attempts=[AttemptProgress(index=0, state="running", pods=["aq-sub1-0-abc"])]
    )
    deadline = JobSnapshot(
        exists=True, finished=True, reason="DeadlineExceeded", attempts=[AttemptProgress(index=0)]
    )
    h = harness([running, deadline])
    h.submit()
    outcome = h.runner.run("sub1")
    attempt = outcome and h.store.get("sub1").progress.attempts[0]
    assert (attempt.pod, attempt.state, attempt.reason) == (
        "aq-sub1-0-abc",
        "failed",
        "job failed: DeadlineExceeded",
    )
    assert outcome["attempts"][0]["error"] == "job failed: DeadlineExceeded"


def test_retried_pods_are_remembered_and_all_their_logs_saved(harness):
    first = JobSnapshot(exists=True, attempts=[AttemptProgress(index=0, state="running", pods=["p0"])])
    retried = JobSnapshot(exists=True, attempts=[AttemptProgress(index=0, state="running", pods=["p1"])])
    gone = JobSnapshot(
        exists=True, finished=True, reason="DeadlineExceeded", attempts=[AttemptProgress(index=0)]
    )
    h = harness([first, retried, gone])
    h.kube.pod_log = lambda pod: f"log of {pod}"
    h.submit()
    outcome = h.runner.run("sub1")
    attempt = h.store.get("sub1").progress.attempts[0]
    assert (attempt.pods, attempt.retries) == (["p0", "p1"], 1)
    assert outcome["attempts"][0]["retries"] == 1
    attempt_dir = h.runner.paths("sub1").attempt(0)
    assert [p.read_text() for p in sorted(attempt_dir.glob("pod-try-*.log"))] == ["log of p0", "log of p1"]


def test_vanished_job_is_reported_as_such(harness):
    running = JobSnapshot(
        exists=True, attempts=[AttemptProgress(index=0, state="running", pods=["aq-sub1-0-abc"])]
    )
    h = harness([running, JobSnapshot(exists=False)])
    h.submit()
    outcome = h.runner.run("sub1")
    assert outcome["attempts"][0]["error"] == "job failed: JobNotFound"


def test_executor_deadline_stops_a_job_that_never_finishes(harness):
    h = harness([running_snapshot()])
    h.submit(agent_timeout=0.05, test_timeout=0.05)
    outcome = h.runner.run("sub1")
    assert h.kube.deleted.count("aq-sub1-w0") == 2
    assert outcome["status"] == "failed"
    assert h.store.get("sub1").error.startswith("no attempt produced test results")


def test_shutdown_leaves_submission_resumable(harness):
    h = harness([running_snapshot()])
    h.submit()
    threading.Timer(0.2, h.runner.stop).start()
    assert h.runner.run("sub1") is None
    stored = h.store.get("sub1")
    assert stored.status == Status.RUNNING and stored.finished_at is None
    assert h.kube.deleted == [] and h.kube.deleted_submissions == [] and h.removed == []
    assert [s.id for s in h.store.list_unfinished()] == ["sub1"]


def test_resume_adopts_running_job_without_recreating_it(harness):
    h = harness([running_snapshot(), finished_snapshot()])
    h.submit()
    h.store.update("sub1", lambda s: s.progress.waves.append(launched_wave(size=1)))
    h.write_trial_result()
    assert h.runner.run("sub1")["status"] == "completed"
    assert h.kube.created == []


def test_resume_never_relaunches_a_vanished_job(harness):
    h = harness([JobSnapshot(exists=False)])
    h.submit(n_attempts=2)
    h.store.update("sub1", lambda s: s.progress.waves.append(launched_wave(size=2)))
    h.write_trial_result(attempt=0)
    outcome = h.runner.run("sub1")
    assert h.kube.created == []
    assert outcome["status"] == "completed"
    assert [a["status"] for a in outcome["attempts"]] == ["completed", "error"]


def test_build_failure_fails_submission_without_launching(harness):
    h = harness([finished_snapshot()])
    h.build_error = docker_ops.BuildError("docker build failed:\nRUN exit 3")
    h.submit()
    outcome = h.runner.run("sub1")
    assert outcome["status"] == "failed" and "docker build failed" in outcome["error"]
    assert h.kube.created == []
    assert ("labels", "aq.submission=sub1") in h.removed


def test_corrupt_upload_fails_cleanly(harness):
    h = harness([finished_snapshot()])
    h.submit(archive=b"not a zip")
    outcome = h.runner.run("sub1")
    assert outcome["status"] == "failed" and "not a valid ZIP" in outcome["error"]


def test_concurrent_builds_are_bounded(harness):
    h = harness([finished_snapshot()])
    ids = [f"sub{i}" for i in range(4)]
    for submission_id in ids:
        h.submit(submission_id)
    threads = [threading.Thread(target=h.runner.run, args=(submission_id,)) for submission_id in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert h.builds["max"] == h.settings.max_concurrent_builds == 1


def test_resumed_wave_whose_job_vanished_only_blames_its_own_attempts(harness):
    h = harness([JobSnapshot(exists=False)])
    h.submit(n_attempts=8)
    launched = utcnow()

    def resume_mid_second_wave(s):
        s.progress.waves = [
            Wave(index=0, offset=0, size=5, launched_at=launched, done=True),
            Wave(index=1, offset=5, size=3, launched_at=launched),
        ]
        s.progress.attempts = [
            AttemptProgress(index=i, state="succeeded", pods=[f"aq-sub1-{i}"]) for i in range(5)
        ] + [AttemptProgress(index=i, state="running", pods=[f"aq-sub1-w1-{i - 5}"]) for i in range(5, 8)]

    h.store.update("sub1", resume_mid_second_wave)
    for attempt in range(5):
        h.write_trial_result(attempt=attempt)

    outcome = h.runner.run("sub1")
    assert h.kube.created == []
    assert "aq-sub1-w1" in h.kube.deleted
    errors = [a.get("error") for a in outcome["attempts"]]
    assert errors == [None] * 5 + ["job failed: JobNotFound"] * 3
    assert outcome["summary"]["resolved_attempts"] == 5


def test_failed_indexes_keep_each_attempts_own_failure_reason(harness):
    oom = AttemptProgress(index=0, state="failed", pods=["p0", "p1"], reason="OOMKilled (exit code 137)")
    h = harness([JobSnapshot(exists=True, finished=True, reason="FailedIndexes", attempts=[oom])])
    h.submit()
    outcome = h.runner.run("sub1")
    assert outcome["attempts"][0]["error"] == "OOMKilled (exit code 137)"
    assert outcome["attempts"][0]["retries"] == 1
