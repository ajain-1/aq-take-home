"""Validate every task under a directory and write the reports.

Usage: python scripts/validation_report.py <tasks-dir> <out-dir> [--mode full|static] [--force]

Tasks are validated one at a time (each full validation runs three Job pods).
Writes <out-dir>/<task>.json per task and <out-dir>/SUMMARY.md.
"""

import argparse
import io
import json
import os
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

API_URL = os.environ.get("API_URL", "http://localhost:8000")
POLL_SEC = 5


def zip_task(task_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(task_dir.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store":
                info = zipfile.ZipInfo.from_file(path, str(path.relative_to(task_dir.parent)))
                archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


def post_validation(archive: bytes, filename: str, mode: str, force: bool) -> dict:
    boundary = uuid.uuid4().hex
    fields = {"mode": mode, "force": str(force).lower()}
    body = b"".join(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        for k, v in fields.items()
    )
    body += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        "Content-Type: application/zip\r\n\r\n"
    ).encode() + archive + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{API_URL}/validate", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def wait_for(validation_id: str) -> dict:
    while True:
        with urllib.request.urlopen(f"{API_URL}/validations/{validation_id}") as response:
            report = json.load(response)
        if report["status"] in ("completed", "failed"):
            return report
        time.sleep(POLL_SEC)


def summarize(reports: dict[str, dict]) -> str:
    lines = ["| Task | Verdict | Stages run | Errors | Warnings | Findings |", "|---|---|---|---|---|---|"]
    for task, report in reports.items():
        findings = "<br>".join(
            f"**{f['severity']}** `{f['stage']}/{f['check']}`: {f['message']}" for f in report["findings"]
        ) or "—"
        verdict = "PASS" if report["passed"] else "FAIL"
        counts = report["counts"]
        lines.append(
            f"| {task} | {verdict} | {', '.join(report['stages_run'])} | {counts['error']} | {counts['warning']} | {findings} |"
        )
    return "\n".join(lines) + "\n"


def rewrite_summary(out_dir: Path) -> None:
    reports = {path.stem: json.loads(path.read_text()) for path in sorted(out_dir.glob("*.json"))}
    (out_dir / "SUMMARY.md").write_text(summarize(reports))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--mode", default="full", choices=["full", "static"])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    reports = {}
    for task_dir in sorted(p for p in args.tasks_dir.iterdir() if (p / "task.yaml").exists()):
        print(f"validating {task_dir.name} ...", flush=True)
        report = post_validation(zip_task(task_dir), f"{task_dir.name}.zip", args.mode, args.force)
        if report["status"] not in ("completed", "failed"):
            report = wait_for(report["validation_id"])
        reports[task_dir.name] = report
        (args.out_dir / f"{task_dir.name}.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"  {'PASS' if report['passed'] else 'FAIL'} {report['counts']}", flush=True)

    (args.out_dir / "SUMMARY.md").write_text(summarize(reports))


if __name__ == "__main__":
    main()
