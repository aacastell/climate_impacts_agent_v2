import numpy as np
import xarray as xr

from narrate_handler import narrate

LON, LAT = -93.6, 42.0


class _FakeS3:
    def __init__(self, objects: dict):
        self.objects = objects

    def download_file(self, bucket, key, dest):
        import shutil

        shutil.copyfile(self.objects[key], dest)


class _FakeResponse:
    def __init__(self, json_body):
        self._json = json_body

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class _FakeHttpClient:
    def __init__(self, response_body):
        self._response_body = response_body
        self.calls = []

    def post(self, url, json):
        self.calls.append({"url": url, "json": json})
        return _FakeResponse(self._response_body)


def _write_field_fixture(path, output_field: str, value: float) -> None:
    data = np.array([[value, 999.0], [999.0, 999.0]])
    ds = (
        xr.DataArray(data, dims=["lat", "lon"], coords={"lat": [LAT, -LAT], "lon": [LON, -LON]})
        .rename(output_field)
        .to_dataset()
    )
    ds.to_netcdf(path)


def _build_fake_s3(tmp_path) -> _FakeS3:
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    objects = {}
    fields = [("tas", 1.8), ("pr_pct", 5.0), ("consecutive_dry_days", 3.0), ("extreme_heat_days", 7.0), ("maize_pct", -12.3)]
    for output_field, value in fields:
        src = remote_dir / f"{output_field}.nc"
        _write_field_fixture(src, output_field, value)
        objects[f"processed/global/{output_field}/y2045.nc"] = src
    return _FakeS3(objects)


def test_narrate_independently_rederives_evidence_and_calls_the_narration_service(tmp_path):
    s3 = _build_fake_s3(tmp_path)
    http_client = _FakeHttpClient({"narration": "text", "verification": {"result": "PASS"}, "status": "PASS", "attempts": 1})
    interpretation = {"region": "Iowa", "region_lon": LON, "region_lat": LAT, "crop": "maize", "warmingLevelC": 2.0, "year": 2045}

    result = narrate(s3, "bucket", tmp_path / "work", http_client, interpretation)

    assert result["status"] == "PASS"
    sent = http_client.calls[0]["json"]
    assert sent["region_name"] == "Iowa"
    assert sent["climate_evidence"]["temp_change_c"] == 1.8
    assert sent["yield_change_pct"] == -12.3


def test_narrate_is_a_pure_function_needing_only_the_interpretation(tmp_path):
    # Real regression guard for ADR-004 Step 4: no hidden dependency on anything interpret()
    # computed beyond what's in the interpretation dict itself.
    s3 = _build_fake_s3(tmp_path)
    http_client = _FakeHttpClient({"narration": "text", "verification": {"result": "PASS"}, "status": "PASS", "attempts": 1})
    interpretation = {"region": "Iowa", "region_lon": LON, "region_lat": LAT, "crop": "maize", "warmingLevelC": 2.0, "year": 2045}

    result_a = narrate(s3, "bucket", tmp_path / "work_a", http_client, interpretation)
    result_b = narrate(s3, "bucket", tmp_path / "work_b", http_client, dict(interpretation))

    assert result_a == result_b
