"""Regenerates the tiny fixture tasks used by the live robustness scenarios."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
OK_TEST = 'def test_output_written():\n    assert Path("/app/out.txt").read_text().strip() == "ok"'
OOM_TEST = (
    "def test_allocation_was_oom_killed():\n"
    '    assert Path("/app/alloc_exit.txt").read_text().strip() == "137"'
)

# name: (agent timeout, test timeout, solution, test, extra Dockerfile lines)
FIXTURES = {
    "rb-ok": (60, 60, "echo ok > /app/out.txt", OK_TEST, ""),
    "rb-slow": (180, 60, "sleep 45\necho ok > /app/out.txt", OK_TEST, ""),
    "rb-agent-timeout": (10, 60, "sleep 40", OK_TEST, ""),
    "rb-hang": (10, 10, "sleep 100000", OK_TEST, ""),
    "rb-oom": (60, 60, 'python3 -c "bytearray(3 * 1024**3)"\necho $? > /app/alloc_exit.txt', OOM_TEST, ""),
    "rb-build-fail": (60, 60, "true", OK_TEST, 'RUN echo "intentional build failure" && exit 3\n'),
    "rb-build-slow": (60, 60, "true", OK_TEST, "RUN sleep 120\n"),
    "rb-build-sleep": (60, 60, "echo ok > /app/out.txt", OK_TEST, "RUN echo rb-build-sleep && sleep 25\n"),
}


def main() -> None:
    for name, (agent_timeout, test_timeout, solution, test, extra) in FIXTURES.items():
        task_dir = ROOT / name
        (task_dir / "tests").mkdir(parents=True, exist_ok=True)
        (task_dir / "task.yaml").write_text(
            f"instruction: Robustness fixture {name}; write ok to /app/out.txt.\n"
            f"difficulty: easy\nmax_agent_timeout_sec: {agent_timeout}\n"
            f"max_test_timeout_sec: {test_timeout}\nresource_class: small\n"
        )
        (task_dir / "Dockerfile").write_text(
            f"FROM python:3.12-slim\nRUN pip install --no-cache-dir pytest==8.3.3\nWORKDIR /app\n{extra}"
        )
        (task_dir / "run-tests.sh").write_text(
            "#!/bin/bash\npython -m pytest $TEST_DIR/test_outputs.py -rA\n"
        )
        (task_dir / "solution.sh").write_text(f"#!/bin/bash\n{solution}\n")
        (task_dir / "tests" / "test_outputs.py").write_text(f"from pathlib import Path\n\n\n{test}\n")
        for script in ("run-tests.sh", "solution.sh"):
            (task_dir / script).chmod(0o755)


if __name__ == "__main__":
    main()
