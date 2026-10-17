import math

Z_95 = 1.959964

# A task is a "learnable data point" when 2-7 of 10 SOTA runs pass, i.e. a true pass
# rate of roughly 20-70%.
LEARNABLE_RANGE = (0.2, 0.7)


def wilson_interval(successes: int, trials: int, z: float = Z_95) -> tuple[float, float]:
    if trials == 0:
        return 0.0, 1.0
    p = successes / trials
    denominator = 1 + z**2 / trials
    centre = (p + z**2 / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2)) / denominator
    return round(max(0.0, centre - margin), 3), round(min(1.0, centre + margin), 3)


def learnability_verdict(successes: int, trials: int) -> dict:
    """Exact rule at n=10; otherwise only commit to a verdict the 95% interval supports."""
    low, high = wilson_interval(successes, trials)
    if trials == 10:
        learnable = 2 <= successes <= 7
        verdict = "learnable" if learnable else ("too_easy" if successes > 7 else "too_hard")
        basis = f"{successes}/10 runs passed (rule: 2-7 of 10)"
    elif LEARNABLE_RANGE[0] <= low and high <= LEARNABLE_RANGE[1]:
        verdict, basis = "likely_learnable", "95% interval lies inside 20-70%"
    elif low > LEARNABLE_RANGE[1]:
        verdict, basis = "likely_too_easy", "95% interval lies above 70%"
    elif high < LEARNABLE_RANGE[0]:
        verdict, basis = "likely_too_hard", "95% interval lies below 20%"
    else:
        verdict = "insufficient_evidence"
        basis = f"95% interval {low:.0%}-{high:.0%} overlaps the 20-70% boundary; more runs needed"
    return {
        "verdict": verdict,
        "basis": basis,
        "pass_rate": round(successes / trials, 3) if trials else None,
        "interval_95": [low, high],
        "n": trials,
    }
