import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from paper_agent.observability.models import (
    RunCounts,
    RunEvent,
    SafeRunSettings,
    UsageTotals,
)
from paper_agent.observability.recorder import RunRecorder
from paper_agent.schemas import Paper
from paper_agent.synthesis.models import CheckedSurveyReport


NOW = datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc)
FIXED_CLOCK = lambda: NOW
SAFE_SETTINGS = SafeRunSettings(
    retrieval_mode="auto",
    embedding_model="text-embedding-v4",
    generation_provider="dashscope",
    generation_endpoint_host="dashscope.aliyuncs.com",
    generation_model="qwen3.7-plus",
    generation_timeout_seconds=60,
    pdf_download_timeout_seconds=30,
    pdf_max_bytes=25_000_000,
    pdf_max_pages=200,
    analysis_evidence_per_paper=6,
    chunk_max_words=180,
    chunk_overlap_words=30,
)
COUNTS = RunCounts(
    selected_papers=0,
    pdf_documents=0,
    abstract_documents=0,
    explicit_abstract_documents=0,
    pdf_fallback_documents=0,
    excluded_papers=0,
    successful_analyses=0,
    evidence_items=0,
)
USAGE = UsageTotals(operations=0, http_attempts=0)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _start(tmp_path: Path) -> RunRecorder:
    return RunRecorder.start(
        output_base=tmp_path,
        question="grounded review",
        requested_limit=3,
        no_pdf=False,
        safe_settings=SAFE_SETTINGS,
        component_versions={
            "paper-agent": "0.1.0",
            "pymupdf": "1.28.0",
            "mupdf": "1.28.0",
        },
        clock=FIXED_CLOCK,
    )


def test_recorder_writes_running_then_one_terminal_manifest(tmp_path) -> None:
    recorder = _start(tmp_path)
    running = _read_json(recorder.run_dir / "run_manifest.json")
    assert running["status"] == "running"
    assert running["started_at"] == "2026-07-21T12:30:00Z"
    assert (recorder.run_dir / "logs.jsonl").exists()

    recorder.complete(
        status="completed",
        counts=COUNTS,
        retrieval_outcomes=(),
        stage_elapsed_seconds={},
        usage=USAGE,
    )
    terminal = _read_json(recorder.run_dir / "run_manifest.json")
    assert terminal["status"] == "completed"
    assert terminal["finished_at"] == "2026-07-21T12:30:00Z"

    recorder.complete(
        status="completed",
        counts=COUNTS,
        retrieval_outcomes=(),
        stage_elapsed_seconds={},
        usage=USAGE,
    )
    with pytest.raises(RuntimeError, match="already terminal"):
        recorder.fail(
            code="late_failure",
            stage="test",
            counts=COUNTS,
            retrieval_outcomes=(),
            stage_elapsed_seconds={},
            usage=USAGE,
        )


def test_emit_writes_one_sanitized_json_event_per_line(tmp_path) -> None:
    recorder = _start(tmp_path)
    recorder.emit(
        RunEvent(
            timestamp=NOW,
            run_id=recorder.run_id,
            stage="generation",
            operation="request",
            status="error",
            attributes={"Authorization": "Bearer private", "prompt_tokens": 4},
        )
    )

    lines = (recorder.run_dir / "logs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["attributes"] == {
        "Authorization": "[REDACTED]",
        "prompt_tokens": 4,
    }


def test_failure_retains_artifacts_and_forbids_publication(tmp_path) -> None:
    recorder = _start(tmp_path)
    recorder.write_papers(
        [
            Paper(
                paper_id="arxiv:1",
                title="Title",
                url="https://arxiv.org/abs/1",
                source="arxiv",
            )
        ]
    )
    recorder.fail(
        stage="analysis",
        code="generation_failed",
        message="safe detail",
        counts=COUNTS,
        retrieval_outcomes=(),
        stage_elapsed_seconds={"analysis": 1.5},
        usage=USAGE,
    )

    assert (recorder.run_dir / "papers.json").exists()
    assert _read_json(recorder.run_dir / "run_manifest.json")["errors"][0] == {
        "stage": "analysis",
        "code": "generation_failed",
        "paper_id": None,
        "message": "safe detail",
    }
    with pytest.raises(RuntimeError, match="already terminal"):
        recorder.publish_report(CheckedSurveyReport(question="q"), "report")
    assert not (recorder.run_dir / "report.json").exists()
    assert not (recorder.run_dir / "report.md").exists()


def test_publish_report_prepares_both_files_before_replacing(
    tmp_path, monkeypatch
) -> None:
    recorder = _start(tmp_path)
    replacements: list[tuple[Path, Path]] = []
    real_replace = Path.replace

    def recording_replace(source: Path, target: Path):
        if not replacements:
            assert len(list(recorder.run_dir.glob(".*.tmp"))) == 2
        replacements.append((source, target))
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", recording_replace)
    recorder.publish_report(CheckedSurveyReport(question="q"), "# Report")

    assert [target.name for _, target in replacements] == ["report.json", "report.md"]
    assert _read_json(recorder.run_dir / "report.json")["question"] == "q"
    assert (recorder.run_dir / "report.md").read_text(encoding="utf-8") == "# Report"


def test_second_report_replacement_failure_is_per_file_atomic(
    tmp_path, monkeypatch
) -> None:
    recorder = _start(tmp_path)
    real_replace = Path.replace
    calls = 0

    def fail_second_replace(source: Path, target: Path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second replacement failed")
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_second_replace)
    with pytest.raises(OSError, match="second replacement failed"):
        recorder.publish_report(CheckedSurveyReport(question="q"), "# Report")

    assert (recorder.run_dir / "report.json").exists()
    assert not (recorder.run_dir / "report.md").exists()
    assert _read_json(recorder.run_dir / "run_manifest.json")["status"] == "running"


def test_report_preparation_failure_publishes_nothing_and_cleans_temporary_files(
    tmp_path, monkeypatch
) -> None:
    recorder = _start(tmp_path)
    real_prepare = recorder._prepare_temporary
    calls = 0

    def fail_second_prepare(target: Path, text: str) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("preparation failed")
        return real_prepare(target, text)

    monkeypatch.setattr(recorder, "_prepare_temporary", fail_second_prepare)
    with pytest.raises(OSError, match="preparation failed"):
        recorder.publish_report(CheckedSurveyReport(question="q"), "# Report")

    assert not (recorder.run_dir / "report.json").exists()
    assert not (recorder.run_dir / "report.md").exists()
    assert list(recorder.run_dir.glob(".*.tmp")) == []


def test_terminal_manifest_write_failure_does_not_consume_transition(
    tmp_path, monkeypatch
) -> None:
    recorder = _start(tmp_path)
    original_write = recorder._write_manifest

    def fail_write(*args, **kwargs) -> None:
        raise OSError("manifest replacement failed")

    monkeypatch.setattr(recorder, "_write_manifest", fail_write)
    with pytest.raises(OSError, match="manifest replacement failed"):
        recorder.complete(
            status="completed",
            counts=COUNTS,
            retrieval_outcomes=(),
            stage_elapsed_seconds={},
            usage=USAGE,
        )

    monkeypatch.setattr(recorder, "_write_manifest", original_write)
    recorder.fail(
        stage="publication",
        code="manifest_write_failed",
        counts=COUNTS,
        retrieval_outcomes=(),
        stage_elapsed_seconds={},
        usage=USAGE,
    )
    assert _read_json(recorder.run_dir / "run_manifest.json")["status"] == "failed"
