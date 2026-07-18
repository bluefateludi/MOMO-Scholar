import json
from datetime import datetime

import paper_agent.io as io_module
from paper_agent.io import append_json_line, create_run_dir, write_json


def test_create_run_dir_uses_slug_and_timestamp(tmp_path):
    run_dir = create_run_dir(
        tmp_path,
        "LLM agents for scientific literature review",
    )

    assert run_dir.exists()
    assert "llm-agents-for-scientific-literature-review" in run_dir.name


def test_create_run_dir_accepts_question_keyword(tmp_path):
    run_dir = create_run_dir(
        base_dir=tmp_path,
        question="Traceable Research",
    )

    assert run_dir.exists()


def test_create_run_dir_is_unique_within_same_second(tmp_path, monkeypatch):
    class FixedDatetime:
        calls = 0

        @classmethod
        def now(cls):
            cls.calls += 1
            return datetime(2026, 7, 11, 12, 30, 45, cls.calls)

    monkeypatch.setattr(io_module, "datetime", FixedDatetime)

    first = create_run_dir(tmp_path, "Traceable Research")
    second = create_run_dir(tmp_path, "Traceable Research")

    assert first.exists()
    assert second.exists()
    assert first != second


def test_write_json_round_trips_data(tmp_path):
    path = tmp_path / "data.json"

    write_json(path, {"hello": "world"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"hello": "world"}


def test_append_json_line_writes_one_compact_utf8_object_per_line(tmp_path) -> None:
    path = tmp_path / "logs.jsonl"
    message = "\u4e2d\u6587"

    append_json_line(path, {"event": "retrieval", "message": message})
    append_json_line(path, {"event": "second"})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        f'{{"event":"retrieval","message":"{message}"}}',
        '{"event":"second"}',
    ]
    assert [json.loads(line) for line in lines] == [
        {"event": "retrieval", "message": message},
        {"event": "second"},
    ]
