"""
ConfigManager - Loads and saves app configuration from config.json
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULTS = {
    "app_title": "InfoHub File Manager",
    "app_port": 8500,
    "log_level": "INFO",
    "log_file": "infohub.log",
    "anythingllm_api_key": "",
    "anythingllm_base_url": "http://localhost:3000",
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "llava:latest",
    "image_description_active": True,
    "watched_folders_root": "",
}

FIELDS_SCHEMA = [
    {"key": "app_title", "label": "Titulo de la App", "type": "text"},
    {"key": "app_port", "label": "Puerto", "type": "number"},
    {"key": "anythingllm_api_key", "label": "API Key InfoHub", "type": "password"},
    {"key": "anythingllm_base_url", "label": "URL InfoHub", "type": "text"},
    {"key": "ollama_base_url", "label": "URL Ollama", "type": "text"},
    {"key": "ollama_model", "label": "Modelo Ollama", "type": "text"},
    {"key": "image_description_active", "label": "Descripciones de Imagenes", "type": "bool"},
    {"key": "watched_folders_root", "label": "Carpeta Raiz Observada", "type": "text"},
    {"key": "log_level", "label": "Nivel de Log", "type": "select", "options": ["DEBUG", "INFO", "WARNING", "ERROR"]},
    {"key": "log_file", "label": "Archivo de Log", "type": "text"},
]


class ConfigManager:
    def __init__(self, config_path=None):
        self.config_path = Path(config_path) if config_path else CONFIG_FILE
        self._config = {}
        self.load()

    def load(self):
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
                logger.info(f"Config loaded from {self.config_path}")
            else:
                self._config = {}
                logger.warning("No config file found, using defaults")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            self._config = {}

        for key, value in DEFAULTS.items():
            if key not in self._config:
                self._config[key] = value

    def save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.info(f"Config saved to {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            return False

    def get(self, key, default=None):
        return self._config.get(key, default)

    def set(self, key, value):
        self._config[key] = value

    def get_all(self):
        return dict(self._config)

    def update(self, data: dict):
        self._config.update(data)

    @staticmethod
    def get_schema():
        return FIELDS_SCHEMA
