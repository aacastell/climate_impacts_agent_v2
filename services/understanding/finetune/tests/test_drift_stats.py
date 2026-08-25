import math

from drift_stats import detect_drift, two_proportion_z_test


def test_identical_proportions_give_zero_z_and_p_one():
    z, p = two_proportion_z_test(20, 25, 20, 25)
    assert z == 0.0
    assert p == 1.0


def test_both_samples_perfect_gives_no_evidence_of_difference():
    # se == 0 branch — both proportions at 1.0, no variance to test against.
    z, p = two_proportion_z_test(25, 25, 25, 25)
    assert z == 0.0
    assert p == 1.0


def test_dramatic_drop_is_detected_as_significant():
    z, p = two_proportion_z_test(25, 25, 5, 25)  # baseline 100% -> current 20%
    assert p < 0.001
    assert z < 0  # current lower than baseline -> negative z, see the sign-convention test below


def test_z_sign_convention_is_current_minus_baseline():
    z_drop, _ = two_proportion_z_test(k1=20, n1=25, k2=10, n2=25)  # current lower than baseline
    z_rise, _ = two_proportion_z_test(k1=10, n1=25, k2=20, n2=25)  # current higher than baseline
    assert z_drop < 0
    assert z_rise > 0


def test_swapping_baseline_and_current_flips_z_but_not_p():
    z1, p1 = two_proportion_z_test(23, 25, 18, 25)
    z2, p2 = two_proportion_z_test(18, 25, 23, 25)
    assert math.isclose(z1, -z2, abs_tol=1e-9)
    assert math.isclose(p1, p2, abs_tol=1e-9)


def test_rejects_impossible_k_greater_than_n():
    import pytest
    with pytest.raises(ValueError):
        two_proportion_z_test(26, 25, 10, 25)


def test_small_realistic_gap_is_not_flagged_as_significant():
    # 92% -> 80% on n=25 each is a real, meaningful-looking drop but not statistically
    # distinguishable from noise at this sample size — the exact scenario this module's own
    # docstring warns about (small n, proportion near the boundary). A loose bound, not a
    # hand-computed exact value, to avoid a transcription error asserting false precision.
    result = detect_drift(baseline_correct=23, baseline_n=25, current_correct=20, current_n=25)
    assert 0.10 < result["p_value"] < 0.35
    assert result["drift_detected"] is False


def test_detect_drift_returns_the_full_decision_not_just_a_boolean():
    result = detect_drift(baseline_correct=23, baseline_n=25, current_correct=23, current_n=25)
    assert result["baseline_accuracy"] == 0.92
    assert result["current_accuracy"] == 0.92
    assert result["delta"] == 0.0
    assert result["drift_detected"] is False
    assert result["alpha"] == 0.05
