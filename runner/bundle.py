"""Unpacks and validates a submitted task ZIP, and prepares it for terminal-bench."""

import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

import yaml
from pydantic import ValidationError

from runner.config import RESOURCE_CLASSES, ResourceClass
from runner.models import TaskSpec

REQUIRED_FILES = ("task.yaml", "Dockerfile", "run-tests.sh", "tests")
TASK_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")
MAX_ENTRIES = 10_000


class InvalidTaskBundle(ValueError):
    pass


def extract_zip(zip_path: Path, destination: Path, max_bytes: int) -> None:
    """Extract defensively: no path traversal, no symlinks, bounded size."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise InvalidTaskBundle(f"not a valid ZIP file: {e}") from e

    with archive:
        entries = [entry for entry in archive.infolist() if not _is_junk(entry.filename)]
        if len(entries) > MAX_ENTRIES:
            raise InvalidTaskBundle(f"ZIP has more than {MAX_ENTRIES} entries")
        if sum(entry.file_size for entry in entries) > max_bytes:
            raise InvalidTaskBundle(f"ZIP expands beyond {max_bytes} bytes")

        shutil.rmtree(destination, ignore_errors=True)
        destination.mkdir(parents=True)
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts:
                raise InvalidTaskBundle(f"unsafe path in ZIP: {entry.filename}")
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise InvalidTaskBundle(f"symlinks are not allowed: {entry.filename}")
            archive.extract(entry, destination)
            if mode := (entry.external_attr >> 16) & 0o777:
                (destination / path).chmod(mode | 0o600)


def _is_junk(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return any(part in ("__MACOSX", ".DS_Store", "__pycache__") for part in parts)


def locate_task_dir(root: Path) -> Path:
    """The task is the shallowest directory containing a task.yaml."""
    candidates = sorted(root.rglob("task.yaml"), key=lambda path: len(path.parts))
    if not candidates:
        raise InvalidTaskBundle("ZIP does not contain a task.yaml")
    task_dir = candidates[0].parent
    if task_dir == root:
        raise InvalidTaskBundle("ZIP must contain a single top-level task directory")
    return task_dir


def load_task_spec(task_dir: Path) -> TaskSpec:
    missing = [name for name in REQUIRED_FILES if not (task_dir / name).exists()]
    if missing:
        raise InvalidTaskBundle(f"task is missing required files: {', '.join(missing)}")

    task_id = task_dir.name
    if not TASK_ID_PATTERN.match(task_id):
        raise InvalidTaskBundle(
            f"task directory name {task_id!r} must be lowercase alphanumerics, '-', '_' or '.'"
        )

    try:
        raw = yaml.safe_load((task_dir / "task.yaml").read_text())
    except yaml.YAMLError as e:
        raise InvalidTaskBundle(f"task.yaml is not valid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise InvalidTaskBundle("task.yaml must be a mapping")

    try:
        spec = TaskSpec.model_validate({**raw, "task_id": task_id})
    except ValidationError as e:
        raise InvalidTaskBundle(f"task.yaml is invalid: {e}") from e

    if spec.resource_class not in RESOURCE_CLASSES:
        raise InvalidTaskBundle(
            f"unknown resource_class {spec.resource_class!r}; "
            f"expected one of {', '.join(RESOURCE_CLASSES)}"
        )
    return spec


def write_compose_file(task_dir: Path, image: str, submission_id: str, resources: ResourceClass) -> None:
    """terminal-bench drives tasks through docker compose. The image is prebuilt once per
    submission, so the compose file only references it and never builds."""
    labels = {"aq.submission": submission_id, "aq.attempt": "${AQ_ATTEMPT:-0}"}
    compose = {
        "services": {
            "client": {
                "image": image,
                "container_name": "${T_BENCH_TASK_DOCKER_CLIENT_CONTAINER_NAME}",
                "command": ["sh", "-c", "sleep infinity"],
                "environment": ["TEST_DIR=${T_BENCH_TEST_DIR}"],
                "volumes": [
                    "${AQ_HOST_PATH_PREFIX:-}${T_BENCH_TASK_LOGS_PATH}:${T_BENCH_CONTAINER_LOGS_PATH}",
                    "${AQ_HOST_PATH_PREFIX:-}${T_BENCH_TASK_AGENT_LOGS_PATH}:${T_BENCH_CONTAINER_AGENT_LOGS_PATH}",
                ],
                "cpus": resources.cpu_limit,
                "mem_limit": resources.memory_limit,
                "labels": labels,
            }
        },
        "networks": {"default": {"labels": labels}},
    }
    (task_dir / "docker-compose.yaml").write_text(yaml.safe_dump(compose, sort_keys=False))
