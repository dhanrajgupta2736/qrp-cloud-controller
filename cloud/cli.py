"""Command Line Interface (CLI) for QRP Cloud Controller.

Provides typer-based CLI commands to control and launch quantitative pipelines on the cloud.
"""

import typer
from rich.console import Console

app = typer.Typer(help="QRP Cloud Controller Command Line Interface.")
console = Console()


@app.command()
def run(
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    )
) -> None:
    """Run an experiment pipeline end-to-end on AWS EC2."""
    console.print(f"[bold green]Starting experiment run using configuration:[/] [cyan]{config}[/]")
    console.print("Orchestration initialized. (Placeholder execution)")


@app.command()
def status(
    instance_id: str = typer.Argument(..., help="AWS EC2 instance ID to query status for.")
) -> None:
    """Query the status of a specific AWS EC2 instance."""
    console.print(f"Fetching status for instance: [cyan]{instance_id}[/]")


@app.command()
def stop(
    instance_id: str = typer.Argument(..., help="AWS EC2 instance ID to stop.")
) -> None:
    """Stop a running AWS EC2 instance."""
    console.print(f"Stopping instance: [red]{instance_id}[/]")


if __name__ == "__main__":
    app()
