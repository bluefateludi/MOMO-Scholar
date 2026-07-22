from pathlib import Path

import typer

from paper_agent.pipeline import PipelineRunFailed, run_pipeline

app = typer.Typer(help="Paper Agent: citation-traceable paper survey assistant")

_ARTIFACTS = (
    "papers.json",
    "documents.json",
    "evidence.json",
    "analyses.json",
    "report.json",
    "report.md",
    "run_manifest.json",
    "logs.jsonl",
)


@app.callback()
def main() -> None:
    pass


@app.command()
def run(
    question: str,
    limit: int = typer.Option(5, min=1, help="Maximum number of papers to retrieve."),
    no_pdf: bool = typer.Option(
        False,
        "--no-pdf",
        help="Explicitly use abstract mode; by default public arXiv PDFs are downloaded.",
    ),
    output_dir: Path = typer.Option(Path("outputs"), help="Base output directory."),
) -> None:
    try:
        result = run_pipeline(
            question=question,
            output_base=output_dir,
            limit=limit,
            no_pdf=no_pdf,
        )
    except PipelineRunFailed as error:
        typer.echo(f"Run failed: {error.code}", err=True)
        typer.echo(f"Run directory: {error.run_dir}", err=True)
        for name in ("run_manifest.json", "logs.jsonl"):
            path = error.run_dir / name
            if path.exists():
                typer.echo(f"Diagnostics: {path}", err=True)
        raise typer.Exit(code=1) from None
    except ValueError as error:
        typer.echo(f"Configuration error: {error}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Status: {result.status}")
    typer.echo(f"Run directory: {result.run_dir}")
    if result.status == "completed_with_degradation":
        typer.echo("Warning: the run completed with documented degradations.", err=True)
    for name in _ARTIFACTS:
        typer.echo(f"Artifact: {result.run_dir / name}")


if __name__ == "__main__":
    app()
