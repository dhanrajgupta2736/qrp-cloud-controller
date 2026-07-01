"""Git automation manager for local and remote repositories.

Handles staging, committing, pushing, pulling, checking out branches,
and querying status/commit hashes for both local and remote (AWS EC2) repositories.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional
import git
from rich.logging import RichHandler
from cloud.ssh_manager import SSHManager

# Set up Rich logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("git_manager")


class GitManager:
    """Manages local and remote Git repositories and synchronizations."""

    def __init__(
        self,
        local_path: Optional[str] = None,
        ssh_manager: Optional[SSHManager] = None,
        remote_path: str = "~/qrp-cloud-controller",
    ) -> None:
        """Initialize GitManager.

        Args:
            local_path: Path to the local git repository (defaults to project root).
            ssh_manager: SSHManager instance for remote repository automation.
            remote_path: Destination path of the repository on the remote host.
        """
        if local_path is None:
            # Resolve to the root folder of the qrp-cloud-controller project
            local_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.local_path = local_path
        self.ssh = ssh_manager
        self.remote_path = remote_path

    # --- Backward Compatibility Helpers ---

    def clone_or_pull(self, dest_path: str) -> None:
        """Deprecated: Wrapper for compatibility. Clones or pulls remote repo."""
        self._ensure_remote_repo()

    def get_commit_hash(self) -> str:
        """Deprecated: Wrapper for compatibility. Returns local head commit hash."""
        res = self.current_commit()
        return res.get("commit", "placeholder-hash")

    def get_status(self) -> Dict[str, Any]:
        """Deprecated: Wrapper for compatibility. Gets local status."""
        return self.status()

    # --- Helper Method ---

    def _ensure_remote_repo(self) -> None:
        """Verifies remote directory is a git repository. If not, clones from local remote origin."""
        if not self.ssh:
            raise RuntimeError("SSHManager is not initialized for remote Git operations.")

        # Check if remote .git directory exists
        res = self.ssh.execute(f"test -d {self.remote_path}/.git && echo 'exists'")
        if "exists" not in res.get("stdout", ""):
            # Find local origin URL to clone
            try:
                local_repo = git.Repo(self.local_path)
                origin_url = local_repo.remotes.origin.url
            except Exception as e:
                raise RuntimeError(f"Failed to query local remote URL to clone remote repository: {e}")

            logger.info(f"Remote path {self.remote_path}/.git not found. Cloning repository from {origin_url}...")
            clone_cmd = f"git clone {origin_url} {self.remote_path}"
            clone_res = self.ssh.execute(clone_cmd)
            if not clone_res.get("success") or clone_res.get("exit_code") != 0:
                raise RuntimeError(
                    f"Failed to clone remote repository: {clone_res.get('error') or clone_res.get('stderr')}"
                )

    # --- Local Git APIs ---

    def status(self) -> Dict[str, Any]:
        """Queries local repository branch, clean state, untracked, modified, and staged changes.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            repo = git.Repo(self.local_path)
            try:
                branch = repo.active_branch.name
            except TypeError:
                branch = "DETACHED"

            clean = not repo.is_dirty(untracked_files=True)
            untracked = repo.untracked_files
            modified = [item.a_path for item in repo.index.diff(None)]

            try:
                staged = [item.a_path for item in repo.index.diff("HEAD")]
            except (git.exc.BadName, ValueError):
                # Handle empty/initial repository commits
                staged = []

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "status",
                "branch": branch,
                "clean": clean,
                "untracked": untracked,
                "modified": modified,
                "staged": staged,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Local git status query failed: {e}")
            return {
                "success": False,
                "operation": "status",
                "error": str(e),
            }

    def diff(self) -> Dict[str, Any]:
        """Gets unstaged local git diff stdout.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            repo = git.Repo(self.local_path)
            diff_text = repo.git.diff()
            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "diff",
                "diff": diff_text,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Local git diff failed: {e}")
            return {
                "success": False,
                "operation": "diff",
                "error": str(e),
            }

    def branch(self) -> Dict[str, Any]:
        """Lists local branches and identifies active one.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            repo = git.Repo(self.local_path)
            branches = [b.name for b in repo.branches]
            try:
                current = repo.active_branch.name
            except TypeError:
                current = "DETACHED"

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "branch",
                "current": current,
                "branches": branches,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Local git branch listing failed: {e}")
            return {
                "success": False,
                "operation": "branch",
                "error": str(e),
            }

    def checkout(self, branch: str) -> Dict[str, Any]:
        """Checks out a local branch.

        Args:
            branch: Branch name to checkout.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            repo = git.Repo(self.local_path)
            repo.git.checkout(branch)
            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "checkout",
                "branch": branch,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Local checkout of branch '{branch}' failed: {e}")
            return {
                "success": False,
                "operation": "checkout",
                "error": str(e),
            }

    def add(self, paths: Optional[List[str]] = None) -> Dict[str, Any] :
        """Stages files in the local repository index.

        Args:
            paths: List of relative files/directories to stage (stages all '.' if None).

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            repo = git.Repo(self.local_path)
            if paths is None:
                repo.git.add(".")
            else:
                for path in paths:
                    repo.git.add(path)
            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "add",
                "paths": paths or ["."],
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Local git add failed: {e}")
            return {
                "success": False,
                "operation": "add",
                "error": str(e),
            }

    def commit(self, message: Optional[str] = None) -> Dict[str, Any]:
        """Commits staged changes in the local repository. Auto-generates message if omitted.

        Args:
            message: Custom commit message.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            repo = git.Repo(self.local_path)

            # Check if there are staged changes to commit
            try:
                staged = repo.index.diff("HEAD")
            except (git.exc.BadName, ValueError):
                # Handle initial commit check
                staged = len(repo.index.entries) > 0

            if not staged:
                elapsed = time.perf_counter() - start_time
                return {
                    "success": True,
                    "operation": "commit",
                    "committed": False,
                    "message": "Nothing to commit.",
                    "elapsed_seconds": round(elapsed, 4),
                }

            # Auto-generate commit message if omitted
            if not message:
                try:
                    diff_items = repo.index.diff("HEAD")
                except (git.exc.BadName, ValueError):
                    diff_items = []
                modified_paths = [item.a_path for item in diff_items]

                has_cloud = any(p.startswith("cloud/") for p in modified_paths)
                has_config = any(p.startswith("configs/") for p in modified_paths)
                has_docs = any(p.startswith("reports/") or p == "README.md" for p in modified_paths)

                if has_cloud:
                    message = "Update cloud controller"
                elif has_config:
                    message = "Update configurations"
                elif has_docs:
                    message = "Documentation updates"
                else:
                    message = "Update research framework"

            commit_obj = repo.index.commit(message)
            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "commit",
                "committed": True,
                "message": message,
                "commit": commit_obj.hexsha,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Local git commit failed: {e}")
            return {
                "success": False,
                "operation": "commit",
                "error": str(e),
            }

    def push(self, force: bool = False) -> Dict[str, Any]:
        """Pushes active branch to remote host origin. Supports non-force safety checks.

        Args:
            force: Force push branch if True.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            repo = git.Repo(self.local_path)
            branch_name = repo.active_branch.name
            if force:
                logger.warning(f"Force pushing local branch '{branch_name}' to remote origin...")
                repo.git.push("origin", branch_name, force=True)
            else:
                logger.info(f"Pushing local branch '{branch_name}' to remote origin...")
                repo.git.push("origin", branch_name)

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "push",
                "branch": branch_name,
                "force": force,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Local git push failed: {e}")
            return {
                "success": False,
                "operation": "push",
                "error": str(e),
            }

    def pull(self) -> Dict[str, Any]:
        """Pulls from origin for the active branch.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            repo = git.Repo(self.local_path)
            branch_name = repo.active_branch.name
            repo.git.pull("origin", branch_name)
            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "pull",
                "branch": branch_name,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Local git pull failed: {e}")
            return {
                "success": False,
                "operation": "pull",
                "error": str(e),
            }

    def fetch(self) -> Dict[str, Any]:
        """Fetches metadata from remote origin.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            repo = git.Repo(self.local_path)
            repo.git.fetch("origin")
            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "fetch",
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Local git fetch failed: {e}")
            return {
                "success": False,
                "operation": "fetch",
                "error": str(e),
            }

    def current_commit(self) -> Dict[str, Any]:
        """Returns the local HEAD commit hash and short message.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            repo = git.Repo(self.local_path)
            commit_obj = repo.head.commit
            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "current_commit",
                "commit": commit_obj.hexsha,
                "message": commit_obj.message.strip(),
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Failed to query local HEAD commit: {e}")
            return {
                "success": False,
                "operation": "current_commit",
                "error": str(e),
            }

    # --- Remote Git APIs ---

    def remote_status(self) -> Dict[str, Any]:
        """Queries remote repository branch and staged/modified/untracked files.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            self._ensure_remote_repo()
            cmd = f"cd {self.remote_path} && git status --porcelain -b"
            res = self.ssh.execute(cmd)
            if not res.get("success") or res.get("exit_code") != 0:
                raise RuntimeError(res.get("stderr") or res.get("error") or "Unknown remote git error.")

            lines = res.get("stdout", "").strip().splitlines()
            branch = "unknown"
            clean = True
            untracked = []
            modified = []
            staged = []

            if lines:
                header = lines[0]
                if header.startswith("## "):
                    branch_part = header[3:]
                    branch = branch_part.split("...")[0] if "..." in branch_part else branch_part.strip()

                for line in lines[1:]:
                    if len(line) < 3:
                        continue
                    status_code = line[:2]
                    filepath = line[3:].strip()
                    clean = False
                    if status_code == "??":
                        untracked.append(filepath)
                    elif status_code[1] == "M":
                        modified.append(filepath)
                    elif status_code[0] in ["M", "A", "D"]:
                        staged.append(filepath)

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "remote_status",
                "branch": branch,
                "clean": clean,
                "untracked": untracked,
                "modified": modified,
                "staged": staged,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Remote git status query failed: {e}")
            return {
                "success": False,
                "operation": "remote_status",
                "error": str(e),
            }

    def remote_pull(self) -> Dict[str, Any]:
        """Executes a git pull command on the remote host.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            self._ensure_remote_repo()
            res = self.ssh.execute(f"cd {self.remote_path} && git pull")
            if not res.get("success") or res.get("exit_code") != 0:
                raise RuntimeError(res.get("stderr") or res.get("error") or "Unknown pull error.")

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "remote_pull",
                "stdout": res.get("stdout", "").strip(),
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Remote git pull failed: {e}")
            return {
                "success": False,
                "operation": "remote_pull",
                "error": str(e),
            }

    def remote_fetch(self) -> Dict[str, Any]:
        """Executes a git fetch command on the remote host.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            self._ensure_remote_repo()
            res = self.ssh.execute(f"cd {self.remote_path} && git fetch")
            if not res.get("success") or res.get("exit_code") != 0:
                raise RuntimeError(res.get("stderr") or res.get("error") or "Unknown fetch error.")

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "remote_fetch",
                "stdout": res.get("stdout", "").strip(),
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Remote git fetch failed: {e}")
            return {
                "success": False,
                "operation": "remote_fetch",
                "error": str(e),
            }

    def remote_branch(self) -> Dict[str, Any]:
        """Lists remote branches and identifies active remote branch.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            self._ensure_remote_repo()
            res = self.ssh.execute(f"cd {self.remote_path} && git branch")
            if not res.get("success") or res.get("exit_code") != 0:
                raise RuntimeError(res.get("stderr") or res.get("error") or "Unknown branch listing error.")

            lines = res.get("stdout", "").strip().splitlines()
            branches = []
            current = "unknown"
            for line in lines:
                clean_line = line.strip()
                if clean_line.startswith("*"):
                    current = clean_line[1:].strip()
                    branches.append(current)
                else:
                    branches.append(clean_line)

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "remote_branch",
                "current": current,
                "branches": branches,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Remote git branch listing failed: {e}")
            return {
                "success": False,
                "operation": "remote_branch",
                "error": str(e),
            }

    def remote_checkout(self, branch: str) -> Dict[str, Any]:
        """Switches target branch on the remote host.

        Args:
            branch: Target branch name.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            self._ensure_remote_repo()
            res = self.ssh.execute(f"cd {self.remote_path} && git checkout {branch}")
            if not res.get("success") or res.get("exit_code") != 0:
                raise RuntimeError(res.get("stderr") or res.get("error") or f"Failed to checkout remote branch {branch}.")

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "remote_checkout",
                "branch": branch,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Remote git checkout of '{branch}' failed: {e}")
            return {
                "success": False,
                "operation": "remote_checkout",
                "error": str(e),
            }

    def remote_current_commit(self) -> Dict[str, Any]:
        """Returns the remote HEAD commit hash and short message.

        Returns:
            Structured dictionary.
        """
        start_time = time.perf_counter()
        try:
            self._ensure_remote_repo()
            res = self.ssh.execute(f"cd {self.remote_path} && git log -1 --format=\"%H%n%s\"")
            if not res.get("success") or res.get("exit_code") != 0:
                raise RuntimeError(res.get("stderr") or res.get("error") or "Failed to read remote commit.")

            parts = res.get("stdout", "").strip().split("\n", 1)
            commit_hash = parts[0].strip() if parts else "unknown"
            message = parts[1].strip() if len(parts) > 1 else ""

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "remote_current_commit",
                "commit": commit_hash,
                "message": message,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Remote current commit query failed: {e}")
            return {
                "success": False,
                "operation": "remote_current_commit",
                "error": str(e),
            }

    def remote_commit_hash(self) -> str:
        """Utility helper to get remote HEAD commit hash directly.

        Returns:
            SHA commit hash string or 'unknown'.
        """
        try:
            self._ensure_remote_repo()
            res = self.ssh.execute(f"cd {self.remote_path} && git rev-parse HEAD")
            if res.get("success") and res.get("exit_code") == 0:
                return res.get("stdout", "").strip()
        except Exception:
            pass
        return "unknown"
