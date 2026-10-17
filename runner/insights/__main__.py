"""Regenerate and re-verify insights for a submission directory.

Usage: python -m runner.insights <submission_dir> [--no-narrative]
The narrative uses the model from AQ_INSIGHTS_MODEL (see runner/config.py).
Exits non-zero if any finding was withheld because its evidence failed verification.
"""

import sys
from pathlib import Path

from runner.config import Settings
from runner.insights import generate


def main() -> int:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        return 2
    model = None if "--no-narrative" in sys.argv else Settings.from_env().insights_model
    report = generate(Path(args[0]), narrative_model=model)
    evidence = report["evidence"].values()
    verified = sum(1 for e in evidence if e["verified"])
    print(
        f"{report['task_id']}: {len(report['insights'])} findings, "
        f"{len(report['rejected_insights'])} withheld, {verified}/{len(evidence)} evidence items verified"
    )
    return 1 if report["rejected_insights"] else 0


if __name__ == "__main__":
    sys.exit(main())
