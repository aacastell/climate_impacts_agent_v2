import json
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


def _reject_plain_floats(value, path="Item"):
    """Mirrors the real, live-confirmed DynamoDB Table resource behavior: a plain Python float
    anywhere in a put_item Item raises TypeError, not just at the top level. Without this, the
    fake would silently accept exactly the shape that broke in production."""
    if isinstance(value, float):
        raise TypeError(f"Float types are not supported. Use Decimal types instead. (at {path})")
    if isinstance(value, dict):
        for k, v in value.items():
            _reject_plain_floats(v, f"{path}.{k}")
    if isinstance(value, list):
        for i, v in enumerate(value):
            _reject_plain_floats(v, f"{path}[{i}]")


class _FakeSessionTable:
    """Minimal in-memory stand-in for the real DynamoDB Table resource — same
    get_item/put_item/delete_item(Key=...) surface, no AWS involved."""

    def __init__(self):
        self.items = {}

    def get_item(self, Key):
        item = self.items.get(Key["query_id"])
        return {"Item": item} if item is not None else {}

    def put_item(self, Item):
        _reject_plain_floats(Item)
        self.items[Item["query_id"]] = Item

    def delete_item(self, Key):
        self.items.pop(Key["query_id"], None)


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

    # Real regional shading data, not just the single scalar — see
    # pipeline/climate_pipeline/query/lookup.py's grid_patch. The fixture's own two cells are
    # ~187°/84° apart, well outside the default 2° radius, so only the resolved cell itself
    # falls in the box — still a real, non-degenerate grid shape, and the same unit conversion
    # as the scalar (mm/day, not the raw per-second flux) applies to the grid too.
    assert indicators["temp_change"]["grid"]["values"] == [[1.8]]
    assert indicators["precip_change_abs"]["grid"]["values"] == [[round(2e-5 * 86400, 4)]]
    assert result["sectorMap"]["grid"]["values"] == [[-12.3]]


def test_interpret_starts_a_session_on_clarify_and_returns_a_query_id():
    # Real regression guard: a real trace (e.g. a geocode() candidate already seen this turn)
    # contains plain Python floats — DynamoDB's Table resource rejects those natively ("Float
    # types are not supported"), a bug only a real float in the trace would have caught.
    http_client = _FakeHttpClient({
        "kind": "clarify", "question": "Did you mean the Vietnamese Mekong Delta?",
        "tool_use_id": "t1",
        "trace": [
            {"role": "user", "content": [{"text": "What about Mekong?"}]},
            {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t0", "name": "geocode", "input": {"region_text": "Mekong"}}}]},
            {"role": "user", "content": [{"toolResult": {"toolUseId": "t0", "content": [{"json": {"candidates": [{"label": "Mekong Delta, VNM", "lon": 105.8, "lat": 10.0}]}}]}}]},
        ],
    })
    session_table = _FakeSessionTable()

    result = interpret(None, "bucket", None, http_client, "What about Mekong?", session_table=session_table)

    assert result["kind"] == "clarify"
    assert result["question"] == "Did you mean the Vietnamese Mekong Delta?"
    query_id = result["query_id"]
    assert query_id  # a real id was minted

    stored = session_table.items[query_id]
    assert stored["tool_use_id"] == "t1"
    assert stored["original_question"] == "What about Mekong?"
    assert stored["expires_at"] > 0
    # Stored as a JSON string (see interpret()'s own comment on why), and it round-trips exactly.
    assert isinstance(stored["trace"], str)
    round_tripped = json.loads(stored["trace"])
    candidate = round_tripped[2]["content"][0]["toolResult"]["content"][0]["json"]["candidates"][0]
    assert candidate["lon"] == 105.8


def test_interpret_resumes_a_session_by_appending_the_answer_as_a_plain_text_turn():
    # Real bug fixed live: appending the answer as a second toolResult for clarify's own
    # toolUseId caused a real, confirmed ValidationException in production ("Expected toolResult
    # blocks..."). orchestrator.py already completes that toolResult turn itself (a placeholder,
    # since clarify has no computation to run) before ever returning — see its own comment — so
    # the stored trace already satisfies Bedrock's requirement, and the resume path only needs to
    # append the user's answer as a normal next turn, same as a human's reply would be.
    session_table = _FakeSessionTable()
    session_table.put_item(Item={
        "query_id": "abc123",
        # Stored as a JSON string, matching the real write path — see interpret()'s own comment:
        # DynamoDB's Table resource rejects plain float anywhere in a nested Item, which a real
        # trace (real geocode() lon/lat) would contain.
        "trace": json.dumps([
            {"role": "user", "content": [{"text": "What about Mekong?"}]},
            {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t1", "name": "clarify", "input": {"question": "Which one?"}}}]},
            {"role": "user", "content": [{"toolResult": {"toolUseId": "t1", "content": [{"json": {"status": "awaiting_user_clarification"}}]}}]},
        ]),
        "tool_use_id": "t1",
        "original_question": "What about Mekong?",
        "expires_at": 9999999999,
    })
    # "refusal", not "resolved" — this test is about the session/resume mechanics, not the
    # indicator-lookup path (covered by test_interpret_returns_full_answer_when_understanding_resolves).
    http_client = _FakeHttpClient({"kind": "refusal", "reason": "no_resolution", "message": "Still couldn't resolve it."})

    result = interpret(None, "bucket", None, http_client, "ignored on resume", session_table=session_table, query_id="abc123", answer="The Vietnamese one.")

    sent = http_client.calls[0]["json"]
    assert sent["question"] == "What about Mekong?"
    last_message = sent["trace"][-1]
    assert last_message == {"role": "user", "content": [{"text": "The Vietnamese one."}]}
    # Session is cleaned up once the conversation ends (resolved or refused either way) — not
    # left behind for a conversation that's over.
    assert "abc123" not in session_table.items
    assert result["kind"] == "refusal"


def test_interpret_returns_a_typed_refusal_for_an_unknown_or_expired_query_id():
    session_table = _FakeSessionTable()
    http_client = _FakeHttpClient({})  # never called — the session lookup fails before any HTTP call

    result = interpret(None, "bucket", None, http_client, "ignored", session_table=session_table, query_id="does-not-exist", answer="whatever")

    assert result["kind"] == "refusal"
    assert result["reason"] == "session_expired"
    assert http_client.calls == []


def test_interpret_passes_refusal_through():
    http_client = _FakeHttpClient({"kind": "refusal", "reason": "no_resolution", "message": "Could not resolve."})
    result = interpret(None, "bucket", None, http_client, "asdf")
    assert result == {"kind": "refusal", "reason": "no_resolution", "message": "Could not resolve."}
