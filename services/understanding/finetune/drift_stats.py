"""A real statistical test for detecting accuracy drift between two eval runs — the actual
computation behind ADR-007's "watch the SCIENTIFIC_DISAGREEMENT rate" revisit trigger and the
equivalent question for understanding(): is current accuracy actually different from baseline, or
does it just look different by chance at this sample size?

Two-proportion z-test, not Fisher's exact: chosen for being exactly, simply implementable with no
new dependency (Fisher's exact two-tailed p-value requires enumerating contingency tables to get
right, not just "double one side" — a real correctness risk to hand-roll without a validated
library). Honest limitation, not hidden: the z-test's normal approximation is weaker at small n or
when a proportion sits near 0 or 1 — exactly this project's regime (n=25, current baseline 92%).
Treat a result near the significance boundary as a prompt to gather more data, not a verdict.

Real, separate risk this module does NOT solve, and shouldn't be assumed away: running this test
repeatedly (every day, every new batch) inflates the true false-positive rate well past the
nominal alpha — the classic "peeking" problem. This is one check's math, not a monitoring
schedule; the caller (check_drift.py) is responsible for running it infrequently (e.g. weekly),
not continuously.
"""

import math


def two_proportion_z_test(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    """Tests whether p2 = k2/n2 differs significantly from p1 = k1/n1 (two-tailed).

    Returns (z_statistic, p_value). A pooled proportion under the null hypothesis that both
    samples share one true rate — standard for comparing two independent proportions.
    """
    if n1 <= 0 or n2 <= 0:
        raise ValueError("both sample sizes must be positive")
    if not (0 <= k1 <= n1) or not (0 <= k2 <= n2):
        raise ValueError("k must be between 0 and n")

    p1 = k1 / n1
    p2 = k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)

    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        # Both proportions identical and at 0 or 1 — no variance, no evidence of a difference.
        return 0.0, 1.0

    z = (p2 - p1) / se
    p_value = 2 * (1 - _standard_normal_cdf(abs(z)))
    return z, p_value


def _standard_normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def detect_drift(baseline_correct: int, baseline_n: int, current_correct: int, current_n: int, alpha: float = 0.05) -> dict:
    """The actual decision a scheduled check makes: is current accuracy significantly different
    from baseline at the given significance level? Returns enough detail to log and act on, not
    just a boolean — a real drift-monitoring result needs the numbers behind the verdict, not
    just the verdict."""
    z, p_value = two_proportion_z_test(baseline_correct, baseline_n, current_correct, current_n)
    baseline_rate = baseline_correct / baseline_n
    current_rate = current_correct / current_n
    return {
        "baseline_accuracy": baseline_rate,
        "current_accuracy": current_rate,
        "delta": current_rate - baseline_rate,
        "z_statistic": z,
        "p_value": p_value,
        "alpha": alpha,
        "drift_detected": p_value < alpha,
    }
