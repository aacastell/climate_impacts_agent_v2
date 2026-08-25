import mlflow

from eval_capture import capture

NARRATE_RESULT = {
    "narration": "Yields are likely to decline modestly.",
    "verification": {"result": "PASS", "direction_match": True, "confidence": 0.8},
    "status": "PASS",
    "attempts": 1,
    "literature": [],
}


def test_capture_logs_a_real_mlflow_run(tmp_path):
    # sqlite, not a plain file:// path — MLflow's filesystem tracking backend is now in
    # maintenance mode and refuses to initialize at all (confirmed live against the real,
    # currently-installed version, not assumed from older docs).
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")
    mlflow.set_experiment("test-experiment")

    capture(NARRATE_RESULT, "Iowa", "maize", 2.0, {"temp_change_c": 1.8}, -12.3)

    client = mlflow.tracking.MlflowClient()
    experiment = client.get_experiment_by_name("test-experiment")
    runs = client.search_runs([experiment.experiment_id])
    assert len(runs) == 1
    assert runs[0].data.params["status"] == "PASS"
    assert runs[0].data.metrics["scientific_disagreement"] == 0.0
