"""Exact cost/latency study of the adaptive strategy versus always running 10 attempts.

Every one of the 2^10 outcome sequences is replayed, so expectations are exact (no
sampling) for each per-run pass probability p, and classifications are checked
against the 10-run rule for every sequence.

Usage: python scripts/simulate_cost.py [results.json ...] > results/cost-optimization/simulation.md
Passing result files from real runs adds a dollar projection from measured tokens.
"""

import itertools
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner.config import Settings  # noqa: E402
from runner.learnability import TARGET_RUNS, Classification, classify, replay, ten_run_class  # noqa: E402

settings = Settings.from_env()
SEQUENCES = [list(bits) for bits in itertools.product([False, True], repeat=TARGET_RUNS)]
P_GRID = [round(i / 20, 2) for i in range(21)]
WAVE_CAPS = (1, 3, 5, 10)
CONFIDENCES = (1.0, 0.99, 0.95, 0.9)


@dataclass
class Outcome:
    runs: int
    waves: int
    correct: bool


def fixed_batches(outcomes: list[bool], batch: int) -> Outcome:
    """Non-adaptive baseline: launch `batch` at a time until the exact rule decides."""
    used = waves = 0
    while classify(sum(outcomes[:used]), used - sum(outcomes[:used])) == Classification.UNDETERMINED:
        used, waves = min(TARGET_RUNS, used + batch), waves + 1
    return Outcome(used, waves, True)


def adaptive(outcomes: list[bool], cap: int, confidence: float) -> Outcome:
    classification, runs, waves = replay(outcomes, cap, confidence)
    return Outcome(runs, waves, classification == ten_run_class(sum(outcomes)))


POLICIES = {
    **{f"exact w{cap}": (lambda o, cap=cap: adaptive(o, cap, 1.0)) for cap in WAVE_CAPS},
    **{f"conf {c}": (lambda o, c=c: adaptive(o, TARGET_RUNS, c)) for c in CONFIDENCES[1:]},
    "batches of 5": lambda o: fixed_batches(o, 5),
}
OUTCOMES = {name: [policy(seq) for seq in SEQUENCES] for name, policy in POLICIES.items()}


def expectation(name: str, p: float, field: str) -> float:
    total = 0.0
    for seq, outcome in zip(SEQUENCES, OUTCOMES[name]):
        weight = p ** sum(seq) * (1 - p) ** (TARGET_RUNS - sum(seq))
        total += weight * (getattr(outcome, field) if field != "error" else (not outcome.correct))
    return total


def measured_attempt_cost(result_files: list[Path]) -> tuple[int, float] | None:
    costs = []
    for path in result_files:
        for attempt in json.loads(path.read_text()).get("attempts", []):
            if attempt.get("input_tokens") is not None:
                costs.append(
                    attempt["input_tokens"] / 1e6 * settings.price_input_per_mtok
                    + (attempt.get("output_tokens") or 0) / 1e6 * settings.price_output_per_mtok
                )
    return (len(costs), sum(costs) / len(costs)) if costs else None


def table(header: list[str], rows: list[list[str]]) -> None:
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for row in rows:
        print("| " + " | ".join(row) + " |")
    print()


def uniform_mean(name: str, field: str) -> float:
    return sum(expectation(name, p, field) for p in P_GRID) / len(P_GRID)


def main() -> None:
    exact_errors = sum(not o.correct for name in OUTCOMES if name.startswith("exact") for o in OUTCOMES[name])
    print("# Adaptive attempts vs. always-10\n")
    print("All expectations are exact: every one of the 1024 outcome sequences of 10 runs is replayed and")
    print("weighted by p^passes (1-p)^failures. Latency is in waves (one wave = one attempt's wall time);")
    print("always-10 is 10 attempts in 1 wave.\n")
    print(f"**Exactness:** the exact policy (confidence 1.0) misclassified {exact_errors} of "
          f"{len(SEQUENCES) * len(WAVE_CAPS)} (sequence, wave cap) cases versus the 10-run rule.\n")

    print("## Exact policy: cost and latency by wave cap\n")
    print("Expected attempts are identical for every wave cap (parallel waves never launch an attempt a")
    print("one-at-a-time policy would skip); only latency changes.\n")
    table(
        ["p", "attempts", "saved vs 10", *[f"waves (cap {cap})" for cap in WAVE_CAPS],
         "batches-of-5 attempts", "batches-of-5 waves"],
        [
            [f"{p:.2f}", f"{expectation('exact w10', p, 'runs'):.2f}",
             f"{1 - expectation('exact w10', p, 'runs') / TARGET_RUNS:.0%}",
             *[f"{expectation(f'exact w{cap}', p, 'waves'):.2f}" for cap in WAVE_CAPS],
             f"{expectation('batches of 5', p, 'runs'):.2f}", f"{expectation('batches of 5', p, 'waves'):.2f}"]
            for p in P_GRID
        ],
    )

    print("## Confidence-based stopping: cost vs. misclassification\n")
    print("Stops once the posterior predictive probability of one class (uniform prior on p) reaches the")
    print("threshold. Error = probability the label differs from what all 10 runs would have given.\n")
    names = ["exact w10", *[f"conf {c}" for c in CONFIDENCES[1:]]]
    table(
        ["p", *[f"{n} attempts" for n in names], *[f"{n} error" for n in names[1:]]],
        [
            [f"{p:.2f}", *[f"{expectation(n, p, 'runs'):.2f}" for n in names],
             *[f"{expectation(n, p, 'error'):.3f}" for n in names[1:]]]
            for p in P_GRID
        ],
    )

    print("## Summary (p uniform on [0, 1])\n")
    summary_rows = []
    for name in ["exact w10", *[f"conf {c}" for c in CONFIDENCES[1:]], "batches of 5"]:
        runs = uniform_mean(name, "runs")
        summary_rows.append([name, f"{runs:.2f}", f"{1 - runs / TARGET_RUNS:.0%}",
                             f"{uniform_mean(name, 'waves'):.2f}", f"{uniform_mean(name, 'error'):.3f}"])
    table(["policy", "attempts", "saved vs 10", "waves", "error rate"], summary_rows)

    if measured := measured_attempt_cost([Path(f) for f in sys.argv[1:]]):
        n, per_attempt = measured
        print(f"Measured from {n} real terminus-1 attempts: ${per_attempt:.3f} per attempt at "
              f"${settings.price_input_per_mtok:g}/${settings.price_output_per_mtok:g} per Mtok in/out "
              f"(tokenizer estimates, no caching discount). Always-10 = ${10 * per_attempt:.2f} per task.\n")
        for name, runs in [(row[0], float(row[1])) for row in summary_rows]:
            print(f"- {name}: ${runs * per_attempt:.2f} per task")


if __name__ == "__main__":
    main()
