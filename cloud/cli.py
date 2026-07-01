"""Command Line Interface (CLI) for QRP Cloud Controller.

Provides typer-based CLI commands to control and launch quantitative pipelines on the cloud.
"""

import os
import stat as stat_mod
import time
from typing import List, Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from cloud.config import ConfigManager
from cloud.aws_manager import AWSManager
from cloud.ssh_manager import SSHManager
from cloud.file_manager import FileManager, _resolve_remote_path
from cloud.git_manager import GitManager
from cloud.research_runner import ResearchRunner

app = typer.Typer(help="QRP Cloud Controller Command Line Interface.")
aws_app = typer.Typer(help="AWS EC2 instance management commands.")
ssh_app = typer.Typer(help="SSH remote execution and file transfer commands.")
file_app = typer.Typer(help="SFTP remote file and directory transfer commands.")
git_app = typer.Typer(help="Git version control management commands.")
research_app = typer.Typer(help="Orchestrated quantitative research experiment commands.")

app.add_typer(aws_app, name="aws")
app.add_typer(ssh_app, name="ssh")
app.add_typer(file_app, name="file")
app.add_typer(git_app, name="git")
app.add_typer(research_app, name="research")

console = Console()


# --- AWS Helpers ---

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


# --- SSH Helpers ---

def get_ssh_manager(config_path: str = "configs/config.yaml") -> SSHManager:
    """Helper to load config and query the active public IP to initialize SSHManager."""
    config = ConfigManager(config_path)
    config.load()
    region = config.get("aws.region", "ap-south-1")
    instance_id = config.get("aws.instance_id", "")
    username = config.get("aws.ssh_user", "ubuntu")
    key_path = config.get("aws.ssh_key", "")

    if not instance_id:
        raise ValueError("AWS EC2 instance_id is not configured in configs/config.yaml.")

    # Query active public IP dynamically from AWS
    aws_mgr = AWSManager(region=region, instance_id=instance_id)
    state_info = aws_mgr.get_instance_state()
    if not state_info.get("success"):
        raise RuntimeError(f"Failed to query EC2 instance state: {state_info.get('error')}")

    state = state_info.get("instance_state")
    if state != "running":
        raise RuntimeError(
            f"EC2 Instance {instance_id} is in '{state}' state. It must be 'running' to connect via SSH."
        )

    public_ip = state_info.get("public_ip")
    if not public_ip:
        raise RuntimeError(
            f"Could not retrieve public IP address for EC2 Instance {instance_id} (even though state is 'running')."
        )

    return SSHManager(hostname=public_ip, username=username, key_path=key_path)


# --- File Helpers ---

def get_file_manager(config_path: str = "configs/config.yaml") -> FileManager:
    """Helper to load SSH config and initialize FileManager."""
    ssh_mgr = get_ssh_manager(config_path)
    return FileManager(ssh_mgr)


# --- Git Helpers ---

def get_local_git_manager() -> GitManager:
    """Helper to initialize GitManager for local Git tasks (does not require SSH)."""
    return GitManager()


def get_git_manager(config_path: str = "configs/config.yaml") -> GitManager:
    """Helper to load SSH config and initialize GitManager for remote tasks."""
    ssh_mgr = get_ssh_manager(config_path)
    return GitManager(ssh_manager=ssh_mgr)


# --- AWS Commands ---

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


# --- SSH Commands ---

@ssh_app.command("connect")
def ssh_connect(
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    )
) -> None:
    """Test and establish SSH connection to the remote EC2 instance."""
    try:
        manager = get_ssh_manager(config)
        result = manager.connect()
        if result.get("success"):
            console.print(
                Panel(
                    f"[green]Successfully connected to remote host:[/] [bold cyan]{manager.hostname}[/]\n"
                    f"[green]User:[/] {manager.username}\n"
                    f"[green]Key Path:[/] {manager.key_path}",
                    title="SSH Connection Test - SUCCESS",
                    border_style="green",
                )
            )
            manager.disconnect()
        else:
            console.print(
                Panel(
                    f"[bold red]SSH connection failed:[/] {result.get('error')}",
                    title="SSH Connection Test - FAILED",
                    border_style="red",
                )
            )
    except Exception as e:
        console.print(Panel(f"[bold red]SSH CLI Error:[/] {e}", border_style="red"))


@ssh_app.command("exec")
def ssh_exec(
    command: str = typer.Argument(..., help="Shell command to execute on remote host."),
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    ),
) -> None:
    """Execute a shell command on the remote EC2 instance."""
    try:
        manager = get_ssh_manager(config)
        result = manager.connect()
        if not result.get("success"):
            console.print(Panel(f"[bold red]Connection failed:[/] {result.get('error')}", border_style="red"))
            return

        exec_result = manager.execute(command)
        manager.disconnect()

        if exec_result.get("success"):
            exit_code = exec_result.get("exit_code")
            color = "green" if exit_code == 0 else "red"
            console.print(f"[bold {color}]Command completed with exit code {exit_code}.[/]")

            if exec_result.get("stdout"):
                console.print(Panel(exec_result.get("stdout"), title="STDOUT", border_style="cyan"))
            if exec_result.get("stderr"):
                console.print(Panel(exec_result.get("stderr"), title="STDERR", border_style="yellow"))
        else:
            console.print(Panel(f"[bold red]Execution error:[/] {exec_result.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]SSH CLI Error:[/] {e}", border_style="red"))


@ssh_app.command("upload")
def ssh_upload(
    local_path: str = typer.Argument(..., help="Path of local file to upload."),
    remote_path: str = typer.Argument(..., help="Destination path on remote host."),
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    ),
) -> None:
    """Upload a local file to the remote EC2 instance."""
    try:
        manager = get_ssh_manager(config)
        result = manager.connect()
        if not result.get("success"):
            console.print(Panel(f"[bold red]Connection failed:[/] {result.get('error')}", border_style="red"))
            return

        upload_result = manager.upload(local_path, remote_path)
        manager.disconnect()

        if upload_result.get("success"):
            console.print(f"[bold green]Successfully uploaded {local_path} to remote path {remote_path}.[/]")
        else:
            console.print(Panel(f"[bold red]Upload failed:[/] {upload_result.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]SSH CLI Error:[/] {e}", border_style="red"))


@ssh_app.command("download")
def ssh_download(
    remote_path: str = typer.Argument(..., help="Path of remote file to download."),
    local_path: str = typer.Argument(..., help="Destination path on local disk."),
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    ),
) -> None:
    """Download a remote file from the remote EC2 instance."""
    try:
        manager = get_ssh_manager(config)
        result = manager.connect()
        if not result.get("success"):
            console.print(Panel(f"[bold red]Connection failed:[/] {result.get('error')}", border_style="red"))
            return

        download_result = manager.download(remote_path, local_path)
        manager.disconnect()

        if download_result.get("success"):
            console.print(f"[bold green]Successfully downloaded remote path {remote_path} to {local_path}.[/]")
        else:
            console.print(Panel(f"[bold red]Download failed:[/] {download_result.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]SSH CLI Error:[/] {e}", border_style="red"))


# --- File Commands ---

@file_app.command("ls")
def file_ls(
    remote_path: str = typer.Argument(..., help="Remote directory path to list."),
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    ),
) -> None:
    """List files and directories in a remote directory."""
    try:
        manager = get_file_manager(config)
        result = manager.remote_list(remote_path)
        if result.get("success"):
            table = Table(title=f"Remote Listing: {remote_path}", show_header=True, header_style="bold magenta")
            table.add_column("Name", style="cyan")
            table.add_column("Type", style="yellow")
            table.add_column("Size (Bytes)", style="green", justify="right")
            table.add_column("Modified Time", style="blue")

            for entry in result.get("entries", []):
                t_type = "DIR" if entry["is_dir"] else "FILE"
                mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(entry["mtime"]))
                table.add_row(entry["name"], t_type, str(entry["size"]), mtime_str)
            console.print(table)
        else:
            console.print(Panel(f"[bold red]List failed:[/] {result.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]File CLI Error:[/] {e}", border_style="red"))


@file_app.command("upload")
def file_upload(
    local: str = typer.Argument(..., help="Local file or directory to upload."),
    remote: str = typer.Argument(..., help="Remote destination path."),
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    ),
) -> None:
    """Upload a file or directory to the remote instance."""
    try:
        manager = get_file_manager(config)
        if os.path.isdir(local):
            result = manager.upload_directory(local, remote)
            title = "Upload Directory"
        else:
            result = manager.upload_file(local, remote)
            title = "Upload File"

        if result.get("success"):
            console.print(
                f"[bold green]Successfully uploaded {local} to {remote} "
                f"({result.get('bytes', 0)} bytes in {result.get('elapsed_seconds', 0.0)}s).[/]"
            )
        else:
            console.print(Panel(f"[bold red]{title} failed:[/] {result.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]File CLI Error:[/] {e}", border_style="red"))


@file_app.command("download")
def file_download(
    remote: str = typer.Argument(..., help="Remote file or directory path to download."),
    local: str = typer.Argument(..., help="Local destination path."),
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    ),
) -> None:
    """Download a file or directory from the remote instance."""
    try:
        manager = get_file_manager(config)
        is_dir = False
        with manager.sftp_session() as sftp:
            resolved = _resolve_remote_path(sftp, remote)
            stat_val = sftp.stat(resolved)
            is_dir = stat_mod.S_ISDIR(stat_val.st_mode)

        if is_dir:
            result = manager.download_directory(remote, local)
            title = "Download Directory"
        else:
            result = manager.download_file(remote, local)
            title = "Download File"

        if result.get("success"):
            console.print(
                f"[bold green]Successfully downloaded {remote} to {local} "
                f"({result.get('bytes', 0)} bytes in {result.get('elapsed_seconds', 0.0)}s).[/]"
            )
        else:
            console.print(Panel(f"[bold red]{title} failed:[/] {result.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]File CLI Error:[/] {e}", border_style="red"))


@file_app.command("mkdir")
def file_mkdir(
    remote_path: str = typer.Argument(..., help="Remote directory path to create."),
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    ),
) -> None:
    """Create a directory on the remote instance."""
    try:
        manager = get_file_manager(config)
        result = manager.remote_mkdir(remote_path, parents=True)
        if result.get("success"):
            console.print(f"[bold green]Successfully created remote directory {remote_path}.[/]")
        else:
            console.print(Panel(f"[bold red]Mkdir failed:[/] {result.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]File CLI Error:[/] {e}", border_style="red"))


@file_app.command("rm")
def file_rm(
    remote_path: str = typer.Argument(..., help="Remote path to delete."),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Recursively delete directory."),
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    ),
) -> None:
    """Delete a file or directory on the remote instance."""
    try:
        manager = get_file_manager(config)
        if recursive:
            result = manager.remote_rmdir(remote_path, recursive=True)
            title = "Rmdir (Recursive)"
        else:
            # Try removing as file first, then fallback to directory
            result = manager.remote_remove(remote_path)
            if not result.get("success"):
                result = manager.remote_rmdir(remote_path, recursive=False)
            title = "Remove"

        if result.get("success"):
            console.print(f"[bold green]Successfully deleted remote path {remote_path}.[/]")
        else:
            console.print(Panel(f"[bold red]{title} failed:[/] {result.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]File CLI Error:[/] {e}", border_style="red"))


@file_app.command("sync")
def file_sync(
    local: str = typer.Argument(..., help="Local file to synchronize."),
    remote: str = typer.Argument(..., help="Remote destination path."),
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    ),
) -> None:
    """Synchronize a local file to the remote host (upload only if size or mtime differs)."""
    try:
        manager = get_file_manager(config)
        result = manager.sync_file(local, remote)
        if result.get("success"):
            if result.get("synced"):
                console.print(f"[bold green]File {local} was out of sync. Uploaded successfully ({result.get('bytes', 0)} bytes).[/]")
            else:
                console.print(f"[bold green]File {local} is already in sync with remote. Skipping transfer.[/]")
        else:
            console.print(Panel(f"[bold red]Sync failed:[/] {result.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]File CLI Error:[/] {e}", border_style="red"))


@file_app.command("verify")
def file_verify(
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    )
) -> None:
    """Perform a complete SFTP transfer verification (upload, list, download, SHA256 match)."""
    import hashlib

    try:
        manager = get_file_manager(config)

        # Create local temp directory
        os.makedirs("temp", exist_ok=True)

        local_test_file = "temp/verify_test.txt"
        local_down_file = "temp/verify_test_down.txt"
        remote_test_file = "~/qrp_verify_test.txt"

        test_content = f"QRP Verification Payload. Timestamp: {time.time()}\n" * 50000  # ~2.5 MB file
        with open(local_test_file, "w", encoding="utf-8") as f:
            f.write(test_content)

        def get_sha256(filepath: str) -> str:
            h = hashlib.sha256()
            with open(filepath, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            return h.hexdigest()

        local_hash = get_sha256(local_test_file)
        file_size = os.path.getsize(local_test_file)

        console.print("[bold yellow]1. Uploading test file...[/]")
        up_res = manager.upload_file(local_test_file, remote_test_file)
        if not up_res.get("success"):
            raise RuntimeError(f"Upload failed: {up_res.get('error')}")

        console.print("[bold yellow]2. Listing remote directory to verify presence...[/]")
        ls_res = manager.remote_list("~")
        found = False
        if ls_res.get("success"):
            for entry in ls_res.get("entries", []):
                if entry["name"] == "qrp_verify_test.txt":
                    found = True
                    break
        if not found:
            raise RuntimeError("Uploaded file 'qrp_verify_test.txt' was not found in remote listing.")

        console.print("[bold yellow]3. Downloading test file back...[/]")
        down_res = manager.download_file(remote_test_file, local_down_file)
        if not down_res.get("success"):
            raise RuntimeError(f"Download failed: {down_res.get('error')}")

        console.print("[bold yellow]4. Checking SHA256 checksums...[/]")
        down_hash = get_sha256(local_down_file)
        sha_match = (local_hash == down_hash)

        # Clean up remote and local
        manager.remote_remove(remote_test_file)
        if os.path.exists(local_test_file):
            os.remove(local_test_file)
        if os.path.exists(local_down_file):
            os.remove(local_down_file)

        # Summary stats
        up_time = up_res.get("elapsed_seconds", 0.0)
        down_time = down_res.get("elapsed_seconds", 0.0)
        total_time = up_time + down_time

        # Speed calculation
        total_bytes = file_size * 2
        speed_kb_s = total_bytes / (total_time * 1024) if total_time > 0 else 0.0

        status_text = "[bold green]PASS[/]" if sha_match else "[bold red]FAIL[/]"

        # Render Rich summary panel
        panel_content = (
            f"• [cyan]Bytes Transferred (Round-Trip):[/] {total_bytes} bytes\n"
            f"• [cyan]Elapsed Time (Round-Trip):[/] {round(total_time, 4)} seconds\n"
            f"• [cyan]Transfer Speed:[/] {round(speed_kb_s, 2)} KB/s\n"
            f"• [cyan]SHA256 Match:[/] {'[green]YES[/]' if sha_match else '[red]NO[/]'}\n\n"
            f"• [bold]Overall Status:[/] {status_text}"
        )

        console.print(
            Panel(
                panel_content,
                title="[magenta]SFTP Transfer Verification Summary[/]",
                border_style="green" if sha_match else "red",
            )
        )

    except Exception as e:
        console.print(Panel(f"[bold red]Verification Failed:[/] {e}", border_style="red"))


# --- Local Git Commands ---

@git_app.command("status")
def git_status() -> None:
    """Show the local Git repository status."""
    try:
        manager = get_local_git_manager()
        res = manager.status()
        if res.get("success"):
            console.print(f"[bold cyan]Branch:[/] {res.get('branch')}")
            if res.get("clean"):
                console.print("[green]Working tree is clean.[/]")
            else:
                if res.get("untracked"):
                    console.print("\n[bold yellow]Untracked files:[/]")
                    for f in res.get("untracked", []):
                        console.print(f"  {f}")
                if res.get("modified"):
                    console.print("\n[bold red]Modified files (unstaged):[/]")
                    for f in res.get("modified", []):
                        console.print(f"  {f}")
                if res.get("staged"):
                    console.print("\n[bold green]Staged changes:[/]")
                    for f in res.get("staged", []):
                        console.print(f"  {f}")
        else:
            console.print(Panel(f"[bold red]Git Status Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


@git_app.command("diff")
def git_diff() -> None:
    """Show local unstaged Git changes."""
    try:
        manager = get_local_git_manager()
        res = manager.diff()
        if res.get("success"):
            diff_text = res.get("diff", "")
            if diff_text:
                console.print(Panel(diff_text, title="Local Git Diff", border_style="cyan"))
            else:
                console.print("[green]No changes to diff.[/]")
        else:
            console.print(Panel(f"[bold red]Git Diff Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


@git_app.command("add")
def git_add(
    paths: Optional[List[str]] = typer.Argument(None, help="Paths to stage. Stages everything if omitted.")
) -> None:
    """Add file contents to the local Git staging index."""
    try:
        manager = get_local_git_manager()
        res = manager.add(paths)
        if res.get("success"):
            console.print(f"[bold green]Successfully staged paths:[/] {res.get('paths')}")
        else:
            console.print(Panel(f"[bold red]Git Add Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


@git_app.command("commit")
def git_commit(
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Commit message.")
) -> None:
    """Record changes to the local Git repository."""
    try:
        manager = get_local_git_manager()
        res = manager.commit(message)
        if res.get("success"):
            if res.get("committed"):
                console.print(
                    f"[bold green]Committed successfully![/]\n"
                    f"Message: {res.get('message')}\n"
                    f"Commit Hash: [cyan]{res.get('commit')}[/]"
                )
            else:
                console.print(f"[yellow]{res.get('message')}[/]")
        else:
            console.print(Panel(f"[bold red]Git Commit Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


@git_app.command("push")
def git_push(
    force: bool = typer.Option(False, "--force", "-f", help="Force push active branch."),
) -> None:
    """Push local active branch commits to GitHub origin."""
    try:
        manager = get_local_git_manager()
        res = manager.push(force=force)
        if res.get("success"):
            console.print(f"[bold green]Successfully pushed branch [cyan]{res.get('branch')}[/].[/]")
        else:
            console.print(Panel(f"[bold red]Git Push Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


@git_app.command("pull")
def git_pull() -> None:
    """Pull origin commits for local active branch."""
    try:
        manager = get_local_git_manager()
        res = manager.pull()
        if res.get("success"):
            console.print(f"[bold green]Successfully pulled changes for branch [cyan]{res.get('branch')}[/].[/]")
        else:
            console.print(Panel(f"[bold red]Git Pull Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


@git_app.command("fetch")
def git_fetch() -> None:
    """Fetch remote Git references locally."""
    try:
        manager = get_local_git_manager()
        res = manager.fetch()
        if res.get("success"):
            console.print("[bold green]Successfully fetched origin references.[/]")
        else:
            console.print(Panel(f"[bold red]Git Fetch Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


@git_app.command("branch")
def git_branch() -> None:
    """List local Git branches."""
    try:
        manager = get_local_git_manager()
        res = manager.branch()
        if res.get("success"):
            for b in res.get("branches", []):
                if b == res.get("current"):
                    console.print(f"[bold green]* {b}[/]")
                else:
                    console.print(f"  {b}")
        else:
            console.print(Panel(f"[bold red]Git Branch Listing Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


@git_app.command("checkout")
def git_checkout(
    branch: str = typer.Argument(..., help="Branch name to switch to.")
) -> None:
    """Switch branches in the local repository."""
    try:
        manager = get_local_git_manager()
        res = manager.checkout(branch)
        if res.get("success"):
            console.print(f"[bold green]Switched to branch [cyan]{res.get('branch')}[/].[/]")
        else:
            console.print(Panel(f"[bold red]Git Checkout Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


# --- Remote Git Commands ---

@git_app.command("remote-status")
def git_remote_status(
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    )
) -> None:
    """Show Git status on the AWS remote EC2 repository."""
    try:
        manager = get_git_manager(config)
        res = manager.remote_status()
        if res.get("success"):
            console.print(f"[bold cyan]Remote Branch:[/] {res.get('branch')}")
            if res.get("clean"):
                console.print("[green]Remote working tree is clean.[/]")
            else:
                if res.get("untracked"):
                    console.print("\n[bold yellow]Untracked files on remote:[/]")
                    for f in res.get("untracked", []):
                        console.print(f"  {f}")
                if res.get("modified"):
                    console.print("\n[bold red]Modified files on remote (unstaged):[/]")
                    for f in res.get("modified", []):
                        console.print(f"  {f}")
                if res.get("staged"):
                    console.print("\n[bold green]Staged changes on remote:[/]")
                    for f in res.get("staged", []):
                        console.print(f"  {f}")
        else:
            console.print(Panel(f"[bold red]Remote Git Status Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


@git_app.command("remote-pull")
def git_remote_pull(
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    )
) -> None:
    """Pull origin changes to the AWS remote repository."""
    try:
        manager = get_git_manager(config)
        res = manager.remote_pull()
        if res.get("success"):
            console.print("[bold green]Successfully pulled remote repository changes.[/]")
            if res.get("stdout"):
                console.print(Panel(res.get("stdout"), title="Git Pull Output", border_style="cyan"))
        else:
            console.print(Panel(f"[bold red]Remote Git Pull Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


@git_app.command("remote-fetch")
def git_remote_fetch(
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    )
) -> None:
    """Fetch remote references on the AWS remote repository."""
    try:
        manager = get_git_manager(config)
        res = manager.remote_fetch()
        if res.get("success"):
            console.print("[bold green]Successfully fetched remote repository references.[/]")
        else:
            console.print(Panel(f"[bold red]Remote Git Fetch Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


@git_app.command("remote-branch")
def git_remote_branch(
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    )
) -> None:
    """List Git branches in the remote AWS repository."""
    try:
        manager = get_git_manager(config)
        res = manager.remote_branch()
        if res.get("success"):
            for b in res.get("branches", []):
                if b == res.get("current"):
                    console.print(f"[bold green]* {b}[/]")
                else:
                    console.print(f"  {b}")
        else:
            console.print(Panel(f"[bold red]Remote Git Branch Listing Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Git CLI Error:[/] {e}", border_style="red"))


@git_app.command("verify-sync")
def git_verify_sync(
    config: str = typer.Option(
        "configs/config.yaml",
        "--config",
        "-c",
        help="Path to the config YAML file.",
    )
) -> None:
    """Verifies branch sync status between local repository and AWS remote repo."""
    try:
        manager = get_git_manager(config)

        console.print("[bold yellow]1. Checking local status...[/]")
        local_status = manager.status()
        if not local_status.get("success"):
            raise RuntimeError(f"Local status failed: {local_status.get('error')}")

        branch = local_status.get("branch")

        console.print("[bold yellow]2. Fetching local HEAD commit...[/]")
        local_commit = manager.current_commit()
        if not local_commit.get("success"):
            raise RuntimeError(f"Local commit fetch failed: {local_commit.get('error')}")

        local_hash = local_commit.get("commit")

        console.print("[bold yellow]3. Pushing local changes to GitHub origin...[/]")
        push_res = manager.push()
        push_status = "SUCCESS" if push_res.get("success") else f"FAILED: {push_res.get('error')}"

        console.print("[bold yellow]4. Pulling remote origin changes on AWS EC2...[/]")
        pull_res = manager.remote_pull()
        pull_status = "SUCCESS" if pull_res.get("success") else f"FAILED: {pull_res.get('error')}"

        console.print("[bold yellow]5. Fetching AWS remote HEAD commit...[/]")
        remote_commit = manager.remote_current_commit()
        if not remote_commit.get("success"):
            raise RuntimeError(f"Remote commit fetch failed: {remote_commit.get('error')}")

        remote_hash = remote_commit.get("commit")

        # Compare HEAD hashes
        hashes_match = (local_hash == remote_hash)
        sync_status = "Synchronized" if hashes_match else "Out of Sync"
        overall_status = "PASS" if hashes_match else "FAIL"

        panel_content = (
            f"• [cyan]Current Branch:[/] {branch}\n"
            f"• [cyan]Local Commit:[/] {local_hash[:10]} ({local_commit.get('message')})\n"
            f"• [cyan]Remote Commit:[/] {remote_hash[:10]} ({remote_commit.get('message')})\n"
            f"• [cyan]Sync Status:[/] {'[green]' if hashes_match else '[red]'}{sync_status}[/]\n"
            f"• [cyan]Push Result:[/] {push_status}\n"
            f"• [cyan]Pull Result:[/] {pull_status}\n\n"
            f"• [bold]Overall Status:[/] {'[bold green]PASS[/]' if hashes_match else '[bold red]FAIL[/]'}"
        )

        console.print(
            Panel(
                panel_content,
                title="[magenta]Local vs AWS Git Sync Verification[/]",
                border_style="green" if hashes_match else "red",
            )
        )

    except Exception as e:
        console.print(Panel(f"[bold red]Sync Verification Failed:[/] {e}", border_style="red"))


# --- Research Commands ---

def get_research_runner(config_path: str = "configs/config.yaml") -> ResearchRunner:
    """Helper to initialize ResearchRunner."""
    return ResearchRunner(config_path)


@research_app.command("run")
def research_run(
    candidate: str = typer.Argument(..., help="Candidate script identifier (e.g. c002)."),
    workers: Optional[int] = typer.Option(None, "--workers", "-w", help="Number of concurrent process workers."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run in simulation mode without executing research."),
    config: str = typer.Option("configs/config.yaml", "--config", "-c", help="Path to config file.")
) -> None:
    """Run an orchestrated quantitative experiment candidate sweep."""
    try:
        runner = get_research_runner(config)
        # Use config workers if not provided
        if workers is None:
            workers = runner.config.get("research.workers", 6)

        console.print(f"[bold yellow]Starting candidate sweep run for {candidate}...[/]")
        res = runner.run_candidate(candidate, workers=workers, dry_run=dry_run)

        # Display summary panel
        success = res.get("success", False)
        status_text = "[bold green]PASS[/]" if success else "[bold red]FAIL[/]"

        panel_content = (
            f"• [cyan]Candidate:[/] {res.get('candidate', candidate)}\n"
            f"• [cyan]Runtime:[/] {res.get('runtime_seconds', 0.0)} seconds\n"
            f"• [cyan]Commit:[/] {res.get('commit', 'N/A')}\n"
            f"• [cyan]Branch:[/] {res.get('branch', 'main')}\n"
            f"• [cyan]Instance:[/] {res.get('instance', 'N/A')}\n"
            f"• [cyan]Workers:[/] {workers}\n"
            f"• [cyan]Downloaded files:[/] {res.get('downloaded_files', 0)}\n"
            f"• [cyan]Research status:[/] {res.get('status', 'FAILED' if not success else 'COMPLETED')}\n\n"
            f"• [bold]Overall Status:[/] {status_text}"
        )
        if not success:
            panel_content += f"\n• [red]Error:[/] {res.get('error', 'Unknown execution error')}"

        console.print(Panel(
            panel_content,
            title="[magenta]Research Sweep Run Summary[/]",
            border_style="green" if success else "red"
        ))

    except Exception as e:
        console.print(Panel(f"[bold red]Research Run CLI Error:[/] {e}", border_style="red"))


@research_app.command("resume")
def research_resume(
    candidate: str = typer.Argument(..., help="Candidate script identifier to resume (e.g. c002)."),
    config: str = typer.Option("configs/config.yaml", "--config", "-c", help="Path to config file.")
) -> None:
    """Resume a paused or interrupted candidate sweep."""
    try:
        runner = get_research_runner(config)
        console.print(f"[bold yellow]Resuming candidate sweep run for {candidate}...[/]")
        res = runner.resume_candidate(candidate)

        success = res.get("success", False)
        status_text = "[bold green]PASS[/]" if success else "[bold red]FAIL[/]"

        panel_content = (
            f"• [cyan]Candidate:[/] {res.get('candidate', candidate)}\n"
            f"• [cyan]Runtime:[/] {res.get('runtime_seconds', 0.0)} seconds\n"
            f"• [cyan]Instance:[/] {res.get('instance', 'N/A')}\n"
            f"• [cyan]Research status:[/] {res.get('status', 'FAILED' if not success else 'COMPLETED')}\n\n"
            f"• [bold]Overall Status:[/] {status_text}"
        )
        if not success:
            panel_content += f"\n• [red]Error:[/] {res.get('error', 'Unknown execution error')}"

        console.print(Panel(
            panel_content,
            title="[magenta]Research Sweep Resume Summary[/]",
            border_style="green" if success else "red"
        ))
    except Exception as e:
        console.print(Panel(f"[bold red]Research Resume CLI Error:[/] {e}", border_style="red"))


@research_app.command("status")
def research_status(
    candidate: str = typer.Argument(..., help="Candidate script identifier (e.g. c002)."),
    config: str = typer.Option("configs/config.yaml", "--config", "-c", help="Path to config file.")
) -> None:
    """Query current run status and metrics of a candidate sweep."""
    try:
        runner = get_research_runner(config)
        res = runner.status(candidate)
        if res.get("success"):
            data = res.get("candidate_data", {})
            table = Table(title=f"Research Status: {candidate}", show_header=True, header_style="bold magenta")
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")

            table.add_row("Name", data.get("name", "N/A"))
            table.add_row("Stage", data.get("stage", "N/A"))

            status_val = data.get("status", "N/A")
            status_style = "green" if status_val == "COMPLETED" else "yellow" if status_val == "RUNNING" else "red"
            table.add_row("Status", f"[{status_style}]{status_val}[/]")

            table.add_row("Progress %", f"{data.get('progress_pct', 0.0)}%")
            table.add_row("Current Experiment", data.get("current_experiment") or "N/A")
            table.add_row("ETA", data.get("eta", "N/A"))
            table.add_row("Current Best Candidate", data.get("current_best_candidate") or "N/A")
            table.add_row("Highest Sharpe Ratio", str(data.get("highest_sharpe", 0.0)))
            table.add_row("Notes/Errors", data.get("notes", "None"))

            console.print(table)
        else:
            console.print(Panel(f"[bold red]Failed to retrieve status:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Research Status CLI Error:[/] {e}", border_style="red"))


@research_app.command("download")
def research_download(
    candidate: str = typer.Argument(..., help="Candidate script identifier (e.g. c002)."),
    config: str = typer.Option("configs/config.yaml", "--config", "-c", help="Path to config file.")
) -> None:
    """Force download the generated reports and outputs for a candidate."""
    try:
        runner = get_research_runner(config)
        console.print(f"[bold yellow]Downloading results for candidate {candidate}...[/]")
        res = runner.download_results(candidate)
        if res.get("success"):
            console.print(
                f"[bold green]Successfully downloaded outputs![/]\n"
                f"Files Count: {res.get('files_count')}\n"
                f"Total Bytes: {res.get('bytes')} bytes\n"
                f"Elapsed: {res.get('elapsed_seconds')}s"
            )
        else:
            console.print(Panel(f"[bold red]Download Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Research Download CLI Error:[/] {e}", border_style="red"))


@research_app.command("cancel")
def research_cancel(
    candidate: str = typer.Argument(..., help="Candidate script identifier to kill (e.g. c002)."),
    config: str = typer.Option("configs/config.yaml", "--config", "-c", help="Path to config file.")
) -> None:
    """Cancel/kill the running sweep script on the remote AWS instance."""
    try:
        runner = get_research_runner(config)
        console.print(f"[bold red]Cancelling remote execution for {candidate}...[/]")
        res = runner.cancel(candidate)
        if res.get("success"):
            console.print(f"[bold green]Kill signal sent. Remote status check complete (elapsed {res.get('elapsed_seconds')}s).[/]")
        else:
            console.print(Panel(f"[bold red]Cancel Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Research Cancel CLI Error:[/] {e}", border_style="red"))


@research_app.command("cleanup")
def research_cleanup(
    candidate: str = typer.Argument(..., help="Candidate script identifier to cleanup (e.g. c002)."),
    config: str = typer.Option("configs/config.yaml", "--config", "-c", help="Path to config file.")
) -> None:
    """Clean checkpoints and remote output reports for a candidate."""
    try:
        runner = get_research_runner(config)
        console.print(f"[bold red]Cleaning up remote outputs and checkpoints for {candidate}...[/]")
        res = runner.cleanup(candidate)
        if res.get("success"):
            console.print(f"[bold green]Cleanup finished successfully on remote (elapsed {res.get('elapsed_seconds')}s).[/]")
        else:
            console.print(Panel(f"[bold red]Cleanup Failed:[/] {res.get('error')}", border_style="red"))
    except Exception as e:
        console.print(Panel(f"[bold red]Research Cleanup CLI Error:[/] {e}", border_style="red"))


if __name__ == "__main__":
    app()
