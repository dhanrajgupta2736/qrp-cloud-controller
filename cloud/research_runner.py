"""Research experiment execution and orchestration runner.

Coordinates AWS starting/stopping, Git syncing, SSH configuration, SFTP file downloads,
live remote execution log streaming, and verification checks.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.logging import RichHandler

from cloud.config import ConfigManager
from cloud.aws_manager import AWSManager
from cloud.ssh_manager import SSHManager
from cloud.git_manager import GitManager
from cloud.file_manager import FileManager

# Set up Rich logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("research_runner")
console = Console()


class ResearchRunner:
    """Orchestrates remote quantitative experiment lifecycle on AWS EC2."""

    def __init__(self, config_path: str = "configs/config.yaml") -> None:
        """Initialize the ResearchRunner.

        Args:
            config_path: Path to the YAML configuration file.
        """
        self.config_path = config_path
        self.config = ConfigManager(config_path)
        self.config.load()

        # AWS manager initialization
        self.region = self.config.get("aws.region", "ap-south-1")
        self.instance_id = self.config.get("aws.instance_id", "")
        self.aws = AWSManager(region=self.region, instance_id=self.instance_id)

        # SSH credentials and directory paths
        self.ssh_user = self.config.get("aws.ssh_user", "ubuntu")
        self.ssh_key = self.config.get("aws.ssh_key", "")
        self.local_repo = os.path.abspath(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                self.config.get("git.local_path", ".."),
            )
        )
        self.remote_repo = self.config.get("git.remote_path", "~/qrp/crypto-backtester")

        # Connection classes (instantiated lazily)
        self.ssh: Optional[SSHManager] = None
        self.git: Optional[GitManager] = None
        self.file: Optional[FileManager] = None

    def _init_connections(self) -> None:
        """Dynamically queries the EC2 IP and configures connection layers."""
        state_info = self.aws.get_instance_state()
        if not state_info.get("success"):
            raise RuntimeError(f"Failed to query EC2 status: {state_info.get('error')}")

        state = state_info.get("instance_state")
        if state != "running":
            raise RuntimeError(f"EC2 Instance {self.instance_id} is in state '{state}'. It must be 'running'.")

        public_ip = state_info.get("public_ip")
        if not public_ip:
            raise RuntimeError("Running EC2 instance does not have a public IP address.")

        self.ssh = SSHManager(hostname=public_ip, username=self.ssh_user, key_path=self.ssh_key)
        self.git = GitManager(local_path=self.local_repo, ssh_manager=self.ssh, remote_path=self.remote_repo)
        self.file = FileManager(ssh_manager=self.ssh)

    def _resolve_candidate_dir(self, candidate_name: str) -> str:
        """Normalizes candidate names to match directory names."""
        clean = candidate_name.lower().strip()
        if "c002" in clean:
            return "candidate_02_vcp"
        elif "c001" in clean:
            return "candidate_01_relative_strength"
        return clean

    def run_candidate(self, candidate_name: str, workers: int = 6, dry_run: bool = False) -> Dict[str, Any]:
        """Runs a quantitative experiment candidate sweep from start to finish.

        Args:
            candidate_name: The candidate name or ID (e.g. c002).
            workers: Concurrency ProcessPool count.
            dry_run: Simulate the run without executing commands.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        candidate_clean = candidate_name.lower().strip()
        candidate_folder = self._resolve_candidate_dir(candidate_name)

        logger.info(f"Preparing sweep lifecycle for Candidate {candidate_name}...")

        # 1. Environment Verification
        if not os.path.exists(self.config_path):
            return {"success": False, "error": f"Local config file does not exist: {self.config_path}"}

        # Check local repository path
        if not os.path.exists(self.local_repo):
            return {"success": False, "error": f"Local repository path does not exist: {self.local_repo}"}

        if dry_run:
            logger.info("[DRY-RUN] Simulating start/pull/execute/sync pipeline...")
            time.sleep(1)
            return {
                "success": True,
                "candidate": candidate_name,
                "runtime_seconds": 1.25,
                "commit": "simulated-commit-sha",
                "instance": self.instance_id,
                "downloaded_files": 10,
                "status": "COMPLETED (Simulated)",
            }

        try:
            # 2. Check and start EC2
            auto_start = self.config.get("research.auto_start_instance", True)
            state_info = self.aws.get_instance_state()
            if not state_info.get("success"):
                return {"success": False, "error": f"AWS credentials or config check failed: {state_info.get('error')}"}

            current_state = state_info.get("instance_state")
            if current_state != "running":
                if auto_start:
                    logger.info(f"Instance is {current_state}. Auto-starting {self.instance_id}...")
                    self.aws.start_instance()
                    self.aws.wait_until_running()
                else:
                    return {"success": False, "error": f"EC2 Instance is {current_state} and auto-start is disabled."}

            # 3. Connection Init and SSH Check
            self._init_connections()
            conn_res = self.ssh.connect()
            if not conn_res.get("success"):
                return {"success": False, "error": f"SSH connection failed: {conn_res.get('error')}"}

            # 4. Verify Git Synchronization
            verify_git = self.config.get("research.verify_git", True)
            if verify_git:
                logger.info("Synchronizing Git repositories...")
                local_status = self.git.status()
                if local_status.get("success") and not local_status.get("clean"):
                    logger.info("Local changes detected. Auto-committing and pushing...")
                    self.git.add()
                    self.git.commit()
                    self.git.push()
                logger.info("Cleaning remote untracked files to avoid merge conflicts...")
                self.ssh.execute(f"cd {self.remote_repo} && git clean -f -d")
                pull_res = self.git.remote_pull()
                if not pull_res.get("success"):
                    return {"success": False, "error": f"Failed remote pull sync: {pull_res.get('error')}"}

            # 5. Remote Environment Checks
            logger.info("Verifying remote python virtualenv...")
            py_check = self.ssh.execute(f"test -f {self.remote_repo}/venv/bin/python && echo 'venv_ok'")
            if "venv_ok" not in py_check.get("stdout", ""):
                return {
                    "success": False,
                    "error": f"Python virtualenv not found on remote machine at {self.remote_repo}/venv",
                }

            # Resources checks
            disk_check = self.ssh.execute("df -h / | tail -n 1")
            ram_check = self.ssh.execute("free -h | grep Mem")
            logger.info(f"Remote Disk: {disk_check.get('stdout', '').strip()}")
            logger.info(f"Remote RAM: {ram_check.get('stdout', '').strip()}")

            # 6. Execute Research Script
            script_path = f"research_engine/run_sweep_{candidate_clean}.py"
            run_cmd = f"cd {self.remote_repo} && venv/bin/python -u {script_path} --workers {workers}"

            logger.info(f"Launching remote command: {run_cmd}")
            stdin, stdout, stderr = self.ssh.client.exec_command(run_cmd)

            # 7. Live Stream STDOUT
            logger.info("Streaming execution logs back to console:")
            start_run = time.time()
            while True:
                line = stdout.readline()
                if not line:
                    break
                line_str = line.strip()
                # Highlight key logs
                if "Progress:" in line_str or "Saved" in line_str:
                    console.print(f"[bold cyan]\[Remote][/] {line_str}")
                else:
                    console.print(f"[dim gray]\[Remote][/] {line_str}")

            exit_status = stdout.channel.recv_exit_status()
            logger.info(f"Remote process exited with status code: {exit_status}")
            if exit_status != 0:
                return {
                    "success": False,
                    "error": f"Remote research execution failed with exit code {exit_status}.",
                }

            # 9. Download results
            download_ok = False
            files_downloaded = 0
            if self.config.get("research.download_outputs", True):
                logger.info("Downloading reports and outputs generated by the sweep...")

                # Candidate reports and outputs
                remote_candidate_dir = f"{self.remote_repo}/research/{candidate_folder}"
                local_download_dir = f"downloads/{candidate_folder}"

                down_res = self.file.download_directory(
                    remote_dir=remote_candidate_dir,
                    local_dir=local_download_dir,
                    recursive=True,
                )
                if down_res.get("success"):
                    download_ok = True
                    files_downloaded = down_res.get("files_count", 0)
                else:
                    logger.warning(f"Failed downloading outputs: {down_res.get('error')}")

            # 11. Optionally Stop EC2
            auto_stop = self.config.get("research.auto_stop_instance", True)
            if auto_stop:
                logger.info(f"Stopping instance {self.instance_id}...")
                self.aws.stop_instance()

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "candidate": candidate_name,
                "runtime_seconds": round(elapsed, 4),
                "commit": self.git.get_commit_hash() if self.git else "unknown",
                "instance": self.instance_id,
                "downloaded_files": files_downloaded,
                "status": "COMPLETED" if download_ok else "COMPLETED_SYNC_FAILED",
            }

        except Exception as e:
            logger.error(f"Error during run_candidate execution: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if self.ssh:
                self.ssh.disconnect()

    def resume_candidate(self, candidate_name: str) -> Dict[str, Any]:
        """Resumes a candidate sweep by starting execution (loads checkpoint automatically).

        Args:
            candidate_name: Candidate identifier.

        Returns:
            Structured results dictionary.
        """
        # run_sweep scripts natively support checkpoint loading, so we call run_candidate
        workers = self.config.get("research.workers", 6)
        return self.run_candidate(candidate_name, workers=workers)

    def download_results(self, candidate_name: str) -> Dict[str, Any]:
        """Forces downloading the generated research outputs from remote to local downloads folder.

        Args:
            candidate_name: Candidate identifier.

        Returns:
            Structured dictionary.
        """
        candidate_folder = self._resolve_candidate_dir(candidate_name)
        start_time = time.perf_counter()
        try:
            self._init_connections()
            self.ssh.connect()

            remote_dir = f"{self.remote_repo}/research/{candidate_folder}"
            local_dir = f"downloads/{candidate_folder}"

            res = self.file.download_directory(remote_dir, local_dir, recursive=True)
            elapsed = time.perf_counter() - start_time
            if res.get("success"):
                return {
                    "success": True,
                    "operation": "download_results",
                    "files_count": res.get("files_count", 0),
                    "bytes": res.get("bytes", 0),
                    "elapsed_seconds": round(elapsed, 4),
                }
            return {"success": False, "error": res.get("error")}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if self.ssh:
                self.ssh.disconnect()

    def cleanup(self, candidate_name: str) -> Dict[str, Any]:
        """Deletes checkpoints and temporary output files on the remote instance.

        Args:
            candidate_name: Candidate identifier.

        Returns:
            Structured dictionary.
        """
        candidate_folder = self._resolve_candidate_dir(candidate_name)
        candidate_clean = candidate_name.lower().strip()
        start_time = time.perf_counter()
        try:
            self._init_connections()
            self.ssh.connect()

            # Clean checkpoints
            checkpoint_path = f"{self.remote_repo}/research_engine/outputs/checkpoint_sweep_{candidate_clean}.pkl"
            self.file.remote_remove(checkpoint_path)

            # Clean reports and outputs
            remote_outputs = f"{self.remote_repo}/research/{candidate_folder}/outputs"
            remote_reports = f"{self.remote_repo}/research/{candidate_folder}/reports"

            self.file.remote_rmdir(remote_outputs, recursive=True)
            self.file.remote_rmdir(remote_reports, recursive=True)

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "cleanup",
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if self.ssh:
                self.ssh.disconnect()

    def status(self, candidate_name: str) -> Dict[str, Any]:
        """Queries the current run status of a candidate from the remote dashboard file.

        Args:
            candidate_name: Candidate identifier.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            self._init_connections()
            self.ssh.connect()

            # Down state state file
            remote_state_file = f"{self.remote_repo}/research_engine/outputs/dashboard_state.json"
            local_temp_file = "temp/dashboard_state.json"

            down_res = self.file.download_file(remote_state_file, local_temp_file)
            elapsed = time.perf_counter() - start_time
            if down_res.get("success") and os.path.exists(local_temp_file):
                with open(local_temp_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                os.remove(local_temp_file)

                # Search candidate info
                candidates = state.get("candidates", {})
                candidate_folder = self._resolve_candidate_dir(candidate_name)
                candidate_key = "Candidate 02" if "c002" in candidate_name.lower() else "Candidate 01"

                candidate_info = candidates.get(candidate_key)
                if not candidate_info:
                    # Fallback match by key search
                    for k, v in candidates.items():
                        if candidate_name.lower() in k.lower() or candidate_folder in k:
                            candidate_info = v
                            break

                if candidate_info:
                    return {
                        "success": True,
                        "operation": "status",
                        "candidate_data": candidate_info,
                        "elapsed_seconds": round(elapsed, 4),
                    }
                return {
                    "success": False,
                    "error": f"No status data found for candidate {candidate_name}.",
                }
            return {"success": False, "error": down_res.get("error")}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if self.ssh:
                self.ssh.disconnect()

    def cancel(self, candidate_name: str) -> Dict[str, Any]:
        """Cancels/kills the running sweep process on the remote machine.

        Args:
            candidate_name: Candidate identifier.

        Returns:
            Structured dictionary.
        """
        candidate_clean = candidate_name.lower().strip()
        start_time = time.perf_counter()
        try:
            self._init_connections()
            self.ssh.connect()

            # Find and kill the running process
            kill_cmd = f"pkill -f run_sweep_{candidate_clean}.py"
            res = self.ssh.execute(kill_cmd)

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "cancel",
                "exit_code": res.get("exit_code"),
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if self.ssh:
                self.ssh.disconnect()
