import shutil

import numpy as np
import pytest
import xarray as xr

from climate_pipeline.query.lookup import (
    download_field_window,
    field_window_key,
    grid_patch,
    lookup_grid,
    lookup_value,
    nearest_cell_value,
)


def _write_field_window_fixture(path, output_field: str) -> None:
    """A synthetic precomputed field-window file matching process/run.py's real output shape:
    single variable, (lat, lon) only, no time dimension."""
    data = np.array([[1.0, 2.0], [3.0, 4.0]])
    ds = xr.DataArray(
        data, dims=["lat", "lon"], coords={"lat": [10.0, -10.0], "lon": [-100.0, 100.0]}
    ).rename(output_field).to_dataset()
    ds.to_netcdf(path)


def test_field_window_key_matches_run_pys_real_upload_key():
    assert field_window_key("tas", "absolute", 2050) == "processed/global/tas/y2050.nc"
    assert field_window_key("pr", "percent", 2050) == "processed/global/pr_pct/y2050.nc"


def test_nearest_cell_value_reads_the_closest_grid_cell(tmp_path):
    path = tmp_path / "y2050.nc"
    _write_field_window_fixture(path, "tas")
    # Nearest to (lon=-95, lat=5) is the (-100.0, 10.0) cell -> data[0, 0] == 1.0
    assert nearest_cell_value(path, "tas", "absolute", lon=-95.0, lat=5.0) == 1.0
    # Nearest to (lon=95, lat=-5) is the (100.0, -10.0) cell -> data[1, 1] == 4.0
    assert nearest_cell_value(path, "tas", "absolute", lon=95.0, lat=-5.0) == 4.0


class _FakeS3:
    """Stands in for a boto3 S3 client: download_file just copies from a local "remote" dir,
    so tests exercise the real download-then-read path without touching AWS."""

    def __init__(self, remote_dir):
        self.remote_dir = remote_dir
        self.download_calls = 0

    def download_file(self, bucket, key, dest):
        self.download_calls += 1
        shutil.copyfile(self.remote_dir / key.split("/")[-1], dest)


def test_download_field_window_reuses_an_existing_local_copy(tmp_path):
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    _write_field_window_fixture(remote_dir / "y2050.nc", "tas")
    work_dir = tmp_path / "work"
    s3 = _FakeS3(remote_dir)

    path_a = download_field_window(s3, "bucket", "tas", "absolute", 2050, work_dir)
    path_b = download_field_window(s3, "bucket", "tas", "absolute", 2050, work_dir)

    assert path_a == path_b
    assert s3.download_calls == 1  # second call reused the local copy, no re-download


def test_download_field_window_does_not_collide_across_fields_at_the_same_year(tmp_path):
    # Regression: every field's S3 key leaf is "y{year}.nc" (the field only appears in the key's
    # directory component), so the local cache name must include the field or two different
    # fields at the same year silently overwrite each other.
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    work_dir = tmp_path / "work"

    _write_field_window_fixture(remote_dir / "y2050.nc", "tas")
    tas_path = download_field_window(_FakeS3(remote_dir), "bucket", "tas", "absolute", 2050, work_dir)

    (remote_dir / "y2050.nc").unlink()
    _write_field_window_fixture(remote_dir / "y2050.nc", "pr_abs")
    pr_path = download_field_window(_FakeS3(remote_dir), "bucket", "pr", "absolute", 2050, work_dir)

    assert tas_path != pr_path
    assert nearest_cell_value(tas_path, "tas", "absolute", lon=-95.0, lat=5.0) == 1.0
    assert nearest_cell_value(pr_path, "pr", "absolute", lon=-95.0, lat=5.0) == 1.0


def test_lookup_value_end_to_end(tmp_path):
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    _write_field_window_fixture(remote_dir / "y2050.nc", "pr_abs")
    s3 = _FakeS3(remote_dir)

    value = lookup_value(s3, "bucket", "pr", "absolute", 2050, lon=-95.0, lat=5.0, work_dir=tmp_path / "work")

    assert value == 1.0


def test_lookup_value_rejects_an_invalid_kind_for_the_field(tmp_path):
    with pytest.raises(ValueError, match="percent"):
        lookup_value(
            _FakeS3(tmp_path), "bucket", "tas", "percent", 2050, lon=0.0, lat=0.0, work_dir=tmp_path / "work"
        )


def _write_fine_grid_fixture(path, output_field: str) -> None:
    """A finer, real-resolution-like fixture (1° spacing, 5x5) — the 2x2/100°-apart fixture above
    is too sparse to exercise a real spatial box selection; this one has a real NaN cell too
    (ocean/masked-land stand-in), which grid_patch must turn into None, not fabricate a value
    for."""
    lats = [2.0, 1.0, 0.0, -1.0, -2.0]
    lons = [-2.0, -1.0, 0.0, 1.0, 2.0]
    data = np.array([[float(i * 5 + j) for j in range(5)] for i in range(5)])
    data[2, 2] = np.nan  # the center cell — real ocean/masked-land stand-in
    ds = xr.DataArray(data, dims=["lat", "lon"], coords={"lat": lats, "lon": lons}).rename(output_field).to_dataset()
    ds.to_netcdf(path)


def test_grid_patch_returns_a_real_spatial_box_not_one_cell(tmp_path):
    path = tmp_path / "y2050.nc"
    _write_fine_grid_fixture(path, "tas")

    patch = grid_patch(path, "tas", "absolute", lon=0.0, lat=0.0, radius_deg=1.0)

    # radius_deg=1.0 around (0,0) on a 1°-spaced grid keeps lon/lat in {-1, 0, 1} — a real 3x3
    # box, not the single nearest cell nearest_cell_value would return.
    assert patch["lons"] == [-1.0, 0.0, 1.0]
    assert patch["lats"] == [1.0, 0.0, -1.0]
    assert len(patch["values"]) == 3
    assert all(len(row) == 3 for row in patch["values"])


def test_grid_patch_turns_a_real_nan_cell_into_none_not_a_fabricated_value(tmp_path):
    path = tmp_path / "y2050.nc"
    _write_fine_grid_fixture(path, "tas")

    patch = grid_patch(path, "tas", "absolute", lon=0.0, lat=0.0, radius_deg=1.0)

    center_row = patch["lats"].index(0.0)
    center_col = patch["lons"].index(0.0)
    assert patch["values"][center_row][center_col] is None


def test_grid_patch_a_bigger_box_grows_correctly_with_radius(tmp_path):
    path = tmp_path / "y2050.nc"
    _write_fine_grid_fixture(path, "tas")

    small = grid_patch(path, "tas", "absolute", lon=0.0, lat=0.0, radius_deg=1.0)
    big = grid_patch(path, "tas", "absolute", lon=0.0, lat=0.0, radius_deg=2.0)

    assert len(small["lons"]) == 3
    assert len(big["lons"]) == 5


def test_lookup_grid_end_to_end(tmp_path):
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    _write_fine_grid_fixture(remote_dir / "y2050.nc", "pr_abs")
    s3 = _FakeS3(remote_dir)

    patch = lookup_grid(s3, "bucket", "pr", "absolute", 2050, lon=0.0, lat=0.0, work_dir=tmp_path / "work", radius_deg=1.0)

    assert len(patch["lons"]) == 3
    assert len(patch["lats"]) == 3


def test_lookup_grid_rejects_an_invalid_kind_for_the_field(tmp_path):
    with pytest.raises(ValueError, match="percent"):
        lookup_grid(
            _FakeS3(tmp_path), "bucket", "tas", "percent", 2050, lon=0.0, lat=0.0, work_dir=tmp_path / "work"
        )
