"""Kubernetes Job management: one Indexed Job per submission, one index per attempt."""

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from runner.config import ResourceClass, Settings
from runner.models import AttemptProgress, AttemptState, TaskSpec

MANAGED_BY = "aq-task-executor"
COMPLETION_INDEX_ANNOTATION = "batch.kubernetes.io/job-completion-index"
FATAL_WAITING_REASONS = {
    "ErrImageNeverPull",
    "ErrImagePull",
    "ImagePullBackOff",
    "InvalidImageName",
    "CreateContainerConfigError",
    "CreateContainerError",
}
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


def job_name(submission_id: str) -> str:
    return f"aq-{submission_id}"


def job_deadline_sec(spec: TaskSpec, settings: Settings) -> int:
    per_try = spec.max_agent_timeout_sec + spec.max_test_timeout_sec + settings.attempt_overhead_sec
    return int(per_try * (1 + settings.retries_per_attempt))


def build_job_manifest(
    *,
    submission_id: str,
    spec: TaskSpec,
    n_attempts: int,
    runner_image: str,
    task_root: Path,
    output_root: Path,
    agent: str,
    model: str | None,
    resources: ResourceClass,
    settings: Settings,
) -> dict:
    labels = {"app.kubernetes.io/managed-by": MANAGED_BY, "aq/submission": submission_id}
    env = {
        "AQ_SUBMISSION_ID": submission_id,
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
    data_dir = str(settings.data_dir)
    container = {
        "name": "trial",
        "image": runner_image,
        "imagePullPolicy": "Never",
        "env": [{"name": k, "value": v} for k, v in env.items()] + secret_env,
        "resources": {
            "requests": {"cpu": resources.cpu_request, "memory": resources.memory_request},
            "limits": {"memory": settings.harness_memory_limit},
        },
        "volumeMounts": [
            {"name": "docker-socket", "mountPath": DOCKER_SOCKET},
            {"name": "data", "mountPath": data_dir},
        ],
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name(submission_id), "labels": labels},
        "spec": {
            "completionMode": "Indexed",
            "completions": n_attempts,
            "parallelism": n_attempts,
            "backoffLimitPerIndex": settings.retries_per_attempt,
            "maxFailedIndexes": n_attempts,
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
                        {"name": "data", "hostPath": {"path": data_dir, "type": "DirectoryOrCreate"}},
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

    def snapshot(self, name: str, n_attempts: int) -> JobSnapshot:
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
        return JobSnapshot(exists=True, finished=finished, reason=reason, attempts=_attempts_from_pods(pods, n_attempts))


def _attempts_from_pods(pods: list, n_attempts: int) -> list[AttemptProgress]:
    by_index: dict[int, list] = {}
    for pod in pods:
        index = (pod.metadata.annotations or {}).get(COMPLETION_INDEX_ANNOTATION)
        if index is not None:
            by_index.setdefault(int(index), []).append(pod)

    attempts = []
    for index in range(n_attempts):
        tries = sorted(by_index.get(index, []), key=lambda pod: pod.metadata.creation_timestamp)
        if not tries:
            attempts.append(AttemptProgress(index=index))
            continue
        state, reason = _pod_state(tries[-1])
        attempts.append(
            AttemptProgress(index=index, state=state, pods=[pod.metadata.name for pod in tries], reason=reason)
        )
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
