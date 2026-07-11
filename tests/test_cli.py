from typer.testing import CliRunner

from paper_agent.cli import app


def test_run_command_accepts_explicit_subcommand() -> None:
    result = CliRunner().invoke(
        app,
        ["run", "test query", "--limit", "2", "--no-pdf"],
    )

    assert result.exit_code == 0
    assert result.output == "Paper Agent MVP placeholder: test query limit=2 no_pdf=True\n"


def test_cli_rejects_non_positive_limit() -> None:
    result = CliRunner().invoke(
        app,
        ["run", "query", "--limit", "0", "--no-pdf"],
    )

    assert result.exit_code != 0
    assert "--limit" in result.output
    assert "x>=1" in result.output
