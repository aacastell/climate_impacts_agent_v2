import json

from climate_pipeline.process.run import (
    ALL_FIELDS,
    FIELD_MANIFESTS,
    FIELD_VARIANTS,
    _manifest_checksums,
    get_or_compute_gwl_year_table,
    output_field_name,
    compute_input_fingerprint,
)


def test_single_variant_fields_keep_their_bare_name():
    for field in ("tas", "consecutive_dry_days", "extreme_heat_days"):
        assert FIELD_VARIANTS[field] == ["absolute"]
        assert output_field_name(field, "absolute") == field


def test_dual_variant_fields_get_suffixed_names():
    for field in ("pr", "maize", "spring_wheat", "soy", "rice"):
        assert FIELD_VARIANTS[field] == ["absolute", "percent"]
        assert output_field_name(field, "absolute") == f"{field}_abs"
        assert output_field_name(field, "percent") == f"{field}_pct"


def test_manifest_checksums_reads_nested_files_list_for_climate_manifests():
    manifest = {"variable": "tas", "files": [{"checksum": "aaa"}, {"checksum": "bbb"}]}
    assert _manifest_checksums(manifest) == ["aaa", "bbb"]


def test_manifest_checksums_reads_top_level_checksum_for_agriculture_manifests():
    manifest = {"s3_key": "raw/agriculture/maize.nc", "checksum": "ccc"}
    assert _manifest_checksums(manifest) == ["ccc"]


def test_compute_input_fingerprint_is_order_independent():
    manifests_a = [{"files": [{"checksum": "aaa"}]}, {"checksum": "bbb"}]
    manifests_b = [{"checksum": "bbb"}, {"files": [{"checksum": "aaa"}]}]
    assert compute_input_fingerprint(manifests_a) == compute_input_fingerprint(manifests_b)


def test_compute_input_fingerprint_changes_when_any_checksum_changes():
    before = [{"files": [{"checksum": "aaa"}]}, {"checksum": "bbb"}]
    after = [{"files": [{"checksum": "aaa"}]}, {"checksum": "ccc"}]
    assert compute_input_fingerprint(before) != compute_input_fingerprint(after)


def test_field_manifests_covers_every_field_with_exactly_two_manifests():
    for field in ALL_FIELDS:
        assert len(FIELD_MANIFESTS[field]) == 2


def test_field_manifests_agriculture_naming():
    assert FIELD_MANIFESTS["maize"] == ("lpjml_maize_baseline", "lpjml_maize_future")
    assert FIELD_MANIFESTS["spring_wheat"] == ("lpjml_spring_wheat_baseline", "lpjml_spring_wheat_future")


def test_field_manifests_climate_naming():
    assert FIELD_MANIFESTS["tas"] == ("tas_baseline", "tas_future")
    assert FIELD_MANIFESTS["pr"] == ("pr_baseline", "pr_future")
    # Derived indices depend on their base climate variable's manifests, not their own.
    assert FIELD_MANIFESTS["consecutive_dry_days"] == ("pr_baseline", "pr_future")
    assert FIELD_MANIFESTS["extreme_heat_days"] == ("tas_baseline", "tas_future")


class _FakeS3ExistingGwlTable:
    """Only supports the "table already exists" path — no tas manifest keys are registered, so
    this fails loudly if get_or_compute_gwl_year_table tries to compute instead of reuse."""

    def __init__(self, table):
        self._table = table

    def head_object(self, Bucket, Key):
        assert Key == "processed/global/gwl_year_table.json"
        return {"Metadata": {}}

    def get_object(self, Bucket, Key):
        assert Key == "processed/global/gwl_year_table.json"

        class _Body:
            def read(_self):
                return json.dumps(self._table).encode("utf-8")

        return {"Body": _Body()}


def test_get_or_compute_gwl_year_table_reuses_an_existing_table_without_recomputing(tmp_path):
    table = [{"gwl_c": 1.5, "year": 2030}]
    s3 = _FakeS3ExistingGwlTable(table)

    result = get_or_compute_gwl_year_table(s3, "bucket", tmp_path / "manifests", tmp_path / "work")

    assert result == table
