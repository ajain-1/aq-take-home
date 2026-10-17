"""Live robustness scenarios against a real API, Kubernetes cluster, and Docker daemon.

Starts its own API (port 8002, isolated data dir) under different settings, drives the
fixture tasks in tests/fixtures with the oracle agent (no LLM calls), injects failures,
and writes the observed evidence to tests/robustness/live_results.json.

Usage: python tests/robustness/live_scenarios.py [scenario_name ...]
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
DATA_DIR = ROOT / "data"
RESULTS_PATH = Path(__file__).resolve().parent / "live_results.json"
PORT = 8002
API = f"http://127.0.0.1:{PORT}"
SECRET_ENV_FILE = Path(os.environ.get("AQ_SECRET_ENV_FILE", ROOT / ".env"))

BASE_ENV = {
    "AQ_DATA_DIR": str(DATA_DIR),
    "AQ_POLL_INTERVAL_SEC": "2",
    "AQ_ATTEMPT_OVERHEAD_SEC": "30",
    "AQ_RETRIES_PER_ATTEMPT": "1",
    "AQ_MAX_UPLOAD_BYTES": "1000000",
}


class ScenarioFailed(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioFailed(message)


def sh(*command: str) -> str:
    return subprocess.run(command, capture_output=True, text=True).stdout.strip()


def secret_value() -> str | None:
    if not SECRET_ENV_FILE.exists():
        return os.environ.get("OPENROUTER_API_KEY")
    for line in SECRET_ENV_FILE.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "OPENROUTER_API_KEY":
            return value.strip()
    return None


class Api:
    """The API under test, run as a subprocess so it can be killed and restarted."""

    def __init__(self, name: str, extra_env: dict[str, str] | None = None):
        self.name = name
        self.env = {**os.environ, **BASE_ENV, **(extra_env or {})}
        if secret := secret_value():
            self.env["OPENROUTER_API_KEY"] = secret
        self.process: subprocess.Popen | None = None
        self.log_path = DATA_DIR / f"api-{name}.log"

    def start(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        log = self.log_path.open("a")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(PORT)],
            cwd=ROOT,
            env=self.env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        wait_for(lambda: get("/health")[0] == 200, 60, "API to become healthy")

    def stop(self, sig: int = signal.SIGTERM) -> None:
        if self.process and self.process.poll() is None:
            self.process.send_signal(sig)
            self.process.wait(timeout=180)

    def __enter__(self) -> "Api":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


def get(path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return 0, {}


def wait_for(predicate, timeout: float, what: str, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(interval)
    raise ScenarioFailed(f"timed out after {timeout:.0f}s waiting for {what}")


def zip_fixture(name: str) -> Path:
    path = Path(tempfile.mkdtemp()) / f"{name}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for file in sorted((FIXTURES / name).rglob("*")):
            archive.write(file, Path(name) / file.relative_to(FIXTURES / name))
    return path


def post(zip_path: Path, **fields) -> tuple[int, dict]:
    form = [arg for key, value in fields.items() for arg in ("-F", f"{key}={value}")]
    out = sh("curl", "-s", "-w", "\n%{http_code}", "-F", f"file=@{zip_path}", *form, f"{API}/submit")
    body, _, code = out.rpartition("\n")
    return int(code), json.loads(body or "{}")


def submit(fixture: str, n_attempts: int = 1, agent: str = "oracle") -> str:
    code, body = post(zip_fixture(fixture), n_attempts=n_attempts, agent=agent)
    check(code == 202, f"submit {fixture} returned {code}: {body}")
    return body["submission_id"]


def status(submission_id: str) -> dict:
    return get(f"/status/{submission_id}")[1]


def wait_terminal(submission_id: str, timeout: float = 600) -> dict:
    wait_for(
        lambda: status(submission_id).get("status") in ("completed", "failed"),
        timeout,
        f"{submission_id} to finish",
        2,
    )
    return get(f"/results/{submission_id}")[1]


def leftovers(submission_id: str) -> dict[str, list[str]]:
    label = f"label=aq.submission={submission_id}"
    return {
        "containers": sh("docker", "ps", "-aq", "--filter", label).split(),
        "networks": sh("docker", "network", "ls", "-q", "--filter", label).split(),
        "images": sh("docker", "images", "-q", f"aq-task-{submission_id}").split(),
        "jobs": sh("kubectl", "get", "jobs", "-l", f"aq/submission={submission_id}", "-o", "name").split(),
    }


def assert_cleaned_up(submission_id: str) -> dict:
    wait_for(lambda: not any(leftovers(submission_id).values()), 60, f"cleanup of {submission_id}", 2)
    return leftovers(submission_id)


def task_container(submission_id: str, attempt: int) -> str | None:
    ids = sh(
        "docker",
        "ps",
        "-q",
        "--filter",
        f"label=aq.submission={submission_id}",
        "--filter",
        f"label=aq.attempt={attempt}",
    )
    return ids.split()[0] if ids else None


def attempt_pod(submission_id: str, attempt: int) -> dict | None:
    attempts = status(submission_id).get("progress", {}).get("attempts", [])
    return next((a for a in attempts if a["index"] == attempt and a["pod"]), None)


def kill_pod_container(pod_name: str) -> str:
    container = wait_for(
        lambda: sh("docker", "ps", "-q", "--filter", f"name=k8s_trial_{pod_name}_"),
        30,
        f"container of {pod_name}",
    )
    sh("docker", "kill", container)
    return container


def summarize(results: dict) -> dict:
    return {
        key: results.get(key)
        for key in ("status", "passed", "passed_tests", "total_tests", "summary", "error")
    } | {
        "attempts": [
            {
                k: a.get(k)
                for k in (
                    "attempt",
                    "status",
                    "resolved",
                    "failure_mode",
                    "infrastructure_issues",
                    "retries",
                    "error",
                    "passed_tests",
                    "total_tests",
                )
            }
            for a in results.get("attempts", [])
        ]
    }


# --- scenarios ---------------------------------------------------------------------------


def happy_parallel_attempts() -> dict:
    sid = submit("rb-ok", n_attempts=2)
    results = wait_terminal(sid)
    check(results["status"] == "completed" and results["passed"], "both attempts should pass")
    logs = [DATA_DIR / "submissions" / sid / "runs" / f"attempt-{i}" / "pod-try-0.log" for i in range(2)]
    check(all(log.exists() and log.stat().st_size > 0 for log in logs), "pod logs captured for every attempt")
    return {
        "submission": sid,
        "results": summarize(results),
        "pod_logs": [str(log.relative_to(ROOT)) for log in logs],
        "leftovers": assert_cleaned_up(sid),
    }


def agent_timeout() -> dict:
    sid = submit("rb-agent-timeout")
    results = wait_terminal(sid)
    attempt = results["attempts"][0]
    check(results["status"] == "completed", "an agent timeout is a normal (unresolved) result")
    check(
        attempt["failure_mode"] == "agent_timeout" and not attempt["resolved"],
        f"expected agent_timeout, got {attempt}",
    )
    return {"submission": sid, "results": summarize(results), "leftovers": assert_cleaned_up(sid)}


def task_container_oom() -> dict:
    sid = submit("rb-oom")
    container = wait_for(lambda: task_container(sid, 0), 300, "task container")
    limits = "{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{.HostConfig.NanoCpus}}"
    memory = sh("docker", "inspect", "--format", limits, container)
    results = wait_terminal(sid)
    check(memory == f"{1024**3} {1024**3} {10**9}", f"task container capped at 1g, no swap, 1 CPU: {memory}")
    check(
        results["passed"], "allocation beyond the limit should be OOM-killed (exit 137) inside the container"
    )
    issues = results["attempts"][0]["infrastructure_issues"]
    check(any("OOM-killed" in issue for issue in issues), f"OOM flagged as an infrastructure issue: {issues}")
    return {
        "submission": sid,
        "task_container_memory_bytes_and_nanocpus": memory,
        "results": summarize(results),
        "leftovers": assert_cleaned_up(sid),
    }


def build_failure() -> dict:
    sid = submit("rb-build-fail")
    results = wait_terminal(sid)
    check(
        results["status"] == "failed" and "docker build failed" in (results["error"] or ""), f"got {results}"
    )
    check(not status(sid)["progress"]["attempts"], "no attempts should be launched after a failed build")
    return {"submission": sid, "error": results["error"], "leftovers": assert_cleaned_up(sid)}


def crash_retry_partial_orphans() -> dict:
    sid = submit("rb-slow", n_attempts=2)
    first_pod = wait_for(lambda: attempt_pod(sid, 1), 300, "attempt 1 pod")["pod"]
    first_task_container = wait_for(lambda: task_container(sid, 1), 300, "attempt 1 task container")
    manifest = sh("kubectl", "get", "job", f"aq-{sid}", "-o", "json")
    kill_pod_container(first_pod)

    retry = wait_for(lambda: (p := attempt_pod(sid, 1)) and p["pod"] != first_pod and p, 120, "retry pod")
    wait_for(
        lambda: (c := task_container(sid, 1)) and c != first_task_container and c,
        300,
        "retried task container",
    )
    orphan_removed_by_retry = sh("docker", "ps", "-aq", "--filter", f"id={first_task_container}") == ""
    kill_pod_container(retry["pod"])

    results = wait_terminal(sid)
    attempts = {a["attempt"]: a for a in results["attempts"]}
    check(results["status"] == "completed", "one surviving attempt keeps the submission completed")
    check(
        attempts[0]["status"] == "completed" and attempts[0]["resolved"],
        "attempt 0 unaffected by attempt 1 crashes",
    )
    check(
        attempts[1]["status"] == "error" and attempts[1]["retries"] == 1,
        f"attempt 1 retried once then errored: {attempts[1]}",
    )
    check("exit code 137" in attempts[1]["error"], "crash reason surfaced")
    check(orphan_removed_by_retry, "retried pod removes the orphaned task container of the killed try")
    attempt_dir = DATA_DIR / "submissions" / sid / "runs" / "attempt-1"
    try_logs = sorted(path.name for path in attempt_dir.glob("pod-try-*.log"))
    check(try_logs == ["pod-try-0.log", "pod-try-1.log"], f"logs of both killed tries kept: {try_logs}")
    secret = secret_value()
    check(
        bool(secret) and secret not in manifest and "secretKeyRef" in manifest,
        "Job manifest references, never embeds, the key",
    )
    return {
        "submission": sid,
        "killed_pods": [first_pod, retry["pod"]],
        "orphan_removed_by_retry": orphan_removed_by_retry,
        "pod_try_logs": try_logs,
        "results": summarize(results),
        "leftovers": assert_cleaned_up(sid),
    }


def job_deadline() -> dict:
    sid = submit("rb-hang")
    started = time.monotonic()
    results = wait_terminal(sid)
    elapsed = round(time.monotonic() - started)
    check(results["status"] == "failed", "a hung attempt produces no results")
    check("DeadlineExceeded" in (results["error"] or ""), f"deadline reason surfaced: {results['error']}")
    return {
        "submission": sid,
        "elapsed_sec": elapsed,
        "job_deadline_sec": (10 + 10 + 30) * 2,
        "results": summarize(results),
        "leftovers": assert_cleaned_up(sid),
    }


def validation_rejections() -> dict:
    tmp = Path(tempfile.mkdtemp())

    def zip_of(entries: dict[str, str], symlink: str | None = None) -> Path:
        path = tmp / f"case-{len(list(tmp.iterdir()))}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
            if symlink:
                info = zipfile.ZipInfo(symlink)
                info.external_attr = 0o120777 << 16
                archive.writestr(info, "/etc/passwd")
        return path

    good = {
        f"rb-ok/{p.relative_to(FIXTURES / 'rb-ok')}": p.read_text()
        for p in (FIXTURES / "rb-ok").rglob("*")
        if p.is_file()
    }
    oversized = tmp / "oversized.zip"
    oversized.write_bytes(os.urandom(1_100_000))
    cases = {
        "path_traversal": (zip_of({**good, "../../escape.txt": "x"}), {}),
        "symlink": (zip_of(good, symlink="rb-ok/link"), {}),
        "missing_files": (zip_of({k: v for k, v in good.items() if not k.endswith("run-tests.sh")}), {}),
        "bad_yaml": (zip_of({**good, "rb-ok/task.yaml": "instruction: [unclosed"}), {}),
        "unknown_resource_class": (
            zip_of({**good, "rb-ok/task.yaml": "instruction: x\nresource_class: huge"}),
            {},
        ),
        "not_a_zip": (tmp / "plain.txt", {}),
        "oversized_upload": (oversized, {}),
        "zero_attempts": (zip_of(good), {"n_attempts": 0}),
        "too_many_attempts": (zip_of(good), {"n_attempts": 11}),
        "non_integer_attempts": (zip_of(good), {"n_attempts": "abc"}),
        "unknown_agent": (zip_of(good), {"agent": "evil"}),
    }
    (tmp / "plain.txt").write_text("hello")
    before = get("/health")[1]["submissions_tracked"]
    observed = {}
    for name, (path, fields) in cases.items():
        code, body = post(path, **fields)
        observed[name] = {"http_status": code, "detail": str(body.get("detail"))[:160]}
    after = get("/health")[1]["submissions_tracked"]
    check(
        all(o["http_status"] == 422 for o in observed.values()), f"every case rejected with 422: {observed}"
    )
    check(before == after, "rejected uploads are not tracked")
    check(not (DATA_DIR / "escape.txt").exists() and not (ROOT / "escape.txt").exists(), "nothing escaped")
    return {"cases": observed, "submissions_tracked_before_after": [before, after]}


def restart_sigkill_while_running(api: Api) -> dict:
    sid = submit("rb-slow")
    pod = wait_for(
        lambda: (p := attempt_pod(sid, 0)) and p["state"] == "running" and p, 300, "attempt running"
    )
    api.stop(signal.SIGKILL)
    api.start()
    results = wait_terminal(sid)
    check(results["status"] == "completed" and results["passed"], "resumed submission completes")
    check(results["attempts"][0]["retries"] == 0, "the running attempt was adopted, not restarted")
    resumed = "resuming submission " + sid in api.log_path.read_text()
    check(resumed, "API logged the resume")
    return {
        "submission": sid,
        "pod": pod["pod"],
        "resumed_logged": resumed,
        "results": summarize(results),
        "leftovers": assert_cleaned_up(sid),
    }


def restart_sigterm_while_building(api: Api) -> dict:
    sid = submit("rb-build-sleep")
    wait_for(lambda: status(sid)["progress"]["phase"] == "building_image", 60, "build phase")
    shutdown_started = time.monotonic()
    api.stop(signal.SIGTERM)
    shutdown_sec = round(time.monotonic() - shutdown_started)
    api.start()
    results = wait_terminal(sid)
    check(
        results["status"] == "completed" and results["passed"], "submission completes after graceful restart"
    )
    return {
        "submission": sid,
        "graceful_shutdown_sec": shutdown_sec,
        "results": summarize(results),
        "leftovers": assert_cleaned_up(sid),
    }


def restart_after_job_vanished(api: Api) -> dict:
    sid = submit("rb-slow")
    wait_for(lambda: (p := attempt_pod(sid, 0)) and p["state"] == "running", 300, "attempt running")
    api.stop(signal.SIGKILL)
    sh("kubectl", "delete", "job", f"aq-{sid}", "--wait=true")
    api.start()
    results = wait_terminal(sid)
    recreated = sh("kubectl", "get", "jobs", "-l", f"aq/submission={sid}", "-o", "name")
    check(not recreated, "a vanished Job must not be relaunched on resume")
    check(
        results["status"] == "failed" and results["attempts"][0]["error"] == "job failed: JobNotFound",
        f"got {summarize(results)}",
    )
    return {"submission": sid, "results": summarize(results), "leftovers": assert_cleaned_up(sid)}


def restart_with_queued_backlog(api: Api) -> dict:
    first = submit("rb-slow")
    second = submit("rb-ok")
    wait_for(lambda: status(first)["status"] == "running", 60, "first running")
    time.sleep(5)
    second_while_first_runs = status(second)["status"]
    check(second_while_first_runs == "queued", "worker pool of 1 keeps the second submission queued")
    api.stop(signal.SIGKILL)
    api.start()
    outcomes = {sid: wait_terminal(sid) for sid in (first, second)}
    check(
        all(r["status"] == "completed" and r["passed"] for r in outcomes.values()), "both resume and complete"
    )
    return {
        "second_status_while_first_running": second_while_first_runs,
        "results": {sid: summarize(r) for sid, r in outcomes.items()},
        "leftovers": {sid: assert_cleaned_up(sid) for sid in outcomes},
    }


def harness_oom_retry() -> dict:
    sid = submit("rb-ok")
    results = wait_terminal(sid)
    attempt = results["attempts"][0]
    check(results["status"] == "failed", "an attempt OOM-killed on every try produces no results")
    check(
        "OOMKilled" in (attempt.get("error") or "") and attempt["retries"] == 1,
        f"OOM surfaced after one retry: {attempt}",
    )
    return {"submission": sid, "results": summarize(results), "leftovers": assert_cleaned_up(sid)}


def unstartable_pod_fails_fast() -> dict:
    sid = submit("rb-ok")
    started = time.monotonic()
    results = wait_terminal(sid, timeout=180)
    elapsed = round(time.monotonic() - started)
    check(
        results["status"] == "failed" and "ErrImageNeverPull" in (results["error"] or ""),
        f"got {results.get('error')}",
    )
    check(elapsed < 120, f"should fail well before the Job deadline, took {elapsed}s")
    return {
        "submission": sid,
        "elapsed_sec": elapsed,
        "error": results["error"],
        "leftovers": assert_cleaned_up(sid),
    }


def build_timeout() -> dict:
    sid = submit("rb-build-slow")
    started = time.monotonic()
    results = wait_terminal(sid, timeout=180)
    elapsed = round(time.monotonic() - started)
    check(
        results["status"] == "failed" and "timed out after 15s" in (results["error"] or ""),
        f"got {results.get('error')}",
    )
    return {
        "submission": sid,
        "elapsed_sec": elapsed,
        "error": results["error"],
        "leftovers": assert_cleaned_up(sid),
    }


def secret_not_leaked() -> dict:
    secret = secret_value()
    check(bool(secret), "a key must be configured to check for leaks")
    hits = sh("grep", "-rl", secret, str(DATA_DIR))
    return (
        {"files_containing_key": hits.split()}
        if hits
        else {"files_containing_key": [], "scanned": str(DATA_DIR.relative_to(ROOT))}
    )


# Each group runs against an API with its own settings; scenarios within a batch run concurrently.
GROUPS = [
    (
        "base",
        {},
        [
            [validation_rejections],
            [happy_parallel_attempts, agent_timeout, task_container_oom, build_failure],
            [crash_retry_partial_orphans, job_deadline],
            [restart_sigkill_while_running],
            [restart_sigterm_while_building],
            [restart_after_job_vanished],
        ],
    ),
    ("single-worker", {"AQ_MAX_CONCURRENT_SUBMISSIONS": "1"}, [[restart_with_queued_backlog]]),
    ("tiny-harness-memory", {"AQ_HARNESS_MEMORY_LIMIT": "48Mi"}, [[harness_oom_retry]]),
    (
        "broken-runner-image",
        {"AQ_RUNNER_IMAGE": "aq-runner:does-not-exist", "AQ_BUILD_TIMEOUT_SEC": "15"},
        [[unstartable_pod_fails_fast, build_timeout]],
    ),
    ("final", {}, [[secret_not_leaked]]),
]


def run_scenario(scenario, api: Api) -> dict:
    started = time.monotonic()
    try:
        takes_api = scenario.__code__.co_argcount == 1
        evidence = scenario(api) if takes_api else scenario()
        outcome = {"result": "pass", "evidence": evidence}
    except Exception as e:
        outcome = {
            "result": "fail",
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc()[-1500:],
        }
    outcome["duration_sec"] = round(time.monotonic() - started)
    print(f"[{outcome['result'].upper()}] {scenario.__name__} ({outcome['duration_sec']}s)", flush=True)
    return outcome


def main(selected: list[str]) -> int:
    recorded = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else {}
    lock = threading.Lock()
    for group, env, batches in GROUPS:
        batches = [[s for s in batch if not selected or s.__name__ in selected] for batch in batches]
        if not any(batches):
            continue
        with Api(group, env) as api:
            for batch in filter(None, batches):
                with ThreadPoolExecutor(len(batch)) as pool:
                    outcomes = pool.map(lambda s: run_scenario(s, api), batch)
                    for scenario, outcome in zip(batch, outcomes, strict=True):
                        with lock:
                            recorded[scenario.__name__] = {"group": group, **outcome}
                RESULTS_PATH.write_text(json.dumps(recorded, indent=2, default=str))
    failed = [name for name, outcome in recorded.items() if outcome["result"] != "pass"]
    print(
        f"{len(recorded) - len(failed)}/{len(recorded)} scenarios passed"
        + (f"; failed: {failed}" if failed else "")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
