"""Container-free checks that catch broken tasks before any compute is spent.

Each check reads a TaskContext and yields findings. They are heuristics over the
task's text (task.yaml, Dockerfile, run-tests.sh, tests, solution), tuned to flag the
mismatches that make a task unsolvable or make its tests meaningless.
"""

import re
import shlex
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from runner import bundle
from runner.models import TaskSpec
from runner.validation.models import Finding, Severity, Stage

SYSTEM_ROOTS = {
    "tmp", "usr", "etc", "var", "proc", "dev", "bin", "sbin", "lib", "lib64", "opt",
    "root", "home", "sys", "run", "srv", "mnt", "tests", "logs", "agent-logs", "oracle",
}
FILE_EXTENSIONS = (
    "txt|json|csv|conf|py|cpp|hpp|cc|c|h|java|xml|jar|html|log|yaml|yml|md|sh|toml|ini|cfg|js|ts|go|rs|so"
)
FILENAME = re.compile(rf"(?<![\w.-])(?:[\w.-]+/)*([\w.-]*[\w-]\.(?:{FILE_EXTENSIONS}))(?![\w.-])")
ABSOLUTE_PATH_LITERAL = re.compile(r"""["'](/[\w.\-/]+)["']""")
FILE_ACCESS_LITERAL = re.compile(
    r"""(?:Path|open|exists|isfile|isdir|read_json|read_text|access)\(\s*["']([^"']+)["']"""
)
NETWORK_SETUP = re.compile(r"apt-get\s+install|apk\s+add|curl\s.*install\.sh|\buv\s+add|pip3?\s+install")
PYTEST_CALL = re.compile(r"\bpytest\b[^\n]*")
MIN_TEST_TIMEOUT_WITH_NETWORK_SETUP_SEC = 90
MIN_REPEATED_LINES = 3
MAX_UNUSED_INSTRUCTION_FILES = 2


@dataclass
class DockerfileFacts:
    workdir: str | None = None
    roots: set[str] = field(default_factory=set)
    copies: list[tuple[str, str]] = field(default_factory=list)
    run_text: str = ""


@dataclass
class TaskContext:
    task_dir: Path
    raw_yaml: dict
    spec: TaskSpec | None
    instruction: str
    dockerfile: DockerfileFacts
    run_tests: str
    tests: str
    solution: str | None
    other_files: dict[str, str]

    @property
    def task_file_names(self) -> set[str]:
        return {PurePosixPath(name).name for name in self.other_files}

    def corpus(self) -> str:
        """Everything except task.yaml: where an instruction's references should appear."""
        return "\n".join([self.run_tests, self.tests, self.solution or "", self.dockerfile.run_text,
                          *self.other_files.values(), *self.other_files])


def parse_dockerfile(text: str) -> DockerfileFacts:
    facts = DockerfileFacts()
    workdir = "/"
    for line in _logical_lines(text):
        instruction, _, args = line.partition(" ")
        instruction = instruction.upper()
        if instruction == "WORKDIR":
            workdir = _resolve(workdir, args.strip())
            facts.workdir = workdir
            facts.roots.add(_top_level(workdir))
        elif instruction in ("COPY", "ADD"):
            parts = [part for part in shlex.split(args) if not part.startswith("--")]
            if "--from" in args or len(parts) < 2:
                continue
            destination = _resolve(workdir, parts[-1])
            facts.roots.add(_top_level(destination))
            facts.copies.extend((source, destination) for source in parts[:-1])
        elif instruction == "RUN":
            facts.run_text += args + "\n"
            for created in re.findall(r"mkdir\s+(?:-\w+\s+)*([^&;|]+)", args):
                facts.roots.update(_top_level(path) for path in created.split() if path.startswith("/"))
    facts.roots.discard("")
    return facts


def _logical_lines(text: str) -> Iterator[str]:
    buffer = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        yield (buffer + line).strip()
        buffer = ""
    if buffer:
        yield buffer.strip()


def _resolve(workdir: str, path: str) -> str:
    return str(PurePosixPath(workdir) / path) if not path.startswith("/") else path


def _top_level(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[1] if len(parts) > 1 else ""


def load_context(task_dir: Path) -> tuple[TaskContext, list[Finding]]:
    findings: list[Finding] = []
    try:
        raw = yaml.safe_load((task_dir / "task.yaml").read_text()) or {}
    except (OSError, yaml.YAMLError):
        raw = {}
    try:
        spec = bundle.load_task_spec(task_dir)
    except bundle.InvalidTaskBundle as e:
        spec = None
        findings.append(_finding("task_schema", Severity.ERROR, str(e)))

    def read(name: str) -> str:
        path = task_dir / name
        return path.read_text(errors="replace") if path.is_file() else ""

    tests_dir = task_dir / "tests"
    tests = "\n".join(p.read_text(errors="replace") for p in sorted(tests_dir.rglob("*.py"))) if tests_dir.is_dir() else ""
    excluded = {"task.yaml", "Dockerfile", "run-tests.sh", "solution.sh", "docker-compose.yaml"}
    other_files = {
        str(path.relative_to(task_dir)): _read_text_or_empty(path)
        for path in sorted(task_dir.rglob("*"))
        if path.is_file() and path.name not in excluded and tests_dir not in path.parents
    }
    context = TaskContext(
        task_dir=task_dir,
        raw_yaml=raw if isinstance(raw, dict) else {},
        spec=spec,
        instruction=str((raw or {}).get("instruction", "")) if isinstance(raw, dict) else "",
        dockerfile=parse_dockerfile(read("Dockerfile")),
        run_tests=read("run-tests.sh"),
        tests=tests,
        solution=read("solution.sh") if (task_dir / "solution.sh").exists() else None,
        other_files=other_files,
    )
    return context, findings


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text()
    except (UnicodeDecodeError, OSError):
        return ""


def _finding(check: str, severity: Severity, message: str, **details) -> Finding:
    return Finding(check=check, stage=Stage.STATIC, severity=severity, message=message, details=details or None)


def check_duplicated_instruction(ctx: TaskContext) -> Iterator[Finding]:
    lines = [line.strip() for line in ctx.instruction.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        for j in range(i + 1, len(lines)):
            if lines[j] != line:
                continue
            run = 0
            while j + run < len(lines) and i + run < j and lines[i + run] == lines[j + run]:
                run += 1
            if run >= MIN_REPEATED_LINES:
                yield _finding(
                    "duplicated_instruction", Severity.WARNING,
                    f"instruction repeats a {run}-line block (starting {line[:60]!r}); "
                    "the agent sees the requirements twice and may treat them as conflicting",
                    repeated_lines=run,
                )
                return


def check_pytest_summary_flag(ctx: TaskContext) -> Iterator[Finding]:
    calls = PYTEST_CALL.findall(ctx.run_tests)
    if not calls:
        yield _finding("pytest_invocation", Severity.ERROR, "run-tests.sh never invokes pytest")
    elif not any(re.search(r"-r\w*A", call) for call in calls):
        yield _finding(
            "pytest_invocation", Severity.ERROR,
            "pytest is not run with -rA; terminal-bench's parser needs the PASSED/FAILED short summary",
        )


def check_tests_present(ctx: TaskContext) -> Iterator[Finding]:
    if not re.search(r"^\s*def test_\w+", ctx.tests, re.MULTILINE):
        yield _finding("tests_present", Severity.ERROR, "tests/ contains no pytest test functions")


def check_workdir(ctx: TaskContext) -> Iterator[Finding]:
    if ctx.dockerfile.workdir in (None, "/"):
        yield _finding(
            "workdir", Severity.ERROR,
            "Dockerfile sets no WORKDIR; the agent and tests start in / and run-tests.sh refuses to run there",
        )


def check_test_paths_inside_image(ctx: TaskContext) -> Iterator[Finding]:
    known_roots = ctx.dockerfile.roots | SYSTEM_ROOTS
    missing = sorted({
        path for path in ABSOLUTE_PATH_LITERAL.findall(ctx.tests)
        if _top_level(path) and _top_level(path) not in known_roots
    })
    if missing:
        yield _finding(
            "test_paths_outside_image", Severity.ERROR,
            f"tests read {', '.join(missing)} but the image never creates "
            f"{', '.join(sorted({'/' + _top_level(p) for p in missing}))} "
            f"(WORKDIR is {ctx.dockerfile.workdir or 'unset'})",
            paths=missing, workdir=ctx.dockerfile.workdir,
        )


def check_copy_renames_referenced_dir(ctx: TaskContext) -> Iterator[Finding]:
    corpus = "\n".join([ctx.tests, ctx.solution or "", *ctx.other_files.values()])
    for source, destination in ctx.dockerfile.copies:
        source_dir = ctx.task_dir / source
        source_name, destination_name = PurePosixPath(source).name, PurePosixPath(destination).name
        if not source_dir.is_dir() or source.endswith("/") or source_name in (".", destination_name):
            continue
        if re.search(rf"(?<![\w.-]){re.escape(source_name)}/", corpus):
            yield _finding(
                "copy_renames_directory", Severity.ERROR,
                f"Dockerfile copies {source}/ to {destination}, but task files refer to it as {source_name}/",
                source=source, destination=destination,
            )


def check_tested_files_in_instruction(ctx: TaskContext) -> Iterator[Finding]:
    """A file the tests read must either ship with the task or be named in the instruction."""
    unexplained = sorted({
        PurePosixPath(literal).name
        for literal in FILE_ACCESS_LITERAL.findall(ctx.tests)
        if FILENAME.fullmatch(PurePosixPath(literal).name)
        and PurePosixPath(literal).name not in ctx.task_file_names
        and PurePosixPath(literal).name not in ctx.instruction
        and PurePosixPath(literal).name not in ctx.run_tests
    })
    if unexplained:
        yield _finding(
            "tested_files_not_in_instruction", Severity.ERROR,
            f"tests check {', '.join(unexplained)}, which the instruction never asks for and the task does not provide",
            files=unexplained,
        )


def check_instruction_files_exist(ctx: TaskContext) -> Iterator[Finding]:
    """Files the instruction names should exist somewhere: shipped, built, produced, or tested."""
    corpus = ctx.corpus()
    named = sorted({match for match in FILENAME.findall(ctx.instruction)})
    unused = [name for name in named if name not in corpus]
    if len(unused) > MAX_UNUSED_INSTRUCTION_FILES:
        yield _finding(
            "instruction_describes_other_project", Severity.ERROR,
            f"instruction names {len(unused)} files that appear nowhere in the environment, tests, "
            f"or solution ({', '.join(unused[:8])}); it likely describes a different project",
            files=unused,
        )
    elif unused:
        yield _finding(
            "instruction_files_unused", Severity.WARNING,
            f"instruction names {', '.join(unused)}, which no test, solution, or task file references",
            files=unused,
        )


def check_test_timeout_budget(ctx: TaskContext) -> Iterator[Finding]:
    if ctx.spec and NETWORK_SETUP.search(ctx.run_tests) and ctx.spec.max_test_timeout_sec < MIN_TEST_TIMEOUT_WITH_NETWORK_SETUP_SEC:
        yield _finding(
            "test_timeout_budget", Severity.WARNING,
            f"run-tests.sh installs packages over the network but max_test_timeout_sec is "
            f"{ctx.spec.max_test_timeout_sec:.0f}s; setup alone can exceed that under load",
            max_test_timeout_sec=ctx.spec.max_test_timeout_sec,
        )


def check_solution_present(ctx: TaskContext) -> Iterator[Finding]:
    if ctx.solution is None:
        yield _finding("solution_present", Severity.WARNING, "no solution.sh; the oracle check cannot run")


CHECKS: list[Callable[[TaskContext], Iterator[Finding]]] = [
    check_duplicated_instruction,
    check_pytest_summary_flag,
    check_tests_present,
    check_workdir,
    check_test_paths_inside_image,
    check_copy_renames_referenced_dir,
    check_tested_files_in_instruction,
    check_instruction_files_exist,
    check_test_timeout_budget,
    check_solution_present,
]


def run_static_checks(task_dir: Path) -> tuple[TaskContext, list[Finding]]:
    context, findings = load_context(task_dir)
    for check in CHECKS:
        findings.extend(check(context))
    return context, findings
