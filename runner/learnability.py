"""Learnability classification under the 10-run rule, with early stopping.

A task is learnable if 2-7 of 10 runs fully pass. Out of 10 runs, the class is
already fixed once passes >= 8 (too easy), failures >= 9 (too hard), or passes >= 2
and failures >= 3 (learnable): no outcome of the remaining runs can change it.
Stopping exactly then (confidence 1.0) always gives the 10-run answer.

With confidence < 1.0, the runner also stops once the posterior predictive
probability of one class (uniform Beta prior on the per-run pass rate) reaches the
threshold, trading a bounded misclassification rate for fewer runs.
"""

import math
from enum import StrEnum

TARGET_RUNS = 10
MIN_LEARNABLE_PASSES = 2
MAX_LEARNABLE_PASSES = 7

TOO_EASY_PASSES = MAX_LEARNABLE_PASSES + 1
TOO_HARD_FAILURES = TARGET_RUNS - MIN_LEARNABLE_PASSES + 1
LEARNABLE_FAILURES = TARGET_RUNS - MAX_LEARNABLE_PASSES


class Classification(StrEnum):
    LEARNABLE = "learnable"
    TOO_EASY = "too_easy"
    TOO_HARD = "too_hard"
    UNDETERMINED = "undetermined"


def ten_run_class(passes: int) -> Classification:
    if passes >= TOO_EASY_PASSES:
        return Classification.TOO_EASY
    if passes < MIN_LEARNABLE_PASSES:
        return Classification.TOO_HARD
    return Classification.LEARNABLE


def classify(passes: int, failures: int) -> Classification:
    """The 10-run class implied by the runs so far, or UNDETERMINED if still open."""
    if passes >= TOO_EASY_PASSES:
        return Classification.TOO_EASY
    if failures >= TOO_HARD_FAILURES:
        return Classification.TOO_HARD
    if passes >= MIN_LEARNABLE_PASSES and failures >= LEARNABLE_FAILURES:
        return Classification.LEARNABLE
    return Classification.UNDETERMINED


def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def class_probabilities(passes: int, failures: int) -> dict[Classification, float]:
    """Posterior predictive probability of each 10-run class given the runs so far."""
    remaining = TARGET_RUNS - passes - failures
    probabilities = dict.fromkeys(
        (Classification.LEARNABLE, Classification.TOO_EASY, Classification.TOO_HARD), 0.0
    )
    for extra in range(remaining + 1):
        log_pmf = (
            math.log(math.comb(remaining, extra))
            + _log_beta(extra + 1 + passes, remaining - extra + 1 + failures)
            - _log_beta(1 + passes, 1 + failures)
        )
        probabilities[ten_run_class(passes + extra)] += math.exp(log_pmf)
    return probabilities


def decide(passes: int, failures: int, confidence: float = 1.0) -> Classification:
    exact = classify(passes, failures)
    if exact != Classification.UNDETERMINED or confidence >= 1.0:
        return exact
    likeliest, probability = max(class_probabilities(passes, failures).items(), key=lambda item: item[1])
    return likeliest if probability >= confidence else Classification.UNDETERMINED


def runs_until_decidable(passes: int, failures: int, confidence: float = 1.0) -> int:
    """Fewest further runs after which a decision could be reached (0 if decided).

    Launching exactly this many in parallel never wastes a run: a one-at-a-time
    strategy that stops as soon as it can would run all of them too.
    """
    if decide(passes, failures, confidence) != Classification.UNDETERMINED:
        return 0
    exact_bound = min(
        TOO_EASY_PASSES - passes,
        TOO_HARD_FAILURES - failures,
        max(0, MIN_LEARNABLE_PASSES - passes) + max(0, LEARNABLE_FAILURES - failures),
    )
    if confidence >= 1.0:
        return exact_bound
    for runs in range(1, exact_bound):
        if any(
            decide(passes + extra, failures + runs - extra, confidence) != Classification.UNDETERMINED
            for extra in range(runs + 1)
        ):
            return runs
    return exact_bound


def next_wave_size(
    passes: int, failures: int, launched: int, max_launches: int, max_wave: int, confidence: float = 1.0
) -> int:
    """How many attempts to launch next; 0 means stop.

    Attempts that errored (no test results) count toward `launched` but not toward
    passes/failures, so they are replaced until the launch budget runs out.
    """
    needed = runs_until_decidable(passes, failures, confidence)
    return max(0, min(needed, max_launches - launched, max_wave))


def replay(
    outcomes: list[bool], max_wave: int = TARGET_RUNS, confidence: float = 1.0
) -> tuple[Classification, int, int]:
    """Run the adaptive policy against a fixed sequence of run outcomes.

    Returns (classification, runs used, waves used); used by tests and the cost study.
    """
    passes = failures = used = waves = 0
    while size := next_wave_size(passes, failures, used, TARGET_RUNS, max_wave, confidence):
        wave = outcomes[used : used + size]
        passes += sum(wave)
        failures += len(wave) - sum(wave)
        used += size
        waves += 1
    return decide(passes, failures, confidence), used, waves
