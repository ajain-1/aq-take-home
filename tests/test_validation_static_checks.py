"""Run with `python -m pytest tests` from the repo root."""

import textwrap
from pathlib import Path

import pytest
import yaml

from runner.validation.static_checks import parse_dockerfile, run_static_checks

RUN_TESTS = """\
apt-get update && apt-get install -y curl
curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh
uv add pytest==8.4.1
uv run pytest $TEST_DIR/test_outputs.py -rA
"""

DEFAULT_TESTS = """\
from pathlib import Path

def test_result():
    assert Path("/app/result.txt").is_file()
"""


def make_task(
    root: Path,
    *,
    instruction: str = "Create /app/result.txt containing the answer.",
    dockerfile: str = "FROM ubuntu:24.04\nWORKDIR /app\n",
    tests: str = DEFAULT_TESTS,
    run_tests: str = RUN_TESTS,
    solution: str | None = "echo 42 > /app/result.txt\n",
    files: dict[str, str] | None = None,
    **task_fields,
) -> Path:
    task_dir = root / "sample-task"
    (task_dir / "tests").mkdir(parents=True)
    fields = {
        "instruction": instruction,
        "max_test_timeout_sec": 120,
        "resource_class": "small",
        **task_fields,
    }
    (task_dir / "task.yaml").write_text(yaml.safe_dump(fields))
    (task_dir / "Dockerfile").write_text(dockerfile)
    (task_dir / "run-tests.sh").write_text(run_tests)
    (task_dir / "tests" / "test_outputs.py").write_text(tests)
    if solution is not None:
        (task_dir / "solution.sh").write_text(solution)
    for name, content in (files or {}).items():
        (task_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (task_dir / name).write_text(content)
    return task_dir


def checks(task_dir: Path) -> dict[str, str]:
    _, findings = run_static_checks(task_dir)
    return {finding.check: finding.severity for finding in findings}


def test_well_formed_task_has_no_findings(tmp_path):
    assert checks(make_task(tmp_path)) == {}


def test_duplicated_instruction(tmp_path):
    block = "Fix the parser.\nKeep the CLI stable.\nWrite tests.\n"
    assert checks(make_task(tmp_path, instruction=block + block))["duplicated_instruction"] == "warning"


def test_tests_reading_outside_workdir(tmp_path):
    task = make_task(
        tmp_path,
        dockerfile="FROM ubuntu:24.04\nWORKDIR /workspace\nCOPY app.py ./\n",
        files={"app.py": ""},
        instruction="Fix app.py so it starts.",
        tests='def test_app():\n    assert open("/app/app.py")\n',
    )
    assert checks(task)["test_paths_outside_image"] == "error"


def test_copy_that_renames_a_referenced_directory(tmp_path):
    task = make_task(
        tmp_path,
        dockerfile="FROM ubuntu:24.04\nWORKDIR /app\nCOPY libs /app/lib\n",
        files={"libs/math/math.cpp": "", "CMakeLists.txt": "add_subdirectory(libs/math)\n"},
    )
    assert checks(task)["copy_renames_directory"] == "error"


def test_tested_file_missing_from_instruction(tmp_path):
    task = make_task(
        tmp_path,
        instruction="Create manifest.txt in /app.",
        tests='from pathlib import Path\n\ndef test_file():\n    assert Path("/app/hello.txt").exists()\n',
    )
    found = checks(task)
    assert found["tested_files_not_in_instruction"] == "error"
    assert found["instruction_files_unused"] == "warning"


def test_instruction_describing_another_project(tmp_path):
    instruction = "Fix pom.xml, libs/math/pom.xml, src/Main.java, and produce target/app.jar."
    assert (
        checks(make_task(tmp_path, instruction=instruction))["instruction_describes_other_project"] == "error"
    )


def test_pytest_without_short_summary(tmp_path):
    task = make_task(tmp_path, run_tests="uv run pytest $TEST_DIR/test_outputs.py\n")
    assert checks(task)["pytest_invocation"] == "error"


def test_missing_workdir(tmp_path):
    assert checks(make_task(tmp_path, dockerfile="FROM ubuntu:24.04\n"))["workdir"] == "error"


def test_no_test_functions(tmp_path):
    assert checks(make_task(tmp_path, tests="import os\n"))["tests_present"] == "error"


def test_tight_test_timeout_with_network_setup(tmp_path):
    assert checks(make_task(tmp_path, max_test_timeout_sec=60))["test_timeout_budget"] == "warning"


def test_missing_solution(tmp_path):
    assert checks(make_task(tmp_path, solution=None))["solution_present"] == "warning"


def test_invalid_task_yaml(tmp_path):
    assert checks(make_task(tmp_path, resource_class="gigantic"))["task_schema"] == "error"


@pytest.mark.parametrize(
    "dockerfile, workdir, roots",
    [
        ("FROM x\nWORKDIR /app\nCOPY a.py ./\n", "/app", {"app"}),
        ("FROM x\nCOPY --from=build /out /srv/out\nWORKDIR /data\n", "/data", {"data"}),
        (
            "FROM x\nRUN mkdir -p /var/log/samples /etc/conf \\\n    && echo hi\nWORKDIR /w\n",
            "/w",
            {"var", "etc", "w"},
        ),
    ],
)
def test_parse_dockerfile(dockerfile, workdir, roots):
    facts = parse_dockerfile(textwrap.dedent(dockerfile))
    assert facts.workdir == workdir
    assert facts.roots == roots
