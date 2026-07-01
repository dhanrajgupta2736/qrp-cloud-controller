"""SFTP and remote file/directory management subsystem.

Handles bidirectional file transfers, directory creation/deletion, checks,
and timestamp preservation using Paramiko SFTP.
"""

from contextlib import contextmanager
import logging
import os
import stat as stat_mod
import time
from typing import Any, Dict, Generator, List, Tuple
import paramiko
from rich.logging import RichHandler
from cloud.ssh_manager import SSHManager

# Set up Rich logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("file_manager")


def _resolve_remote_path(sftp: paramiko.SFTPClient, path: str) -> str:
    """Helper to resolve home directory shortcuts (~) in remote SFTP paths.

    Args:
        sftp: Live SFTPClient session.
        path: Path string to resolve.

    Returns:
        Resolved absolute path.
    """
    path_str = str(path)
    if path_str.startswith("~"):
        home = sftp.normalize(".")
        path_str = path_str.replace("~", home, 1)
    return path_str.replace("\\", "/")


def _remote_mkdir_recursive(sftp: paramiko.SFTPClient, remote_path: str) -> None:
    """Recursively creates directory folders on the remote machine if missing.

    Args:
        sftp: Live SFTPClient session.
        remote_path: Target directory path to create.
    """
    resolved = _resolve_remote_path(sftp, remote_path)
    parts = resolved.split("/")
    current = ""
    if parts[0] == "":  # Absolute path
        current = "/"
        parts = parts[1:]

    for part in parts:
        if not part:
            continue
        current = f"{current.rstrip('/')}/{part}"
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


def _remote_rmtree(sftp: paramiko.SFTPClient, remote_path: str) -> None:
    """Recursively deletes a directory tree on the remote host.

    Args:
        sftp: Live SFTPClient session.
        remote_path: Absolute remote path of directory to delete.
    """
    resolved = _resolve_remote_path(sftp, remote_path)
    for entry in sftp.listdir_attr(resolved):
        entry_path = f"{resolved.rstrip('/')}/{entry.filename}"
        if stat_mod.S_ISDIR(entry.st_mode):
            _remote_rmtree(sftp, entry_path)
        else:
            sftp.remove(entry_path)
    sftp.rmdir(resolved)


class FileManager:
    """Coordinates SFTP file and directory operations over an SSHManager session."""

    def __init__(self, ssh_manager: SSHManager) -> None:
        """Initialize the FileManager with a configured SSHManager.

        Args:
            ssh_manager: The active SSHManager instance.
        """
        self.ssh = ssh_manager

    @contextmanager
    def sftp_session(self) -> Generator[paramiko.SFTPClient, None, None]:
        """Safely opens, optimizes, and closes an SFTP channel.

        Yields:
            An optimized Paramiko SFTPClient instance.
        """
        if not self.ssh.client:
            connect_res = self.ssh.connect()
            if not connect_res.get("success"):
                raise RuntimeError(f"Failed to connect SSH client: {connect_res.get('error')}")

        transport = self.ssh.client.get_transport()
        if transport:
            # Optimize window size for fast file transfer speeds
            transport.window_size = 4294967294

        sftp = self.ssh.client.open_sftp()
        try:
            yield sftp
        finally:
            sftp.close()

    def upload_file(self, local_path: str, remote_path: str) -> Dict[str, Any]:
        """Uploads a single local file to a remote path, preserving timestamp.

        Args:
            local_path: Source file on local disk.
            remote_path: Target path on remote host.

        Returns:
            Structured dictionary results.
        """
        start_time = time.perf_counter()
        if not os.path.exists(local_path):
            return {
                "success": False,
                "operation": "upload_file",
                "error": f"Local file does not exist: {local_path}",
            }

        try:
            file_size = os.path.getsize(local_path)
            local_stat = os.stat(local_path)

            with self.sftp_session() as sftp:
                resolved_remote = _resolve_remote_path(sftp, remote_path)

                # Auto-create missing remote parent directories
                remote_dir = os.path.dirname(resolved_remote)
                if remote_dir:
                    _remote_mkdir_recursive(sftp, remote_dir)

                # Perform sftp upload
                logger.info(f"SFTP Put: {local_path} -> {resolved_remote} ({file_size} bytes)")
                sftp.put(local_path, resolved_remote)

                # Preserve timestamps (mtime)
                sftp.utime(resolved_remote, (int(local_stat.st_atime), int(local_stat.st_mtime)))

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "upload_file",
                "source": local_path,
                "destination": remote_path,
                "bytes": file_size,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Failed to upload file {local_path} to {remote_path}: {e}")
            return {
                "success": False,
                "operation": "upload_file",
                "error": str(e),
            }

    def download_file(self, remote_path: str, local_path: str) -> Dict[str, Any]:
        """Downloads a single remote file to local disk, preserving timestamp.

        Args:
            remote_path: Source file on remote machine.
            local_path: Target path on local disk.

        Returns:
            Structured dictionary results.
        """
        start_time = time.perf_counter()
        try:
            # Auto-create missing local parent directories
            local_dir = os.path.dirname(os.path.abspath(local_path))
            if local_dir:
                os.makedirs(local_dir, exist_ok=True)

            file_size = 0
            with self.sftp_session() as sftp:
                resolved_remote = _resolve_remote_path(sftp, remote_path)
                remote_stat = sftp.stat(resolved_remote)
                file_size = remote_stat.st_size

                # Perform download
                logger.info(f"SFTP Get: {resolved_remote} -> {local_path} ({file_size} bytes)")
                sftp.get(resolved_remote, local_path)

                # Preserve timestamps (mtime)
                os.utime(local_path, (int(remote_stat.st_atime), int(remote_stat.st_mtime)))

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "download_file",
                "source": remote_path,
                "destination": local_path,
                "bytes": file_size,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Failed to download remote file {remote_path} to {local_path}: {e}")
            return {
                "success": False,
                "operation": "download_file",
                "error": str(e),
            }

    def upload_directory(self, local_dir: str, remote_dir: str, recursive: bool = True) -> Dict[str, Any]:
        """Uploads a local directory tree to remote host.

        Args:
            local_dir: Source directory.
            remote_dir: Remote target destination.
            recursive: True to upload subdirectories.

        Returns:
            Structured dictionary results.
        """
        start_time = time.perf_counter()
        if not os.path.isdir(local_dir):
            return {
                "success": False,
                "operation": "upload_directory",
                "error": f"Local path is not a directory: {local_dir}",
            }

        total_bytes = 0
        files_count = 0
        try:
            with self.sftp_session() as sftp:
                resolved_remote = _resolve_remote_path(sftp, remote_dir)
                _remote_mkdir_recursive(sftp, resolved_remote)

                for root, dirs, files in os.walk(local_dir):
                    # Compute relative directory structure
                    rel_dir = os.path.relpath(root, local_dir)
                    if rel_dir == ".":
                        current_remote_dir = resolved_remote
                    else:
                        if not recursive:
                            continue
                        rel_dir_clean = rel_dir.replace("\\", "/")
                        current_remote_dir = f"{resolved_remote.rstrip('/')}/{rel_dir_clean}"

                    _remote_mkdir_recursive(sftp, current_remote_dir)

                    for file in files:
                        local_filepath = os.path.join(root, file)
                        remote_filepath = f"{current_remote_dir.rstrip('/')}/{file}"
                        file_size = os.path.getsize(local_filepath)
                        local_stat = os.stat(local_filepath)

                        logger.info(f"SFTP Dir Put: {local_filepath} -> {remote_filepath}")
                        sftp.put(local_filepath, remote_filepath)
                        sftp.utime(remote_filepath, (int(local_stat.st_atime), int(local_stat.st_mtime)))

                        total_bytes += file_size
                        files_count += 1

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "upload_directory",
                "source": local_dir,
                "destination": remote_dir,
                "bytes": total_bytes,
                "files_count": files_count,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Failed to upload directory {local_dir} to {remote_dir}: {e}")
            return {
                "success": False,
                "operation": "upload_directory",
                "error": str(e),
            }

    def download_directory(self, remote_dir: str, local_dir: str, recursive: bool = True) -> Dict[str, Any]:
        """Downloads a remote directory tree to local disk.

        Args:
            remote_dir: Remote source directory.
            local_dir: Local target destination.
            recursive: True to download subdirectories.

        Returns:
            Structured dictionary results.
        """
        start_time = time.perf_counter()
        total_bytes = 0
        files_count = 0

        def _download_recursive(sftp: paramiko.SFTPClient, r_dir: str, l_dir: str) -> Tuple[int, int]:
            nonlocal recursive
            os.makedirs(l_dir, exist_ok=True)
            bytes_sum = 0
            count_sum = 0

            for entry in sftp.listdir_attr(r_dir):
                r_path = f"{r_dir.rstrip('/')}/{entry.filename}"
                l_path = os.path.join(l_dir, entry.filename)

                if stat_mod.S_ISDIR(entry.st_mode):
                    if recursive:
                        b, c = _download_recursive(sftp, r_path, l_path)
                        bytes_sum += b
                        count_sum += c
                else:
                    logger.info(f"SFTP Dir Get: {r_path} -> {l_path}")
                    sftp.get(r_path, l_path)
                    os.utime(l_path, (int(entry.st_atime), int(entry.st_mtime)))
                    bytes_sum += entry.st_size
                    count_sum += 1

            return bytes_sum, count_sum

        try:
            with self.sftp_session() as sftp:
                resolved_remote = _resolve_remote_path(sftp, remote_dir)
                # Check that source exists and is directory
                stat_val = sftp.stat(resolved_remote)
                if not stat_mod.S_ISDIR(stat_val.st_mode):
                    return {
                        "success": False,
                        "operation": "download_directory",
                        "error": f"Remote source is not a directory: {remote_dir}",
                    }

                total_bytes, files_count = _download_recursive(sftp, resolved_remote, local_dir)

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "download_directory",
                "source": remote_dir,
                "destination": local_dir,
                "bytes": total_bytes,
                "files_count": files_count,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Failed to download remote directory {remote_dir} to {local_dir}: {e}")
            return {
                "success": False,
                "operation": "download_directory",
                "error": str(e),
            }

    def remote_exists(self, path: str) -> Dict[str, Any]:
        """Checks if a file or directory exists on the remote machine.

        Args:
            path: Target path on the remote host.

        Returns:
            Structured dictionary.
        """
        try:
            with self.sftp_session() as sftp:
                resolved = _resolve_remote_path(sftp, path)
                try:
                    sftp.stat(resolved)
                    return {"success": True, "exists": True}
                except FileNotFoundError:
                    return {"success": True, "exists": False}
        except Exception as e:
            logger.error(f"Error checking remote existence of {path}: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def remote_mkdir(self, path: str, parents: bool = True) -> Dict[str, Any]:
        """Creates a directory on the remote machine.

        Args:
            path: Remote path to create.
            parents: True to create missing parent folders.

        Returns:
            Structured dictionary results.
        """
        start_time = time.perf_counter()
        try:
            with self.sftp_session() as sftp:
                resolved = _resolve_remote_path(sftp, path)
                if parents:
                    _remote_mkdir_recursive(sftp, resolved)
                else:
                    sftp.mkdir(resolved)

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "mkdir",
                "destination": path,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Failed to create remote directory {path}: {e}")
            return {
                "success": False,
                "operation": "mkdir",
                "error": str(e),
            }

    def remote_list(self, path: str) -> Dict[str, Any]:
        """Lists entries in a remote directory with meta info.

        Args:
            path: Remote path of the directory.

        Returns:
            Structured dictionary with entries.
        """
        start_time = time.perf_counter()
        try:
            entries = []
            with self.sftp_session() as sftp:
                resolved = _resolve_remote_path(sftp, path)
                for entry in sftp.listdir_attr(resolved):
                    entries.append(
                        {
                            "name": entry.filename,
                            "is_dir": stat_mod.S_ISDIR(entry.st_mode),
                            "size": entry.st_size,
                            "mtime": entry.st_mtime,
                        }
                    )

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "list",
                "source": path,
                "entries": entries,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Failed to list remote directory {path}: {e}")
            return {
                "success": False,
                "operation": "list",
                "error": str(e),
            }

    def remote_remove(self, path: str) -> Dict[str, Any]:
        """Deletes a single file on the remote host.

        Args:
            path: Remote path of file to remove.

        Returns:
            Structured dictionary results.
        """
        start_time = time.perf_counter()
        try:
            with self.sftp_session() as sftp:
                resolved = _resolve_remote_path(sftp, path)
                sftp.remove(resolved)

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "remove",
                "destination": path,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Failed to remove remote file {path}: {e}")
            return {
                "success": False,
                "operation": "remove",
                "error": str(e),
            }

    def remote_rmdir(self, path: str, recursive: bool = False) -> Dict[str, Any]:
        """Removes a directory on the remote machine.

        Args:
            path: Remote path of directory to delete.
            recursive: True to recursively delete subdirectories.

        Returns:
            Structured dictionary results.
        """
        start_time = time.perf_counter()
        try:
            with self.sftp_session() as sftp:
                resolved = _resolve_remote_path(sftp, path)
                if recursive:
                    _remote_rmtree(sftp, resolved)
                else:
                    sftp.rmdir(resolved)

            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "rmdir",
                "destination": path,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Failed to remove remote directory {path}: {e}")
            return {
                "success": False,
                "operation": "rmdir",
                "error": str(e),
            }

    def sync_file(self, local_path: str, remote_path: str) -> Dict[str, Any]:
        """Uploads local file only if size or mtime differs from remote.

        Args:
            local_path: Source file on local disk.
            remote_path: Target path on remote host.

        Returns:
            Structured dictionary results with synced boolean.
        """
        start_time = time.perf_counter()
        if not os.path.exists(local_path):
            return {
                "success": False,
                "operation": "sync_file",
                "error": f"Local file does not exist: {local_path}",
            }

        try:
            local_stat = os.stat(local_path)
            local_size = local_stat.st_size
            local_mtime = int(local_stat.st_mtime)

            should_upload = False
            with self.sftp_session() as sftp:
                resolved_remote = _resolve_remote_path(sftp, remote_path)
                try:
                    remote_stat = sftp.stat(resolved_remote)
                    remote_size = remote_stat.st_size
                    remote_mtime = int(remote_stat.st_mtime)

                    # Sync if size or mtime differ
                    if remote_size != local_size or remote_mtime != local_mtime:
                        should_upload = True
                except FileNotFoundError:
                    # Upload if remote file doesn't exist
                    should_upload = True

            if should_upload:
                logger.info(f"Sync: File {local_path} differs or is missing. Uploading...")
                res = self.upload_file(local_path, remote_path)
                if res.get("success"):
                    res["operation"] = "sync_file"
                    res["synced"] = True
                return res

            logger.info(f"Sync: File {local_path} matches remote file. Skipping upload.")
            elapsed = time.perf_counter() - start_time
            return {
                "success": True,
                "operation": "sync_file",
                "source": local_path,
                "destination": remote_path,
                "bytes": 0,
                "synced": False,
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as e:
            logger.error(f"Failed to sync file {local_path} with {remote_path}: {e}")
            return {
                "success": False,
                "operation": "sync_file",
                "error": str(e),
            }
