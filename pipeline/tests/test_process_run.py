from climate_pipeline.process.run import (
    FIELD_VARIANTS,
    _manifest_checksums,
    _output_field_name,
    compute_input_fingerprint,
)


def test_single_variant_fields_keep_their_bare_name():
    for field in ("tas", "consecutive_dry_days", "extreme_heat_days"):
        assert FIELD_VARIANTS[field] == ["absolute"]
        assert _output_field_name(field, "absolute") == field


def test_dual_variant_fields_get_suffixed_names():
    for field in ("pr", "maize", "spring_wheat", "soy", "rice"):
        assert FIELD_VARIANTS[field] == ["absolute", "percent"]
        assert _output_field_name(field, "absolute") == f"{field}_abs"
        assert _output_field_name(field, "percent") == f"{field}_pct"


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
