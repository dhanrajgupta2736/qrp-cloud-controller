"""Bidirectional file and directory synchronization manager.

Coordinates transferring source code, config files, training logs, weights,
and data assets between local and remote environments.
"""

from typing import List


class SyncManager:
    """Synchronizes folders and files between local disk and remote machines."""

    def __init__(self, host: str, user: str, key_path: str) -> None:
        """Initialize SyncManager.

        Args:
            host: Remote hostname or IP address.
            user: Remote username.
            key_path: Path to the SSH private key.
        """
        self.host = host
        self.user = user
        self.key_path = key_path

    def upload(self, local_path: str, remote_path: str, exclusions: List[str] = None) -> None:
        """Uploads files or directories to the remote machine.

        Args:
            local_path: Local source file or directory path.
            remote_path: Remote destination path.
            exclusions: List of file pattern exclusions.
        """
        pass

    def download(self, remote_path: str, local_path: str, exclusions: List[str] = None) -> None:
        """Downloads files or directories from the remote machine.

        Args:
            remote_path: Remote source file or directory path.
            local_path: Local destination path.
            exclusions: List of file pattern exclusions.
        """
        pass
