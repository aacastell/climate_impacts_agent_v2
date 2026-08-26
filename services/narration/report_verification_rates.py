"""Aggregates narrate() verification results across MLflow runs into the per-dimension error-rate
report named as a real, named gap in review/evaluation-and-error-rate.md and ADR-007's own Step 5
("captured as structured evaluation data... this is what gives the CT/model-quality loop an
actual reason to exist later"). Reads what eval_capture.py already logs on every call — this adds
the missing aggregation, not new instrumentation.

Three dimensions, not one flat PASS rate, because "does it pass" now bundles three genuinely
different checks (see graph.py): number provenance (deterministic), driver-mechanism consistency
(LLM-judged against a deterministic covariation signal, only where region size gives it enough
cells to trust — see covariation.py's MIN_CELLS_FOR_CONFIDENCE), and direction/severity (LLM-
judged against the held-out yield number). Reporting one blended rate would hide which kind of
failure is actually happening.

mlflow.search_runs() returns params as strings (MLflow's own tracking-store convention — even a
bool or None becomes "True"/"False"/"None" once logged), not their original Python types — every
comparison below is against string literals for that reason, not an oversight.

Run with: python report_verification_rates.py [--experiment-name NAME]
"""

import argparse
import json

import mlflow


def _rate(mask, denominator) -> float | None:
    return float(mask.sum() / denominator) if denominator else None


def build_report(experiment_name: str = "Default") -> dict:
    runs = mlflow.search_runs(experiment_names=[experiment_name])
    n = len(runs)
    if n == 0:
        return {"experiment_name": experiment_name, "n_runs": 0}

    status_col = "params.status"
    number_guard_col = "params.number_guard_passed"
    mechanism_col = "params.mechanism_consistent"
    covariation_checked_col = "params.covariation_checked"

    overall_pass = runs[status_col] == "PASS" if status_col in runs else None
    number_guard_pass = runs[number_guard_col] == "True" if number_guard_col in runs else None

    # mechanism_consistent is only ever set when covariation_check actually found a confident
    # driver to check against (graph.py's _select_top_driver) — most regions/queries won't have
    # one, so the denominator here is "queries where the check was even possible," not every run.
    judged_mask = runs[mechanism_col].isin(["True", "False"]) if mechanism_col in runs else None
    mechanism_pass = (runs[mechanism_col] == "True") if mechanism_col in runs else None
    n_judged = int(judged_mask.sum()) if judged_mask is not None else 0
    n_covariation_checked = int((runs[covariation_checked_col] == "True").sum()) if covariation_checked_col in runs else 0

    combined_mask = None
    if overall_pass is not None:
        combined_mask = overall_pass.copy()
        if number_guard_pass is not None:
            combined_mask &= number_guard_pass
        if judged_mask is not None and mechanism_pass is not None:
            combined_mask &= ~judged_mask | mechanism_pass  # only penalize where it was actually judged

    return {
        "experiment_name": experiment_name,
        "n_runs": n,
        "overall_pass_rate": _rate(overall_pass, n) if overall_pass is not None else None,
        "number_guard_pass_rate": _rate(number_guard_pass, n) if number_guard_pass is not None else None,
        "n_covariation_checked": n_covariation_checked,
        "mechanism_consistency_rate": _rate(mechanism_pass[judged_mask], n_judged) if n_judged else None,
        "mechanism_consistency_n_judged": n_judged,
        "combined_pass_rate": _rate(combined_mask, n) if combined_mask is not None else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-name", default="Default")
    args = parser.parse_args()
    print(json.dumps(build_report(args.experiment_name), indent=2))


if __name__ == "__main__":
    main()
