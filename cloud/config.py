"""Configuration manager for the QRP Cloud Controller.

Handles loading, validating, and retrieving configurations from YAML files.
"""

import os
from typing import Any, Dict
import yaml


class ConfigManager:
    """Manages system and experiment configurations."""

    def __init__(self, config_path: str) -> None:
        """Initialize the ConfigManager.

        Args:
            config_path: Path to the YAML configuration file.
        """
        self.config_path = config_path
        self._config: Dict[str, Any] = {}

    def load(self) -> None:
        """Loads and parses the YAML configuration file.

        Raises:
            FileNotFoundError: If the configuration file does not exist.
            ValueError: If the configuration file is not valid YAML.
        """
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML configuration file: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieves a configuration value. Supports dot-notation for nested keys.

        Args:
            key: Configuration key path, e.g., 'aws.region'.
            default: Default value if the key does not exist.

        Returns:
            The configuration value or default.
        """
        if "." in key:
            parts = key.split(".")
            current: Any = self._config
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return default
            return current
        return self._config.get(key, default)
