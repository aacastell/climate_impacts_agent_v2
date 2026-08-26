"""Captures narrate()'s result as structured evaluation data — see ADR-007 Step 5: "Every
SCIENTIFIC_DISAGREEMENT (and more broadly every case that doesn't cleanly PASS) is captured as
structured evaluation data... This is what gives the eventual CT/model-quality loop an actual
reason to exist later." And the Accompanying decision: "MLflow tracks the evaluation loop this
gate produces specifically: model version -> evaluation dataset -> tool-calling accuracy ->
consistency accuracy -> model candidate."

Logs every narrate() call as its own MLflow run (not just the non-PASS ones — PASS cases are the
denominator any later accuracy metric needs, not just the failures) with the full query context,
evidence, literature, generated text, and verification result as run params/artifacts. No real
MLflow tracking server is provisioned tonight (see docs/overnight-2026-08-25.md) — this reads
MLFLOW_TRACKING_URI the standard way, so it points at a real server the moment one exists, with no
code change. One real thing worth knowing, confirmed live against the currently-installed MLflow
version (not assumed from older docs): the plain filesystem backend (a bare "./mlruns" path) is
now in maintenance mode and refuses to initialize at all unless MLFLOW_ALLOW_FILE_STORE is
explicitly set — MLFLOW_TRACKING_URI needs to be a real database backend (e.g.
"sqlite:///mlflow.db") to work today, not a plain local path.

Extended for the number-guard and covariation-check nodes (graph.py) — logged as their own
params/metrics, not just buried in the artifact JSON, specifically so report_verification_rates.py
can query and slice by them directly (mlflow.search_runs filters/reads params and metrics without
needing to open every run's artifact).
"""

import mlflow


def capture(
    narrate_result: dict,
    region_name: str,
    crop_label: str,
    warming_level_c: float,
    climate_evidence: dict,
    yield_change_pct: float,
    driver_covariation: dict,
) -> None:
    number_guard = narrate_result.get("number_guard") or {}
    covariation_result = narrate_result.get("covariation_result") or {}
    verification = narrate_result["verification"]

    with mlflow.start_run(run_name=f"narrate-{region_name}-{crop_label}-{warming_level_c}C"):
        mlflow.log_params(
            {
                "region_name": region_name,
                "crop_label": crop_label,
                "warming_level_c": warming_level_c,
                "status": narrate_result["status"],
                "attempts": narrate_result["attempts"],
                "verification_result": verification["result"],
                "direction_match": verification.get("direction_match"),
                "confidence": verification.get("confidence"),
                "number_guard_passed": number_guard.get("passed"),
                "covariation_checked": covariation_result.get("checked"),
                "top_covariation_driver": covariation_result.get("top_driver"),
                "mechanism_consistent": verification.get("mechanism_consistent"),
            }
        )
        mlflow.log_metric("attempts", narrate_result["attempts"])
        mlflow.log_metric("scientific_disagreement", 1 if narrate_result["status"] == "SCIENTIFIC_DISAGREEMENT" else 0)
        mlflow.log_metric("unsupported_number_count", len(number_guard.get("unsupported_numbers", [])))
        if covariation_result.get("top_r") is not None:
            mlflow.log_metric("top_covariation_r", covariation_result["top_r"])
        mlflow.log_dict(
            {
                "climate_evidence": climate_evidence,
                "yield_change_pct": yield_change_pct,
                "driver_covariation": driver_covariation,
                "literature": narrate_result["literature"],
                "narration": narrate_result["narration"],
                "verification": verification,
                "number_guard": number_guard,
                "covariation_result": covariation_result,
            },
            "eval_record.json",
        )
