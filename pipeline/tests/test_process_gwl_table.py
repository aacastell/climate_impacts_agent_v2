import json

from climate_pipeline.process.gwl_table import compute_gwl_year_table, gwl_year_table_exists


class _FakeS3ExistingTable:
    """Only supports the "table already exists" path — no tas manifest keys are registered, so
    this fails loudly if compute_gwl_year_table tries to compute instead of reuse."""

    def __init__(self, table):
        self._table = table

    def head_object(self, Bucket, Key):
        assert Key == "processed/global/gwl_year_table.json"
        return {}

    def get_object(self, Bucket, Key):
        assert Key == "processed/global/gwl_year_table.json"

        class _Body:
            def read(_self):
                return json.dumps(self._table).encode("utf-8")

        return {"Body": _Body()}


def test_gwl_year_table_exists_true_when_present():
    s3 = _FakeS3ExistingTable([{"gwl_c": 1.5, "year": 2030}])
    assert gwl_year_table_exists(s3, "bucket") is True


def test_compute_gwl_year_table_reuses_an_existing_table_without_recomputing(tmp_path):
    table = [{"gwl_c": 1.5, "year": 2030}]
    s3 = _FakeS3ExistingTable(table)

    result = compute_gwl_year_table(s3, "bucket", tmp_path / "manifests", tmp_path / "work")

    assert result == table
