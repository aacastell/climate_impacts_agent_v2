import json

from climate_pipeline.fetch.corpus import SOURCES_FILE, _load_sources


def test_sources_file_is_real_valid_json_with_required_fields():
    sources = _load_sources()
    assert len(sources) > 0
    for source in sources:
        assert set(source.keys()) == {"id", "title", "url"}
        assert source["url"].startswith("https://")


def test_source_ids_are_unique():
    sources = _load_sources()
    ids = [s["id"] for s in sources]
    assert len(ids) == len(set(ids))


def test_sources_file_is_actually_at_the_expected_path():
    assert SOURCES_FILE.name == "CORPUS_SOURCES.json"
    assert SOURCES_FILE.exists()
