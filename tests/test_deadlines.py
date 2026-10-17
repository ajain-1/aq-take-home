"""Deadlines count running time only: queueing for cluster capacity is never charged."""

from pathlib import Path
from types import SimpleNamespace

from runner.config import RESOURCE_CLASSES, Settings
from runner.k8s import _pod_state, attempt_deadline_sec, build_job_manifest
from runner.models import AttemptProgress, AttemptState, TaskSpec, Wave

SPEC = TaskSpec(task_id="t", instruction="i", max_agent_timeout_sec=600, max_test_timeout_sec=120)
SETTINGS = Settings(attempt_overhead_sec=300)


def _pod(phase, reason=None, message=None, conditions=(), statuses=()):
    status = SimpleNamespace(
        phase=phase,
        reason=reason,
        message=message,
        conditions=list(conditions),
        container_statuses=list(statuses),
    )
    return SimpleNamespace(status=status)


def test_wave_clock_charges_running_and_queued_time_separately():
    wave = Wave(index=0, offset=0, size=2)
    pending = [AttemptProgress(index=0), AttemptProgress(index=1)]
    wave.advance_clock(pending, 30)
    running = [AttemptProgress(index=0, state=AttemptState.RUNNING), AttemptProgress(index=1)]
    wave.advance_clock(running, 10)
    wave.advance_clock([AttemptProgress(index=0, state=AttemptState.SUCCEEDED)], 5)
    assert (wave.queued_sec, wave.running_sec) == (30, 10)


def test_deadline_is_per_pod_not_per_job():
    manifest = build_job_manifest(
        submission_id="s1",
        spec=SPEC,
        wave=Wave(index=0, offset=0, size=3),
        runner_image="aq-runner:x",
        submission_root=Path("/data/s1"),
        task_root=Path("/data/s1/tasks"),
        output_root=Path("/data/s1/runs"),
        agent="oracle",
        model=None,
        resources=RESOURCE_CLASSES["small"],
        settings=SETTINGS,
    )
    assert "activeDeadlineSeconds" not in manifest["spec"]
    assert manifest["spec"]["template"]["spec"]["activeDeadlineSeconds"] == 600 + 120 + 300
    assert attempt_deadline_sec(SPEC, SETTINGS) == 1020


def test_unschedulable_pod_is_pending_with_scheduler_reason():
    condition = SimpleNamespace(
        type="PodScheduled", status="False", reason="Unschedulable", message="Insufficient memory"
    )
    assert _pod_state(_pod("Pending", conditions=[condition])) == (
        AttemptState.PENDING,
        "Unschedulable: Insufficient memory",
    )


def test_pod_deadline_is_reported_as_deadline_exceeded():
    state, reason = _pod_state(_pod("Failed", reason="DeadlineExceeded", message="Pod was active too long"))
    assert state == AttemptState.FAILED and reason.startswith("DeadlineExceeded")
