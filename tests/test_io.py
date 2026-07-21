import json
from datetime import datetime
from pathlib import Path

import paper_agent.io as io_module
from paper_agent.io import append_json_line, create_run_dir, write_json, write_text


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


def test_write_json_atomically_replaces_complete_sibling(tmp_path, monkeypatch):
    target = tmp_path / "artifact.json"
    replacements: list[tuple[Path, Path]] = []
    real_replace = Path.replace

    def recording_replace(source: Path, destination: Path):
        replacements.append((source, destination))
        return real_replace(source, destination)

    monkeypatch.setattr(Path, "replace", recording_replace)
    write_json(target, {"status": "complete"})

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "status": "complete"
    }
    assert replacements[0][1] == target
    assert replacements[0][0].parent == target.parent


def test_failed_atomic_replace_preserves_target_and_cleans_own_sibling(
    tmp_path, monkeypatch
):
    target = tmp_path / "artifact.json"
    target.write_text('{"status":"existing"}', encoding="utf-8")
    existing_sibling = tmp_path / "unrelated.tmp"
    existing_sibling.write_text("keep", encoding="utf-8")
    attempted_sources: list[Path] = []

    def failing_replace(source: Path, destination: Path):
        attempted_sources.append(source)
        raise OSError("replacement failed")

    monkeypatch.setattr(Path, "replace", failing_replace)

    try:
        write_json(target, {"status": "new"})
    except OSError as error:
        assert str(error) == "replacement failed"
    else:
        raise AssertionError("write_json did not propagate replacement failure")

    assert target.read_text(encoding="utf-8") == '{"status":"existing"}'
    assert existing_sibling.read_text(encoding="utf-8") == "keep"
    assert len(attempted_sources) == 1
    assert not attempted_sources[0].exists()


def test_failed_temporary_write_cleans_own_sibling(tmp_path, monkeypatch):
    target = tmp_path / "artifact.json"
    temporary = tmp_path / ".artifact.json.failed.tmp"

    class FailingTemporaryFile:
        name = str(temporary)

        def __enter__(self):
            temporary.write_text("partial", encoding="utf-8")
            return self

        def __exit__(self, *args):
            return False

        def write(self, text: str):
            raise OSError("write failed")

        def flush(self):
            raise AssertionError("flush must not follow a failed write")

    monkeypatch.setattr(
        io_module.tempfile,
        "NamedTemporaryFile",
        lambda **kwargs: FailingTemporaryFile(),
    )

    try:
        write_json(target, {"status": "new"})
    except OSError as error:
        assert str(error) == "write failed"
    else:
        raise AssertionError("write_json did not propagate write failure")

    assert not temporary.exists()
    assert not target.exists()


def test_write_text_uses_atomic_sibling_replacement(tmp_path, monkeypatch):
    target = tmp_path / "report.md"
    replacements: list[tuple[Path, Path]] = []
    real_replace = Path.replace

    def recording_replace(source: Path, destination: Path):
        replacements.append((source, destination))
        return real_replace(source, destination)

    monkeypatch.setattr(Path, "replace", recording_replace)
    write_text(target, "complete report")

    assert target.read_text(encoding="utf-8") == "complete report"
    assert replacements == [(replacements[0][0], target)]
    assert replacements[0][0].parent == target.parent


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
