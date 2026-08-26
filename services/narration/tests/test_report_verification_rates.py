import pandas as pd
import pytest

import report_verification_rates as report_module
from report_verification_rates import build_report


def _runs(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_build_report_returns_zero_runs_when_experiment_is_empty(monkeypatch):
    monkeypatch.setattr(report_module.mlflow, "search_runs", lambda experiment_names: pd.DataFrame())

    report = build_report("Default")

    assert report == {"experiment_name": "Default", "n_runs": 0}


def test_build_report_computes_overall_and_number_guard_pass_rates(monkeypatch):
    rows = [
        {"params.status": "PASS", "params.number_guard_passed": "True", "params.mechanism_consistent": "None", "params.covariation_checked": "False"},
        {"params.status": "PASS", "params.number_guard_passed": "True", "params.mechanism_consistent": "None", "params.covariation_checked": "False"},
        {"params.status": "SCIENTIFIC_DISAGREEMENT", "params.number_guard_passed": "False", "params.mechanism_consistent": "None", "params.covariation_checked": "False"},
        {"params.status": "PASS", "params.number_guard_passed": "True", "params.mechanism_consistent": "None", "params.covariation_checked": "False"},
    ]
    monkeypatch.setattr(report_module.mlflow, "search_runs", lambda experiment_names: _runs(rows))

    report = build_report("Default")

    assert report["n_runs"] == 4
    assert report["overall_pass_rate"] == 0.75
    assert report["number_guard_pass_rate"] == 0.75


def test_build_report_only_denominates_mechanism_consistency_by_runs_where_it_was_judged(monkeypatch):
    # Most queries won't have a confident enough region to check a mechanism at all (see
    # covariation.py's MIN_CELLS_FOR_CONFIDENCE) — the rate must not silently count those as
    # failures, or pass rate would be meaningless everywhere covariation wasn't even attempted.
    rows = [
        {"params.status": "PASS", "params.number_guard_passed": "True", "params.mechanism_consistent": "True", "params.covariation_checked": "True"},
        {"params.status": "PASS", "params.number_guard_passed": "True", "params.mechanism_consistent": "False", "params.covariation_checked": "True"},
        {"params.status": "PASS", "params.number_guard_passed": "True", "params.mechanism_consistent": "None", "params.covariation_checked": "False"},
        {"params.status": "PASS", "params.number_guard_passed": "True", "params.mechanism_consistent": "None", "params.covariation_checked": "False"},
    ]
    monkeypatch.setattr(report_module.mlflow, "search_runs", lambda experiment_names: _runs(rows))

    report = build_report("Default")

    assert report["n_runs"] == 4
    assert report["mechanism_consistency_n_judged"] == 2
    assert report["mechanism_consistency_rate"] == 0.5
    assert report["n_covariation_checked"] == 2


def test_build_report_combined_pass_rate_requires_all_checks_that_actually_ran(monkeypatch):
    rows = [
        # passes everything actually checked
        {"params.status": "PASS", "params.number_guard_passed": "True", "params.mechanism_consistent": "None", "params.covariation_checked": "False"},
        # overall PASS, but number guard failed on the way there is impossible in real data (a
        # number-guard fail always retries or ends in SCIENTIFIC_DISAGREEMENT — see graph.py) —
        # still worth confirming the combined rate would catch such a row if it existed.
        {"params.status": "PASS", "params.number_guard_passed": "False", "params.mechanism_consistent": "None", "params.covariation_checked": "False"},
        # mechanism was judged and failed -> should count against combined even though status=PASS
        {"params.status": "PASS", "params.number_guard_passed": "True", "params.mechanism_consistent": "False", "params.covariation_checked": "True"},
    ]
    monkeypatch.setattr(report_module.mlflow, "search_runs", lambda experiment_names: _runs(rows))

    report = build_report("Default")

    assert report["combined_pass_rate"] == pytest.approx(1 / 3)
