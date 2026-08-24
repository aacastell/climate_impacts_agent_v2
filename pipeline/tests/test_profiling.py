import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from climate_pipeline.fetch.profiling import record_run


def _fetched(size_bytes: int) -> dict:
    return {"size_bytes": size_bytes, "skipped_fetch": False}


def _skipped(size_bytes: int) -> dict:
    return {"size_bytes": size_bytes, "skipped_fetch": True}


def test_record_shape_and_key_format():
    s3 = MagicMock()
    started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    with patch("climate_pipeline.fetch.profiling.boto3.client", return_value=s3):
        with patch("climate_pipeline.fetch.profiling.datetime") as mock_dt:
            mock_dt.now.return_value = started_at + timedelta(seconds=10)
            key = record_run("bucket", "tas_baseline", started_at, [_fetched(1_000_000)])

    assert key == "_profiling/2026-01-01T12-00-00Z/tas_baseline.json"
    s3.put_object.assert_called_once()
    call = s3.put_object.call_args
    assert call.kwargs["Bucket"] == "bucket"
    assert call.kwargs["Key"] == key
    record = json.loads(call.kwargs["Body"])
    assert record["stage"] == "tas_baseline"
    assert record["file_count"] == 1
    assert record["fetched_count"] == 1
    assert record["skipped_count"] == 0
    assert record["duration_seconds"] == 10.0
    assert record["throughput_mbps"] == 0.8  # 1,000,000 bytes * 8 / 1e6 / 10s


def test_throughput_is_none_when_everything_was_skipped():
    s3 = MagicMock()
    started_at = datetime(2026, 1, 1, tzinfo=UTC)

    with patch("climate_pipeline.fetch.profiling.boto3.client", return_value=s3):
        with patch("climate_pipeline.fetch.profiling.datetime") as mock_dt:
            mock_dt.now.return_value = started_at + timedelta(seconds=5)
            record_run("bucket", "pr_future", started_at, [_skipped(500), _skipped(500)])

    record = json.loads(s3.put_object.call_args.kwargs["Body"])
    assert record["fetched_count"] == 0
    assert record["skipped_count"] == 2
    assert record["throughput_mbps"] is None
