import itertools

import pytest

from runner.learnability import (
    TARGET_RUNS,
    Classification,
    classify,
    next_wave_size,
    replay,
    runs_until_decidable,
)

ALL_SEQUENCES = [list(bits) for bits in itertools.product([False, True], repeat=TARGET_RUNS)]


def ten_run_class(outcomes: list[bool]) -> Classification:
    passes = sum(outcomes)
    if passes >= 8:
        return Classification.TOO_EASY
    if passes <= 1:
        return Classification.TOO_HARD
    return Classification.LEARNABLE


@pytest.mark.parametrize(
    "passes, failures, expected",
    [
        (0, 0, Classification.UNDETERMINED),
        (8, 0, Classification.TOO_EASY),
        (7, 2, Classification.UNDETERMINED),
        (7, 3, Classification.LEARNABLE),
        (2, 3, Classification.LEARNABLE),
        (1, 8, Classification.UNDETERMINED),
        (1, 9, Classification.TOO_HARD),
        (0, 9, Classification.TOO_HARD),
        (2, 2, Classification.UNDETERMINED),
    ],
)
def test_classify_boundaries(passes, failures, expected):
    assert classify(passes, failures) == expected


def test_full_ten_runs_always_decided():
    for passes in range(TARGET_RUNS + 1):
        assert classify(passes, TARGET_RUNS - passes) != Classification.UNDETERMINED


@pytest.mark.parametrize("max_wave", range(1, TARGET_RUNS + 1))
def test_early_stopping_matches_ten_run_rule_for_every_sequence(max_wave):
    for outcomes in ALL_SEQUENCES:
        classification, used, _ = replay(outcomes, max_wave)
        assert classification == ten_run_class(outcomes)
        assert used <= TARGET_RUNS


def test_parallel_waves_cost_the_same_as_one_at_a_time():
    for outcomes in ALL_SEQUENCES:
        _, sequential_runs, _ = replay(outcomes, max_wave=1)
        _, parallel_runs, _ = replay(outcomes, max_wave=TARGET_RUNS)
        assert parallel_runs == sequential_runs


def test_sequential_policy_stops_at_first_decidable_prefix():
    for outcomes in ALL_SEQUENCES:
        _, used, _ = replay(outcomes, max_wave=1)
        prefix = outcomes[:used]
        assert classify(sum(prefix), len(prefix) - sum(prefix)) != Classification.UNDETERMINED
        shorter = outcomes[: used - 1]
        assert classify(sum(shorter), len(shorter) - sum(shorter)) == Classification.UNDETERMINED


def test_first_wave_is_five_runs():
    assert runs_until_decidable(0, 0) == 5
    assert next_wave_size(0, 0, launched=0, max_launches=10, max_wave=10) == 5


def test_wave_size_respects_cap_and_budget():
    assert next_wave_size(0, 0, launched=0, max_launches=10, max_wave=3) == 3
    assert next_wave_size(1, 1, launched=9, max_launches=10, max_wave=10) == 1
    assert next_wave_size(1, 1, launched=10, max_launches=10, max_wave=10) == 0


def test_errored_attempts_are_replaced_until_budget():
    assert next_wave_size(0, 0, launched=5, max_launches=13, max_wave=10) == 5
    assert next_wave_size(8, 0, launched=8, max_launches=13, max_wave=10) == 0
