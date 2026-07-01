"""Command Line Interface (CLI) for QRP Cloud Controller.

Provides typer-based CLI commands to control and launch quantitative pipelines on the cloud.
"""

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from cloud.config import ConfigManager
from cloud.aws_manager import AWSManager

app = typer.Typer(help="QRP Cloud Controller Command Line Interface.")
aws_app = typer.Typer(help="AWS EC2 instance management commands.")
app.add_typer(aws_app, name="aws")

console = Console()


def get_aws_manager(config_path: str = "configs/config.yaml") -> AWSManager:
    """Helper to load config and initialize AWSManager."""
    config = ConfigManager(config_path)
    config.load()
    region = config.get("aws.region", "ap-south-1")
    instance_id = config.get("aws.instance_id", "")
    return AWSManager(region=region, instance_id=instance_id)


def render_result(title: str, result: dict) -> None:
    """Displays AWS action results using Rich tables and panels."""
    if result.get("success"):
        table = Table(title=title, show_header=True, header_style="bold magenta")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Success", "True")
        table.add_row("Instance ID", result.get("instance_id") or "N/A")

        state = result.get("instance_state", "unknown")
        state_style = "green" if state == "running" else "red" if state == "stopped" else "yellow"
        table.add_row("Instance State", f"[{state_style}]{state}[/]")

        table.add_row("Public IP", result.get("public_ip") or "None")
        table.add_row("Private IP", result.get("private_ip") or "None")

        console.print(table)
    else:
        error_msg = result.get("error", "Unknown error occurred.")
        panel = Panel(
            f"[bold red]Error:[/] {error_msg}",
            title=f"[red]{title} - Failed[/]",
            border_style="red",
        )
        console.print(panel)


@aws_app.command("status")
def status(
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    )
) -> None:
    """Query the status of the configured AWS EC2 instance."""
    try:
        manager = get_aws_manager(config)
        result = manager.get_instance_state()
        if result.get("success"):
            result["instance_id"] = manager.instance_id
        render_result("AWS EC2 Status Inquiry", result)
    except Exception as e:
        console.print(Panel(f"[bold red]CLI Error:[/] {e}", border_style="red"))


@aws_app.command("start")
def start(
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    ),
    wait: bool = typer.Option(True, help="Wait until instance is running before returning."),
) -> None:
    """Start the configured AWS EC2 instance."""
    try:
        manager = get_aws_manager(config)
        result = manager.start_instance()
        if result.get("success") and wait:
            result = manager.wait_until_running()
        if result.get("success"):
            result["instance_id"] = manager.instance_id
        render_result("AWS EC2 Instance Start", result)
    except Exception as e:
        console.print(Panel(f"[bold red]CLI Error:[/] {e}", border_style="red"))


@aws_app.command("stop")
def stop(
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    ),
    wait: bool = typer.Option(True, help="Wait until instance is stopped before returning."),
) -> None:
    """Stop the configured AWS EC2 instance."""
    try:
        manager = get_aws_manager(config)
        result = manager.stop_instance()
        if result.get("success") and wait:
            result = manager.wait_until_stopped()
        if result.get("success"):
            result["instance_id"] = manager.instance_id
        render_result("AWS EC2 Instance Stop", result)
    except Exception as e:
        console.print(Panel(f"[bold red]CLI Error:[/] {e}", border_style="red"))


@aws_app.command("restart")
def restart(
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    )
) -> None:
    """Reboot the configured AWS EC2 instance."""
    try:
        manager = get_aws_manager(config)
        result = manager.reboot_instance()
        if result.get("success"):
            result["instance_id"] = manager.instance_id
        render_result("AWS EC2 Instance Reboot", result)
    except Exception as e:
        console.print(Panel(f"[bold red]CLI Error:[/] {e}", border_style="red"))


if __name__ == "__main__":
    app()
