from climate_pipeline.process.field_names import CROP_FIELDS, FIELD_VARIANTS, output_field_name


def test_crop_fields_matches_the_real_fetch_stage_crop_list():
    from climate_pipeline.fetch.agriculture import CROPS

    assert CROP_FIELDS == list(CROPS)


def test_output_field_name_single_variant_field_is_unsuffixed():
    assert output_field_name("tas", "absolute") == "tas"


def test_output_field_name_multi_variant_field_gets_a_suffix():
    assert output_field_name("pr", "absolute") == "pr_abs"
    assert output_field_name("pr", "percent") == "pr_pct"


def test_field_variants_covers_every_crop():
    for crop in CROP_FIELDS:
        assert FIELD_VARIANTS[crop] == ["absolute", "percent"]
