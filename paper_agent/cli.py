from pathlib import Path

import typer

from paper_agent.pipeline import run_pipeline

app = typer.Typer(help="Paper Agent: citation-traceable paper survey assistant")


@app.callback()
def main() -> None:
    pass


@app.command()
def run(
    question: str,
    limit: int = typer.Option(5, min=1, help="Maximum number of papers to retrieve."),
    no_pdf: bool = typer.Option(False, help="Use abstract-only mode."),
    output_dir: Path = typer.Option(Path("outputs"), help="Base output directory."),
) -> None:
    run_dir = run_pipeline(
        question=question,
        output_base=output_dir,
        limit=limit,
        no_pdf=no_pdf,
    )
    typer.echo(f"Created {run_dir / 'report.md'}")
    typer.echo(f"Created {run_dir / 'papers.json'}")


if __name__ == "__main__":
    app()
