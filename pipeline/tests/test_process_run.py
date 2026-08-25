from climate_pipeline.process.run import (
    ALL_FIELDS,
    FIELD_MANIFESTS,
    FIELD_VARIANTS,
    _manifest_checksums,
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


def test_no_field_manifest_mentions_tas_preindustrial():
    # Real regression guard: no field's own output should ever depend on GWL/preindustrial data —
    # that's gwl_table.py's job alone. See run.py's module docstring.
    for manifests in FIELD_MANIFESTS.values():
        assert "tas_preindustrial" not in manifests
