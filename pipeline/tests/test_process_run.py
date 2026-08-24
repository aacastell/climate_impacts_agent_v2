from climate_pipeline.process.run import FIELD_VARIANTS, _output_field_name


def test_single_variant_fields_keep_their_bare_name():
    for field in ("tas", "consecutive_dry_days", "extreme_heat_days"):
        assert FIELD_VARIANTS[field] == ["absolute"]
        assert _output_field_name(field, "absolute") == field


def test_dual_variant_fields_get_suffixed_names():
    for field in ("pr", "maize", "spring_wheat", "soy", "rice"):
        assert FIELD_VARIANTS[field] == ["absolute", "percent"]
        assert _output_field_name(field, "absolute") == f"{field}_abs"
        assert _output_field_name(field, "percent") == f"{field}_pct"
