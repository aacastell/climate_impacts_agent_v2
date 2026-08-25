import shutil

import numpy as np
import xarray as xr

from interpret_handler import interpret

LON, LAT = -93.6, 42.0


class _FakeS3:
    def __init__(self, objects: dict):
        self.objects = objects

    def download_file(self, bucket, key, dest):
        shutil.copyfile(self.objects[key], dest)


class _FakeResponse:
    def __init__(self, json_body, status_code=200):
        self._json = json_body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

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
    fields = [("tas", 1.8), ("pr_abs", 2e-5), ("pr_pct", 5.0), ("consecutive_dry_days", 3.0), ("extreme_heat_days", 7.0), ("maize_pct", -12.3)]
    for output_field, value in fields:
        src = remote_dir / f"{output_field}.nc"
        _write_field_fixture(src, output_field, value)
        objects[f"processed/global/{output_field}/y2045.nc"] = src
    return _FakeS3(objects)


def test_interpret_returns_full_answer_when_understanding_resolves(tmp_path):
    s3 = _build_fake_s3(tmp_path)
    http_client = _FakeHttpClient(
        {
            "kind": "resolved",
            "region": {"name": "Iowa", "lon": LON, "lat": LAT},
            "crop": "maize",
            "warmingLevelC": 2.0,
            "year": 2045,
        }
    )

    result = interpret(s3, "bucket", tmp_path / "work", http_client, "How will maize yields in Iowa change at 2C?")

    assert result["kind"] == "answer"
    assert result["interpretation"] == {
        "region": "Iowa",
        "region_lon": LON,
        "region_lat": LAT,
        "crop": "maize",
        "warmingLevelC": 2.0,
        "year": 2045,
    }
    assert result["sectorMap"]["value"] == -12.3
    indicators = {i["id"]: i for i in result["climateMap"]["indicators"]}
    assert indicators["temp_change"]["value"] == 1.8
    assert indicators["precip_change_abs"]["value"] == round(2e-5 * 86400, 4)


def test_interpret_passes_clarify_through():
    http_client = _FakeHttpClient({"kind": "clarify", "question": "Did you mean the Vietnamese Mekong Delta?"})
    result = interpret(None, "bucket", None, http_client, "What about Mekong?")
    assert result == {"kind": "clarify", "question": "Did you mean the Vietnamese Mekong Delta?"}


def test_interpret_passes_refusal_through():
    http_client = _FakeHttpClient({"kind": "refusal", "reason": "no_resolution", "message": "Could not resolve."})
    result = interpret(None, "bucket", None, http_client, "asdf")
    assert result == {"kind": "refusal", "reason": "no_resolution", "message": "Could not resolve."}
