"""Learnability classification under the 10-run rule, with exact early stopping.

A task is learnable if 2-7 of 10 runs fully pass. Out of 10 runs, the class is
already fixed once passes >= 8 (too easy), failures >= 9 (too hard), or passes >= 2
and failures >= 3 (learnable): no outcome of the remaining runs can change it. The
adaptive strategy stops exactly then, so its answer always equals the 10-run answer.
"""

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


def classify(passes: int, failures: int) -> Classification:
    """The 10-run class implied by the runs so far, or UNDETERMINED if still open."""
    if passes >= TOO_EASY_PASSES:
        return Classification.TOO_EASY
    if failures >= TOO_HARD_FAILURES:
        return Classification.TOO_HARD
    if passes >= MIN_LEARNABLE_PASSES and failures >= LEARNABLE_FAILURES:
        return Classification.LEARNABLE
    return Classification.UNDETERMINED


def runs_until_decidable(passes: int, failures: int) -> int:
    """Fewest further runs after which the class could be decided (0 if already decided).

    Launching exactly this many in parallel never wastes a run: a one-at-a-time
    strategy that stops as soon as it can would run all of them too.
    """
    if classify(passes, failures) != Classification.UNDETERMINED:
        return 0
    return min(
        TOO_EASY_PASSES - passes,
        TOO_HARD_FAILURES - failures,
        max(0, MIN_LEARNABLE_PASSES - passes) + max(0, LEARNABLE_FAILURES - failures),
    )


def next_wave_size(passes: int, failures: int, launched: int, max_launches: int, max_wave: int) -> int:
    """How many attempts to launch next; 0 means stop.

    Attempts that errored (no test results) count toward `launched` but not toward
    passes/failures, so they are replaced until the launch budget runs out.
    """
    return max(0, min(runs_until_decidable(passes, failures), max_launches - launched, max_wave))


def replay(outcomes: list[bool], max_wave: int = TARGET_RUNS) -> tuple[Classification, int, int]:
    """Run the adaptive policy against a fixed sequence of run outcomes.

    Returns (classification, runs used, waves used); used by tests and the cost study.
    """
    passes = failures = used = waves = 0
    while size := next_wave_size(passes, failures, used, TARGET_RUNS, max_wave):
        wave = outcomes[used : used + size]
        passes += sum(wave)
        failures += len(wave) - sum(wave)
        used += size
        waves += 1
    return classify(passes, failures), used, waves
