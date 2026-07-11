import typer

app = typer.Typer(help="Paper Agent: citation-traceable paper survey assistant")


@app.callback()
def main() -> None:
    pass


@app.command()
def run(
    question: str,
    limit: int = typer.Option(5, min=1, help="Maximum number of papers to retrieve."),
    no_pdf: bool = typer.Option(False, help="Use abstract-only mode."),
) -> None:
    typer.echo(f"Paper Agent MVP placeholder: {question} limit={limit} no_pdf={no_pdf}")


if __name__ == "__main__":
    app()
