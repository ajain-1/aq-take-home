import math

from runner.learnability import Classification, decide

Z_95 = 1.959964

def wilson_interval(successes: int, trials: int, z: float = Z_95) -> tuple[float, float]:
    if trials == 0:
        return 0.0, 1.0
    p = successes / trials
    denominator = 1 + z**2 / trials
    centre = (p + z**2 / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2)) / denominator
    return round(max(0.0, centre - margin), 3), round(min(1.0, centre + margin), 3)


def learnability_verdict(passes: int, failures: int, errored: int = 0) -> dict:
    """The 10-run learnability class from runner.learnability (the same rule the adaptive
    strategy stops on), with the Wilson interval as descriptive context only."""
    classification = decide(passes, failures)
    trials = passes + failures
    low, high = wilson_interval(passes, trials)
    if classification == Classification.UNDETERMINED:
        basis = (
            f"{passes} passing / {failures} failing runs; the 10-run rule (2-7 of 10 pass) "
            "is not yet decided"
        )
    else:
        basis = f"{passes} passing / {failures} failing runs decide the 10-run rule (2-7 of 10 pass)"
    if errored:
        basis += f"; {errored} errored attempt(s) excluded"
    return {
        "verdict": classification.value,
        "basis": basis,
        "pass_rate": round(passes / trials, 3) if trials else None,
        "interval_95": [low, high],
        "n": trials,
    }
