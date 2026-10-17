import json

from runner import results
from runner.config import RESOURCE_CLASSES
from runner.k8s import JobSnapshot, _pod_state, build_job_manifest, job_deadline_sec
from runner.models import AttemptProgress, AttemptState, TaskSpec, Wave


def _write_trial(attempt_dir, task_id, parser_results, resolved):
    trial_dir = attempt_dir / "run" / task_id / f"{task_id}.1-of-1.run"
    (trial_dir / "panes").mkdir(parents=True)
    (trial_dir / "results.json").write_text(
        json.dumps({"parser_results": parser_results, "is_resolved": resolved, "failure_mode": "unset"})
    )
    (trial_dir / "panes" / "post-test.txt").write_text("apt noise\n==== test session starts ====\nPASSED x\n")


def test_partial_results_when_one_attempt_crashed(tmp_path):
    _write_trial(tmp_path / "attempt-0", "t", {"test_a": "passed", "test_b": "passed"}, True)
    crashed = AttemptProgress(
        index=1, state=AttemptState.FAILED, pods=["p0", "p1"], reason="OOMKilled (exit code 137)"
    )
    attempts = [
        results.collect_attempt(tmp_path / "attempt-0", "t", AttemptProgress(index=0), tmp_path),
        results.collect_attempt(tmp_path / "attempt-1", "t", crashed, tmp_path),
    ]

    assert attempts[0]["status"] == "completed"
    assert attempts[0]["pytest_output"].startswith("==== test session starts")
    assert attempts[1] == {
        "attempt": 1,
        "status": "error",
        "resolved": False,
        "error": "OOMKilled (exit code 137)",
        "retries": 1,
        "infrastructure_issues": [],
        "tests": [],
        "passed_tests": 0,
        "total_tests": 0,
    }

    summary = results.aggregate(attempts)
    assert summary["passed"] is False
    assert summary["summary"] == {
        "n_attempts": 2,
        "completed_attempts": 1,
        "tests_not_run_attempts": 0,
        "errored_attempts": 1,
        "resolved_attempts": 1,
        "pass_rate": 0.5,
    }
    assert (summary["passed_tests"], summary["total_tests"]) == (2, 2)


def test_task_container_oom_is_flagged_as_infrastructure_issue(tmp_path):
    _write_trial(tmp_path / "attempt-0", "t", {"test_a": "failed"}, False)
    (tmp_path / "attempt-0" / results.TASK_CONTAINER_EVENTS_FILE).write_text(
        json.dumps({"status": "oom", "Action": "oom"}) + "\n" + json.dumps({"Action": "die"}) + "\n"
    )
    attempt = results.collect_attempt(tmp_path / "attempt-0", "t", AttemptProgress(index=0), tmp_path)
    assert attempt["infrastructure_issues"] == [
        "task container was OOM-killed (exceeded its resource_class memory limit)"
    ]


def test_per_test_pass_rates_across_attempts(tmp_path):
    _write_trial(tmp_path / "attempt-0", "t", {"test_a": "passed", "test_b": "failed"}, False)
    _write_trial(tmp_path / "attempt-1", "t", {"test_a": "passed", "test_b": "passed"}, True)
    attempts = [
        results.collect_attempt(tmp_path / f"attempt-{i}", "t", AttemptProgress(index=i), tmp_path)
        for i in range(2)
    ]
    summary = results.aggregate(attempts)
    rates = {test["name"]: test["pass_rate"] for test in summary["tests"]}
    assert rates == {"test_a": 1.0, "test_b": 0.5}
    assert (summary["passed_tests"], summary["passed"]) == (1, False)


def test_manifest_derives_limits_and_never_inlines_secrets(settings, tmp_path):
    spec = TaskSpec(task_id="t", instruction="x", max_agent_timeout_sec=100, max_test_timeout_sec=20)
    manifest = build_job_manifest(
        submission_id="abc",
        spec=spec,
        wave=Wave(index=0, offset=0, size=3),
        runner_image="aq-runner:x",
        submission_root=tmp_path,
        task_root=tmp_path,
        output_root=tmp_path,
        agent="terminus-1",
        model="m",
        resources=RESOURCE_CLASSES["large"],
        settings=settings,
    )
    job = manifest["spec"]
    container = job["template"]["spec"]["containers"][0]
    assert (job["completions"], job["parallelism"], job["completionMode"]) == (3, 3, "Indexed")
    assert job["backoffLimitPerIndex"] == settings.retries_per_attempt
    assert job["activeDeadlineSeconds"] == job_deadline_sec(spec, settings) == 120
    assert container["resources"]["requests"] == {"cpu": "1", "memory": "2Gi"}
    assert container["resources"]["limits"] == {"memory": settings.harness_memory_limit}
    secret_env = [e for e in container["env"] if e["name"] == "OPENROUTER_API_KEY"]
    assert secret_env == [
        {
            "name": "OPENROUTER_API_KEY",
            "valueFrom": {
                "secretKeyRef": {
                    "name": settings.llm_secret_name,
                    "key": "OPENROUTER_API_KEY",
                    "optional": True,
                }
            },
        }
    ]


def test_memory_request_never_exceeds_harness_limit(settings, tmp_path):
    from dataclasses import replace

    spec = TaskSpec(task_id="t", instruction="x")
    manifest = build_job_manifest(
        submission_id="abc",
        spec=spec,
        wave=Wave(index=0, offset=0, size=1),
        runner_image="aq-runner:x",
        submission_root=tmp_path,
        task_root=tmp_path,
        output_root=tmp_path,
        agent="oracle",
        model=None,
        resources=RESOURCE_CLASSES["large"],
        settings=replace(settings, harness_memory_limit="48Mi"),
    )
    resources = manifest["spec"]["template"]["spec"]["containers"][0]["resources"]
    assert resources["requests"]["memory"] == resources["limits"]["memory"] == "48Mi"


def test_fatal_waiting_reasons_are_detected():
    stuck = AttemptProgress(index=0, reason="ErrImageNeverPull: image not present with pull policy of Never")
    assert JobSnapshot(exists=True, attempts=[stuck]).fatal_reason.startswith("ErrImageNeverPull")
    scheduling = AttemptProgress(index=0, reason="ContainerCreating")
    assert JobSnapshot(exists=True, attempts=[scheduling]).fatal_reason is None


class _Obj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_oom_killed_pod_reason_is_surfaced():
    terminated = _Obj(reason="OOMKilled", exit_code=137)
    pod = _Obj(
        status=_Obj(
            phase="Failed",
            reason=None,
            container_statuses=[_Obj(state=_Obj(terminated=terminated, waiting=None))],
        )
    )
    assert _pod_state(pod) == (AttemptState.FAILED, "OOMKilled (exit code 137)")
