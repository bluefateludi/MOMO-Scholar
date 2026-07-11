from typer.testing import CliRunner

import paper_agent.cli as cli_module
from paper_agent.cli import app


def test_run_command_accepts_explicit_subcommand(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "example-run"
    run_dir.mkdir()

    def fake_run_pipeline(**kwargs):
        assert kwargs["question"] == "test query"
        assert kwargs["limit"] == 2
        assert kwargs["no_pdf"] is True
        return run_dir

    monkeypatch.setattr(cli_module, "run_pipeline", fake_run_pipeline)
    result = CliRunner().invoke(
        app,
        ["run", "test query", "--limit", "2", "--no-pdf", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert f"Created {run_dir / 'report.md'}" in result.output
    assert f"Created {run_dir / 'papers.json'}" in result.output


def test_cli_rejects_non_positive_limit() -> None:
    result = CliRunner().invoke(
        app,
        ["run", "query", "--limit", "0", "--no-pdf"],
    )

    assert result.exit_code != 0
    assert "--limit" in result.output
    assert "x>=1" in result.output
