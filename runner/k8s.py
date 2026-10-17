"""Kubernetes Job management: one Indexed Job per wave of attempts, one index per attempt."""

import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.utils import parse_quantity

from runner.config import ResourceClass, Settings
from runner.models import AttemptProgress, AttemptState, TaskSpec, Wave

MANAGED_BY = "aq-task-executor"
COMPLETION_INDEX_ANNOTATION = "batch.kubernetes.io/job-completion-index"
FATAL_WAITING_REASONS = {
    "ErrImageNeverPull",
    "ErrImagePull",
    "ImagePullBackOff",
    "InvalidImageName",
    "CreateContainerConfigError",
    "CreateContainerError",
    "FailedMount",
}
# Volume failures surface only as pod events, which the kubelet keeps retrying; a few
# repeats rule out a transient hiccup.
FATAL_EVENT_REASONS = {"FailedMount", "FailedAttachVolume"}
FATAL_EVENT_MIN_COUNT = 3
DOCKER_SOCKET = "/var/run/docker.sock"


@dataclass
class JobSnapshot:
    exists: bool
    finished: bool = False
    reason: str | None = None
    attempts: list[AttemptProgress] = field(default_factory=list)

    @property
    def fatal_reason(self) -> str | None:
        return next(
            (a.reason for a in self.attempts if a.reason and a.reason.split(":")[0] in FATAL_WAITING_REASONS),
            None,
        )


def api_error_message(error: ApiException) -> str:
    try:
        return json.loads(error.body)["message"]
    except (TypeError, ValueError, KeyError):
        return f"{error.status} {error.reason}"


def job_name(submission_id: str, wave: int = 0) -> str:
    return f"aq-{submission_id}" if wave == 0 else f"aq-{submission_id}-w{wave}"


def job_deadline_sec(spec: TaskSpec, settings: Settings) -> int:
    per_try = spec.max_agent_timeout_sec + spec.max_test_timeout_sec + settings.attempt_overhead_sec
    return int(per_try * (1 + settings.retries_per_attempt))


def build_job_manifest(
    *,
    submission_id: str,
    spec: TaskSpec,
    wave: Wave,
    runner_image: str,
    submission_root: Path,
    task_root: Path,
    output_root: Path,
    agent: str,
    model: str | None,
    resources: ResourceClass,
    settings: Settings,
) -> dict:
    labels = {
        "app.kubernetes.io/managed-by": MANAGED_BY,
        "aq/submission": submission_id,
        "aq/wave": str(wave.index),
    }
    env = {
        "AQ_SUBMISSION_ID": submission_id,
        "AQ_ATTEMPT_OFFSET": str(wave.offset),
        "AQ_TASK_ROOT": str(task_root),
        "AQ_TASK_ID": spec.task_id,
        "AQ_OUTPUT_ROOT": str(output_root),
        "AQ_AGENT": agent,
        "AQ_MODEL": model or "",
        "AQ_HOST_PATH_PREFIX": settings.host_path_prefix,
    }
    secret_env = [
        {
            "name": key,
            "valueFrom": {"secretKeyRef": {"name": settings.llm_secret_name, "key": key, "optional": True}},
        }
        for key in settings.llm_secret_keys
    ]
    # Only this submission's directory is shared, at the same path as on the host.
    shared_dir = str(submission_root)
    # Kubernetes rejects a request above the limit; the harness limit wins if they clash.
    memory_request = min(resources.memory_request, settings.harness_memory_limit, key=parse_quantity)
    container = {
        "name": "trial",
        "image": runner_image,
        "imagePullPolicy": "Never",
        "env": [{"name": k, "value": v} for k, v in env.items()] + secret_env,
        "resources": {
            "requests": {"cpu": resources.cpu_request, "memory": memory_request},
            "limits": {"memory": settings.harness_memory_limit},
        },
        "volumeMounts": [
            {"name": "docker-socket", "mountPath": DOCKER_SOCKET},
            {"name": "submission", "mountPath": shared_dir},
        ],
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name(submission_id, wave.index), "labels": labels},
        "spec": {
            "completionMode": "Indexed",
            "completions": wave.size,
            "parallelism": wave.size,
            "backoffLimitPerIndex": settings.retries_per_attempt,
            "maxFailedIndexes": wave.size,
            "activeDeadlineSeconds": job_deadline_sec(spec, settings),
            "ttlSecondsAfterFinished": 24 * 3600,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "terminationGracePeriodSeconds": 30,
                    "containers": [container],
                    "volumes": [
                        {"name": "docker-socket", "hostPath": {"path": DOCKER_SOCKET, "type": "Socket"}},
                        {"name": "submission", "hostPath": {"path": shared_dir, "type": "DirectoryOrCreate"}},
                    ],
                },
            },
        },
    }


class KubeClient:
    """Loads cluster credentials on first use, so the API can start (and report the
    cluster as unavailable) without a working kubeconfig."""

    def __init__(self, namespace: str):
        self._namespace = namespace

    @cached_property
    def _api_client(self) -> client.ApiClient:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        return client.ApiClient()

    @property
    def _batch(self) -> client.BatchV1Api:
        return client.BatchV1Api(self._api_client)

    @property
    def _core(self) -> client.CoreV1Api:
        return client.CoreV1Api(self._api_client)

    def available(self) -> bool:
        try:
            self._core.list_namespaced_pod(self._namespace, limit=1, _request_timeout=5)
            return True
        except Exception:
            return False

    def upsert_secret(self, name: str, data: dict[str, str]) -> None:
        body = client.V1Secret(metadata=client.V1ObjectMeta(name=name), string_data=data)
        try:
            self._core.create_namespaced_secret(self._namespace, body)
        except ApiException as e:
            if e.status != 409:
                raise
            self._core.replace_namespaced_secret(name, self._namespace, body)

    def create_job(self, manifest: dict) -> None:
        """Idempotent: an existing Job with the same name is adopted, not duplicated."""
        try:
            self._batch.create_namespaced_job(self._namespace, manifest)
        except ApiException as e:
            if e.status != 409:
                raise

    def delete_submission_jobs(self, submission_id: str) -> None:
        self._batch.delete_collection_namespaced_job(
            self._namespace, label_selector=f"aq/submission={submission_id}", propagation_policy="Background"
        )

    def delete_job(self, name: str) -> None:
        try:
            self._batch.delete_namespaced_job(name, self._namespace, propagation_policy="Background")
        except ApiException as e:
            if e.status != 404:
                raise

    def pod_log(self, pod_name: str) -> str | None:
        try:
            return self._core.read_namespaced_pod_log(pod_name, self._namespace)
        except ApiException:
            return None

    def snapshot(self, name: str, wave: Wave) -> JobSnapshot:
        try:
            job = self._batch.read_namespaced_job(name, self._namespace)
        except ApiException as e:
            if e.status == 404:
                return JobSnapshot(exists=False)
            raise

        finished, reason = False, None
        for condition in job.status.conditions or []:
            if condition.type in ("Complete", "Failed") and condition.status == "True":
                finished, reason = True, condition.reason if condition.type == "Failed" else None

        pods = self._core.list_namespaced_pod(self._namespace, label_selector=f"job-name={name}").items
        attempts = _attempts_from_pods(pods, wave)
        for attempt in attempts:
            if attempt.state == AttemptState.PENDING and attempt.pod:
                attempt.reason = self._fatal_pod_event(attempt.pod) or attempt.reason
        return JobSnapshot(exists=True, finished=finished, reason=reason, attempts=attempts)

    def _fatal_pod_event(self, pod_name: str) -> str | None:
        events = self._core.list_namespaced_event(
            self._namespace, field_selector=f"involvedObject.kind=Pod,involvedObject.name={pod_name}"
        ).items
        for event in events:
            if event.reason in FATAL_EVENT_REASONS and (event.count or 1) >= FATAL_EVENT_MIN_COUNT:
                return f"{event.reason}: {event.message}"
        return None


def _attempts_from_pods(pods: list, wave: Wave) -> list[AttemptProgress]:
    by_index: dict[int, list] = {}
    for pod in pods:
        index = (pod.metadata.annotations or {}).get(COMPLETION_INDEX_ANNOTATION)
        if index is not None:
            by_index.setdefault(int(index), []).append(pod)

    attempts = []
    for local_index in range(wave.size):
        index = wave.offset + local_index
        tries = sorted(by_index.get(local_index, []), key=lambda pod: pod.metadata.creation_timestamp)
        if not tries:
            attempts.append(AttemptProgress(index=index))
            continue
        state, reason = _pod_state(tries[-1])
        pod_names = [pod.metadata.name for pod in tries]
        attempts.append(AttemptProgress(index=index, state=state, pods=pod_names, reason=reason))
    return attempts


def _pod_state(pod) -> tuple[AttemptState, str | None]:
    statuses = pod.status.container_statuses or []
    match pod.status.phase:
        case "Succeeded":
            return AttemptState.SUCCEEDED, None
        case "Failed":
            terminated = next((s.state.terminated for s in statuses if s.state.terminated), None)
            if terminated:
                return AttemptState.FAILED, f"{terminated.reason} (exit code {terminated.exit_code})"
            return AttemptState.FAILED, pod.status.reason or "pod failed"
        case "Running":
            return AttemptState.RUNNING, None
        case _:
            waiting = next((s.state.waiting for s in statuses if s.state.waiting), None)
            if waiting is None:
                return AttemptState.PENDING, None
            return AttemptState.PENDING, ": ".join(filter(None, [waiting.reason, waiting.message]))
