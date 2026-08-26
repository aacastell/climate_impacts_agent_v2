import json

from build_training_dataset import build_dataset
from orchestrator import SYSTEM_PROMPT


def _write_traces_file(path, records: list[dict]) -> None:
    with path.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def test_build_dataset_keeps_only_correct_records(tmp_path):
    trace_correct = [{"role": "user", "content": [{"text": "How will maize yields in Iowa change at 2C?"}]}]
    trace_wrong = [{"role": "user", "content": [{"text": "asdf"}]}]
    _write_traces_file(
        tmp_path / "run_traces.jsonl",
        [
            {"correct": True, "result": {"kind": "resolved"}, "trace": trace_correct},
            {"correct": False, "result": {"kind": "refusal"}, "trace": trace_wrong},
        ],
    )

    records = build_dataset(tmp_path)

    assert len(records) == 1
    assert records[0]["messages"] == trace_correct


def test_build_dataset_excludes_correct_but_erroring_records(tmp_path):
    # A real edge case in the eval harness: run_baseline_eval.py's own try/except means a raised
    # exception is recorded as kind="error" and correct is never True for it — but this guards
    # against that invariant silently breaking later, since a trace ending in an exception isn't
    # a valid tool-calling conversation to train on regardless of what `correct` says.
    _write_traces_file(
        tmp_path / "run_traces.jsonl",
        [{"correct": True, "result": {"kind": "error", "error": "boom"}, "trace": [{"role": "user", "content": [{"text": "x"}]}]}],
    )

    records = build_dataset(tmp_path)

    assert records == []


def test_build_dataset_uses_the_real_system_prompt_and_schema_version():
    trace = [{"role": "user", "content": [{"text": "q"}]}]

    from build_training_dataset import _to_bedrock_conversation_record

    record = _to_bedrock_conversation_record(trace)

    assert record["schemaVersion"] == "bedrock-conversation-2024"
    assert record["system"] == [{"text": SYSTEM_PROMPT}]
    assert record["messages"] == trace


def test_build_dataset_merges_multiple_eval_run_files(tmp_path):
    _write_traces_file(tmp_path / "a_traces.jsonl", [{"correct": True, "result": {"kind": "resolved"}, "trace": [{"role": "user", "content": [{"text": "a"}]}]}])
    _write_traces_file(tmp_path / "b_traces.jsonl", [{"correct": True, "result": {"kind": "resolved"}, "trace": [{"role": "user", "content": [{"text": "b"}]}]}])

    records = build_dataset(tmp_path)

    assert len(records) == 2
