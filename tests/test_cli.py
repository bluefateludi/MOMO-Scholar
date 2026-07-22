from pathlib import Path

from typer.testing import CliRunner

import paper_agent.cli as cli_module
from paper_agent.cli import app
from paper_agent.pipeline import PipelineResult, PipelineRunFailed


ARTIFACTS = (
    "papers.json", "documents.json", "evidence.json", "analyses.json",
    "report.json", "report.md", "run_manifest.json", "logs.jsonl",
)


def test_completed_run_reports_status_directory_and_all_artifacts(tmp_path, monkeypatch):
    run_dir = tmp_path / "example-run"
    monkeypatch.setattr(cli_module, "run_pipeline", lambda **_: PipelineResult(run_dir, "completed"))
    result = CliRunner().invoke(app, ["run", "test query", "--output-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Status: completed" in result.output
    assert f"Run directory: {run_dir}" in result.output
    assert all(str(run_dir / name) in result.output for name in ARTIFACTS)


def test_degraded_run_warns_and_explicit_no_pdf_is_forwarded(tmp_path, monkeypatch):
    run_dir = tmp_path / "example-run"
    def fake_run_pipeline(**kwargs):
        assert kwargs["no_pdf"] is True
        return PipelineResult(run_dir, "completed_with_degradation")
    monkeypatch.setattr(cli_module, "run_pipeline", fake_run_pipeline)
    result = CliRunner().invoke(app, ["run", "query", "--no-pdf"])
    assert result.exit_code == 0
    assert "completed_with_degradation" in result.output
    assert "warning" in result.output.lower()


def test_pipeline_failure_is_safe_and_does_not_claim_report(tmp_path, monkeypatch):
    run_dir = tmp_path / "failed-run"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").touch()
    (run_dir / "logs.jsonl").touch()
    def fail(**_):
        raise PipelineRunFailed(run_dir, "generation_authentication_failed")
    monkeypatch.setattr(cli_module, "run_pipeline", fail)
    result = CliRunner().invoke(app, ["run", "query"])
    assert result.exit_code == 1
    assert "generation_authentication_failed" in result.output
    assert str(run_dir) in result.output
    assert "run_manifest.json" in result.output and "logs.jsonl" in result.output
    assert "report.md" not in result.output
    assert "Traceback" not in result.output


def test_missing_dashscope_key_is_actionable(tmp_path, monkeypatch):
    def fail(**_):
        raise ValueError("DASHSCOPE_API_KEY is required for generation")
    monkeypatch.setattr(cli_module, "run_pipeline", fail)
    result = CliRunner().invoke(app, ["run", "query"])
    assert result.exit_code == 1
    assert "DASHSCOPE_API_KEY" in result.output
    assert "Traceback" not in result.output


def test_unexpected_programming_error_is_not_hidden(monkeypatch):
    monkeypatch.setattr(cli_module, "run_pipeline", lambda **_: (_ for _ in ()).throw(RuntimeError("bug")))
    result = CliRunner().invoke(app, ["run", "query"])
    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)


def test_cli_rejects_non_positive_limit() -> None:
    result = CliRunner().invoke(app, ["run", "query", "--limit", "0", "--no-pdf"])
    assert result.exit_code != 0
    assert "--limit" in result.output


def test_help_explains_default_pdf_and_explicit_abstract_mode() -> None:
    result = CliRunner().invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "PDF" in result.output
    assert "--no-pdf" in result.output
    assert "abstract" in result.output.lower()
