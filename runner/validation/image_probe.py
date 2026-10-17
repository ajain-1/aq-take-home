"""Inspects the built task image (no agent, no tests) for environment problems that
text alone can't reveal: paths the instruction promises that are missing or empty,
and tools the tests call that the image doesn't have."""

import re
import shlex
import subprocess
from collections.abc import Iterator
from pathlib import Path

from runner import docker_ops
from runner.validation.models import Finding, Severity, Stage
from runner.validation.static_checks import TaskContext

INSTRUCTION_PATH = re.compile(r"(?<![\w.:/`-])(/[\w.-]+(?:/[\w.-]+)*/?)")
SUBPROCESS_TOOL = re.compile(r"""subprocess\.\w+\(\s*\[\s*["']([\w.+-]+)["']""")
PROBE_TIMEOUT_SEC = 120


def _instruction_paths(ctx: TaskContext) -> list[str]:
    """Paths the instruction mentions, minus ones the agent or tests are meant to create."""
    created = set(re.findall(r">\s*(/[\w./-]+)", ctx.run_tests))
    for text in (ctx.instruction, ctx.solution or ""):
        created.update(re.findall(r"mkdir\s+(?:-\w+\s+)*(/[\w./-]+)", text))
    return sorted({
        path for path in INSTRUCTION_PATH.findall(ctx.instruction)
        if path.rstrip("/") and path not in created
    })


def _test_tools(ctx: TaskContext) -> list[str]:
    installed_by_run_tests = set(re.findall(r"[\w.+-]+", ctx.run_tests))
    return sorted({tool for tool in SUBPROCESS_TOOL.findall(ctx.tests) if tool not in installed_by_run_tests})


def _probe_script(paths: list[str], tools: list[str]) -> str:
    lines = []
    for path in paths:
        quoted, top = shlex.quote(path), shlex.quote("/" + path.strip("/").split("/")[0])
        lines.append(
            f"if [ -d {quoted} ]; then [ -z \"$(ls -A {quoted})\" ] && echo 'empty {path}'; "
            f"elif [ ! -e {quoted} ] && [ -e {top} ]; then echo 'missing {path}'; fi"
        )
    lines += [f"command -v {shlex.quote(tool)} >/dev/null 2>&1 || echo 'tool {tool}'" for tool in tools]
    return "\n".join(lines) + "\ntrue\n"


def _finding(check: str, severity: Severity, message: str, **details) -> Finding:
    return Finding(check=check, stage=Stage.IMAGE_PROBE, severity=severity, message=message, details=details or None)


def probe_image(ctx: TaskContext, tag: str, build_log: Path, build_timeout: float) -> Iterator[Finding]:
    try:
        docker_ops.build_task_image(ctx.task_dir, tag, build_log, build_timeout)
    except docker_ops.BuildError as e:
        yield _finding("image_builds", Severity.ERROR, f"task image does not build: {e}")
        return

    paths, tools = _instruction_paths(ctx), _test_tools(ctx)
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", "--entrypoint", "sh", tag, "-c", _probe_script(paths, tools)],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        yield _finding("image_probe", Severity.WARNING, "image probe timed out")
        return
    finally:
        docker_ops.remove_images(tag, f"{tag}-base")

    for line in result.stdout.splitlines():
        kind, _, subject = line.partition(" ")
        if kind == "empty":
            yield _finding(
                "instruction_path_empty", Severity.ERROR,
                f"instruction points the agent at {subject}, but it is empty in the image", path=subject,
            )
        elif kind == "missing":
            yield _finding(
                "instruction_path_missing", Severity.WARNING,
                f"instruction mentions {subject}, which does not exist in the image", path=subject,
            )
        elif kind == "tool":
            yield _finding(
                "test_tool_missing", Severity.ERROR,
                f"tests run `{subject}`, which is not installed in the image or by run-tests.sh", tool=subject,
            )
