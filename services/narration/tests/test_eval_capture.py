import mlflow

from eval_capture import capture

NARRATE_RESULT = {
    "narration": "Yields are likely to decline modestly.",
    "verification": {"result": "PASS", "direction_match": True, "confidence": 0.8, "mechanism_consistent": True},
    "status": "PASS",
    "attempts": 1,
    "literature": [],
    "number_guard": {"passed": True, "unsupported_numbers": []},
    "covariation_result": {"checked": True, "top_driver": "extreme_heat_days", "top_r": 0.9},
}
DRIVER_COVARIATION = {"extreme_heat_days": {"r": 0.9, "cell_count": 20, "low_confidence": False}}


def test_capture_logs_a_real_mlflow_run(tmp_path):
    # sqlite, not a plain file:// path — MLflow's filesystem tracking backend is now in
    # maintenance mode and refuses to initialize at all (confirmed live against the real,
    # currently-installed version, not assumed from older docs).
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")
    mlflow.set_experiment("test-experiment")

    capture(NARRATE_RESULT, "Iowa", "maize", 2.0, {"temp_change_c": 1.8}, -12.3, DRIVER_COVARIATION)

    client = mlflow.tracking.MlflowClient()
    experiment = client.get_experiment_by_name("test-experiment")
    runs = client.search_runs([experiment.experiment_id])
    assert len(runs) == 1
    assert runs[0].data.params["status"] == "PASS"
    assert runs[0].data.metrics["scientific_disagreement"] == 0.0
    assert runs[0].data.params["number_guard_passed"] == "True"
    assert runs[0].data.params["top_covariation_driver"] == "extreme_heat_days"
    assert runs[0].data.params["mechanism_consistent"] == "True"
    assert runs[0].data.metrics["top_covariation_r"] == 0.9
    assert runs[0].data.metrics["unsupported_number_count"] == 0.0


def test_capture_logs_zero_covariation_r_metric_absent_when_not_checked(tmp_path):
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")
    mlflow.set_experiment("test-experiment-unchecked")
    result = {
        **NARRATE_RESULT,
        "covariation_result": {"checked": False, "top_driver": None, "top_r": None},
    }

    capture(result, "Iowa", "maize", 2.0, {"temp_change_c": 1.8}, -12.3, {})

    client = mlflow.tracking.MlflowClient()
    experiment = client.get_experiment_by_name("test-experiment-unchecked")
    runs = client.search_runs([experiment.experiment_id])
    assert "top_covariation_r" not in runs[0].data.metrics
    assert runs[0].data.params["top_covariation_driver"] == "None"
