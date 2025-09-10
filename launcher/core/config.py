import json
from typing import Optional

from .models import Config

class ConfigManager:
    """Manages the application's configuration state."""

    def __init__(self, config_file: str = "config.json"):
        """Initializes the ConfigManager, loading existing config or creating a new one."""
        self.config_path = config_file
        self.config: Config = self._load()

    def _load(self) -> Config:
        """Loads config from file, or returns a default Config object."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return Config(**data)
        except (FileNotFoundError, json.JSONDecodeError):
            return Config()

    def _save(self):
        """Saves the current config state to the file."""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config.model_dump(), f, indent=4)

    def get_config(self) -> Config:
        """Returns the current configuration object."""
        return self.config

    def update_config(self, **kwargs):
        """
        Updates configuration attributes and saves the changes.
        
        Args:
            **kwargs: The configuration fields to update (e.g., game_path="C:/...").
        """
        updated_fields = self.config.model_copy(update=kwargs)
        if updated_fields != self.config:
            self.config = updated_fields
            self._save()