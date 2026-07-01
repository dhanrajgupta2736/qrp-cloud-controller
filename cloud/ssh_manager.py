"""SSH connection and remote command execution manager.

Establishes secure tunnels, runs shell scripts/commands on remote instances,
and manages file transfers using SFTP.
"""

import logging
import os
import time
from typing import Any, Dict
import paramiko
from rich.logging import RichHandler

# Set up Rich logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("ssh_manager")


def _load_private_key(key_path: str) -> paramiko.PKey:
    """Helper to load different types of SSH keys (Ed25519, RSA, ECDSA).

    Args:
        key_path: Absolute or relative path to the private key.

    Returns:
        Paramiko PKey object.
    """
    expanded_path = os.path.expanduser(key_path)
    if not os.path.exists(expanded_path):
        raise FileNotFoundError(f"SSH private key file not found: {expanded_path}")

    exceptions = []
    # Try different key types
    for key_class in [paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey]:
        try:
            return key_class.from_private_key_file(expanded_path)
        except Exception as e:
            exceptions.append(f"{key_class.__name__}: {e}")

    raise ValueError(
        f"Could not load SSH key {expanded_path}. Attempted key loaders (Ed25519Key, RSAKey, ECDSAKey) failed:\n"
        + "\n".join(exceptions)
    )


class SSHManager:
    """Manages SSH connections and remote process executions."""

    def __init__(
        self,
        hostname: str,
        username: str,
        key_path: str,
        timeout: int = 10,
        retries: int = 5,
        retry_delay: int = 10,
    ) -> None:
        """Initialize SSHManager.

        Args:
            hostname: Public IP or domain name of remote host.
            username: Login user.
            key_path: Path to the private key file.
            timeout: Command and connection timeout in seconds.
            retries: Connection retry count.
            retry_delay: Delay in seconds between connection retries.
        """
        self.hostname = hostname
        self.username = username
        self.key_path = key_path
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self.client = None

    def connect(self) -> Dict[str, Any]:
        """Establishes connection to the remote server with retry logic.

        Returns:
            Structured dictionary.
        """
        logger.info(f"Connecting to remote host {self.hostname} as {self.username}...")

        last_exception = None
        for attempt in range(1, self.retries + 1):
            try:
                pkey = _load_private_key(self.key_path)

                if self.client:
                    self.client.close()

                self.client = paramiko.SSHClient()
                self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                self.client.connect(
                    hostname=self.hostname,
                    username=self.username,
                    pkey=pkey,
                    timeout=self.timeout,
                    allow_agent=False,
                    look_for_keys=False,
                )
                logger.info(f"Successfully connected to {self.hostname} (attempt {attempt}/{self.retries}).")
                return {"success": True}
            except Exception as e:
                last_exception = e
                logger.warning(f"Connection attempt {attempt}/{self.retries} failed: {e}")
                if attempt < self.retries:
                    logger.info(f"Waiting {self.retry_delay}s before retrying...")
                    time.sleep(self.retry_delay)

        err_msg = f"Failed to connect to {self.hostname} after {self.retries} attempts. Last error: {last_exception}"
        logger.error(err_msg)
        return {"success": False, "error": err_msg}

    def disconnect(self) -> Dict[str, Any]:
        """Terminates the active SSH connection.

        Returns:
            Structured dictionary.
        """
        if self.client:
            try:
                self.client.close()
                logger.info("Disconnected SSH connection.")
            except Exception as e:
                logger.warning(f"Error while closing SSH connection: {e}")
            finally:
                self.client = None
        return {"success": True}

    def execute(self, command: str) -> Dict[str, Any]:
        """Executes a command on the remote server.

        Args:
            command: Shell command to run.

        Returns:
            Structured dictionary.
        """
        logger.info(f"Executing remote command: {command}")
        if not self.client:
            return {"success": False, "error": "SSH client is not connected."}
        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=self.timeout)
            exit_status = stdout.channel.recv_exit_status()
            out_content = stdout.read().decode("utf-8", errors="replace")
            err_content = stderr.read().decode("utf-8", errors="replace")

            logger.info(f"Command execution completed with exit code: {exit_status}")
            return {
                "success": True,
                "exit_code": exit_status,
                "stdout": out_content,
                "stderr": err_content,
            }
        except Exception as e:
            err_msg = f"Failed to execute command on {self.hostname}: {e}"
            logger.error(err_msg)
            return {"success": False, "error": err_msg}

    def _get_sftp(self) -> paramiko.SFTPClient:
        """Helper to get SFTP client. Assumes connected client.

        Returns:
            Paramiko SFTPClient object.
        """
        if not self.client:
            raise RuntimeError("SSH client is not connected.")
        return self.client.open_sftp()

    def exists(self, remote_path: str) -> Dict[str, Any]:
        """Checks if a file or directory exists on the remote host.

        Args:
            remote_path: Target path on the remote filesystem.

        Returns:
            Structured dictionary.
        """
        if not self.client:
            return {"success": False, "error": "SSH client is not connected."}
        try:
            sftp = self._get_sftp()
            try:
                sftp.stat(remote_path)
                return {"success": True, "exists": True}
            except FileNotFoundError:
                return {"success": True, "exists": False}
            finally:
                sftp.close()
        except Exception as e:
            err_msg = f"Error checking existence of remote path {remote_path}: {e}"
            logger.error(err_msg)
            return {"success": False, "error": err_msg}

    def mkdir(self, remote_path: str) -> Dict[str, Any]:
        """Creates a directory on the remote host.

        Args:
            remote_path: Directory path to create on the remote filesystem.

        Returns:
            Structured dictionary.
        """
        if not self.client:
            return {"success": False, "error": "SSH client is not connected."}
        try:
            sftp = self._get_sftp()
            try:
                sftp.mkdir(remote_path)
                logger.info(f"Created remote directory: {remote_path}")
                return {"success": True}
            finally:
                sftp.close()
        except Exception as e:
            err_msg = f"Failed to create remote directory {remote_path}: {e}"
            logger.error(err_msg)
            return {"success": False, "error": err_msg}

    def upload(self, local_path: str, remote_path: str) -> Dict[str, Any]:
        """Uploads a file to the remote host.

        Args:
            local_path: Source path on local disk.
            remote_path: Target destination path on the remote host.

        Returns:
            Structured dictionary.
        """
        if not self.client:
            return {"success": False, "error": "SSH client is not connected."}
        if not os.path.exists(local_path):
            return {"success": False, "error": f"Local file does not exist: {local_path}"}
        try:
            sftp = self._get_sftp()
            try:
                logger.info(f"Uploading local file {local_path} to remote {remote_path}...")
                sftp.put(local_path, remote_path)
                logger.info("Upload completed successfully.")
                return {"success": True}
            finally:
                sftp.close()
        except Exception as e:
            err_msg = f"Failed to upload {local_path} to {remote_path}: {e}"
            logger.error(err_msg)
            return {"success": False, "error": err_msg}

    def download(self, remote_path: str, local_path: str) -> Dict[str, Any]:
        """Downloads a file from the remote host.

        Args:
            remote_path: Source path on the remote host.
            local_path: Target destination path on local disk.

        Returns:
            Structured dictionary.
        """
        if not self.client:
            return {"success": False, "error": "SSH client is not connected."}
        try:
            sftp = self._get_sftp()
            try:
                logger.info(f"Downloading remote file {remote_path} to local {local_path}...")
                local_dir = os.path.dirname(os.path.abspath(local_path))
                if not os.path.exists(local_dir):
                    os.makedirs(local_dir, exist_ok=True)
                sftp.get(remote_path, local_path)
                logger.info("Download completed successfully.")
                return {"success": True}
            finally:
                sftp.close()
        except Exception as e:
            err_msg = f"Failed to download {remote_path} to {local_path}: {e}"
            logger.error(err_msg)
            return {"success": False, "error": err_msg}
