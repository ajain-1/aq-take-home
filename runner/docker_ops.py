"""Docker operations on the host daemon: image builds and label-based cleanup."""

import hashlib
import json
import subprocess
import threading
from pathlib import Path

from runner.config import REPO_ROOT

RUNNER_IMAGE_REPO = "aq-runner"
RUNNER_IMAGE_SOURCES = ("runner/Dockerfile", "runner/trial_entrypoint.py", "terminal_bench")

# terminal-bench needs tmux (and asciinema for recordings) inside the task container.
# Tasks are plain images, so the executor layers these on rather than requiring every
# task author to install them.
AGENT_RUNTIME_DOCKERFILE = """\
FROM {base}
USER root
RUN if command -v tmux >/dev/null && command -v asciinema >/dev/null; then exit 0; \\
    elif command -v apt-get >/dev/null; then \\
        apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tmux asciinema \\
        && rm -rf /var/lib/apt/lists/*; \\
    elif command -v apk >/dev/null; then apk add --no-cache bash tmux asciinema; \\
    elif command -v dnf >/dev/null; then dnf install -y tmux asciinema && dnf clean all; \\
    else echo "unsupported base image: tmux and asciinema are required" >&2; exit 1; fi
USER {user}
"""

_runner_image_lock = threading.Lock()


class BuildError(RuntimeError):
    pass


def _run(command: list[str], timeout: float | None = None, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, **kwargs)


def image_exists(tag: str) -> bool:
    return _run(["docker", "image", "inspect", tag]).returncode == 0


def _build(command: list[str], log_path: Path, timeout: float, stdin: str | None = None) -> None:
    try:
        result = _run(command, timeout=timeout, input=stdin)
    except subprocess.TimeoutExpired as e:
        raise BuildError(f"docker build timed out after {timeout:.0f}s") from e
    with log_path.open("a") as log:
        log.write(f"$ {' '.join(command)}\n{result.stdout}{result.stderr}\n")
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-15:])
        raise BuildError(f"docker build failed:\n{tail}")


def _runner_source_digest() -> str:
    digest = hashlib.sha256()
    for source in RUNNER_IMAGE_SOURCES:
        root = REPO_ROOT / source
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for path in files:
            if "__pycache__" in path.parts:
                continue
            digest.update(str(path.relative_to(REPO_ROOT)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def ensure_runner_image(log_path: Path, timeout: float) -> str:
    """Build the Job pod image once per version of its sources (content-addressed tag)."""
    tag = f"{RUNNER_IMAGE_REPO}:{_runner_source_digest()}"
    with _runner_image_lock:
        if not image_exists(tag):
            _build(
                ["docker", "build", "-f", str(REPO_ROOT / "runner/Dockerfile"), "-t", tag, str(REPO_ROOT)],
                log_path,
                timeout,
            )
    return tag


def build_task_image(task_dir: Path, tag: str, log_path: Path, timeout: float) -> None:
    """Build the task's Dockerfile, then layer the agent runtime on top of it."""
    base_tag = f"{tag}-base"
    _build(["docker", "build", "-t", base_tag, str(task_dir)], log_path, timeout)

    config = json.loads(_run(["docker", "image", "inspect", "--format", "{{json .Config}}", base_tag]).stdout)
    dockerfile = AGENT_RUNTIME_DOCKERFILE.format(base=base_tag, user=config.get("User") or "root")
    _build(["docker", "build", "-t", tag, "-"], log_path, timeout, stdin=dockerfile)


def remove_images(*tags: str) -> None:
    _run(["docker", "image", "rm", "-f", *tags])


def remove_labelled_resources(label: str) -> None:
    """Remove task containers and networks left behind by killed or crashed pods."""
    containers = _run(["docker", "ps", "-aq", "--filter", f"label={label}"]).stdout.split()
    if containers:
        _run(["docker", "rm", "-f", *containers])
    networks = _run(["docker", "network", "ls", "-q", "--filter", f"label={label}"]).stdout.split()
    if networks:
        _run(["docker", "network", "rm", *networks])


def docker_available() -> bool:
    try:
        return _run(["docker", "info"], timeout=5).returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
