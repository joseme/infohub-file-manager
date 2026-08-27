"""Tests for ConfigManager"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from config_manager import ConfigManager, DEFAULTS, FIELDS_SCHEMA


class TestConfigManager:
    """Tests for ConfigManager loading, saving, and field access."""

    def test_load_non_existent_file_applies_defaults(self, tmp_path: Path):
        """Loading a non-existent config file should result in defaults."""
        config_path = tmp_path / "nonexistent.json"
        assert not config_path.exists()

        cm = ConfigManager(config_path)
        assert cm.get("app_title") == DEFAULTS["app_title"]
        assert cm.get("anythingllm_base_url") == "http://localhost:3000"
        assert cm.get("watched_folders_root") == ""

    def test_load_saves_to_file_roundtrip(self, tmp_path: Path):
        """Save and reload should preserve all values."""
        config_path = tmp_path / "test_config.json"
        cm = ConfigManager(config_path)

        # Modify a few values
        cm.set("app_title", "Custom Title")
        cm.set("anythingllm_api_key", "test-key-123")
        cm.set("watched_folders_root", "/some/path")
        cm.set("image_description_active", False)

        assert cm.save() is True
        assert config_path.exists()

        # Reload from the saved file
        cm2 = ConfigManager(config_path)
        assert cm2.get("app_title") == "Custom Title"
        assert cm2.get("anythingllm_api_key") == "test-key-123"
        assert cm2.get("watched_folders_root") == "/some/path"
        assert cm2.get("image_description_active") is False

    def test_load_from_valid_file(self, tmp_path: Path):
        """Loading from a config file should read all values correctly."""
        data = {
            "app_title": "My App",
            "app_port": 9000,
            "anythingllm_api_key": "key-from-file",
            "anythingllm_base_url": "https://custom.example.com",
        }
        config_path = tmp_path / "valid_config.json"
        with open(config_path, "w") as f:
            json.dump(data, f)

        cm = ConfigManager(config_path)
        assert cm.get("app_title") == "My App"
        assert cm.get("app_port") == 9000
        assert cm.get("anythingllm_api_key") == "key-from-file"

        # Missing keys should fall back to defaults
        assert cm.get("ollama_model") == "llava:latest"

    def test_load_corrupt_json_uses_defaults(self, tmp_path: Path):
        """Corrupt JSON should fall back to defaults without crashing."""
        config_path = tmp_path / "corrupt.json"
        config_path.write_text("{invalid json here}")

        cm = ConfigManager(config_path)
        # Should have loaded defaults
        assert cm.get("app_title") == DEFAULTS["app_title"]
        assert cm.get("app_port") == DEFAULTS["app_port"]

    def test_load_corrupt_json_records_error(self, tmp_path: Path):
        config_path = tmp_path / "corrupt.json"
        config_path.write_text("{invalid json here}")

        cm = ConfigManager(config_path)

        assert cm.last_error is not None

    def test_load_valid_json_clears_error(self, tmp_path: Path):
        config_path = tmp_path / "valid.json"
        config_path.write_text('{"app_port": 9999}')

        cm = ConfigManager(config_path)

        assert cm.last_error is None
        assert cm.get("app_port") == 9999

    def test_save_write_failure_returns_false(self, tmp_path: Path):
        """When the config file cannot be written, save() should return False."""
        cm = ConfigManager(tmp_path / "valid_config.json")
        cm.set("app_title", "Test")

        with patch("builtins.open", side_effect=PermissionError("No write perm")):
            assert cm.save() is False

    def test_get_default_fallback(self, tmp_path: Path):
        """get() should return the provided default when key doesn't exist."""
        cm = ConfigManager(tmp_path / "empty.json")
        assert cm.get("nonexistent_key", "fallback") == "fallback"
        assert cm.get("nonexistent_key") is None

    def test_set_and_get_all(self, tmp_path: Path):
        """set() and get_all() should work correctly."""
        cm = ConfigManager(tmp_path / "test.json")
        cm.set("watched_folders_root", "/my/folder")
        assert cm.get("watched_folders_root") == "/my/folder"

        all_config = cm.get_all()
        assert isinstance(all_config, dict)
        assert all_config["watched_folders_root"] == "/my/folder"
        # Defaults should also be present
        assert "app_title" in all_config

    def test_update(self, tmp_path: Path):
        """update() should merge provided data into config."""
        cm = ConfigManager(tmp_path / "test.json")
        cm.update({"watched_folders_root": "/updated", "app_port": 9999})

        assert cm.get("watched_folders_root") == "/updated"
        assert cm.get("app_port") == 9999
        # Other defaults should remain
        assert cm.get("app_title") == DEFAULTS["app_title"]

    def test_get_schema_returns_static_schema(self):
        """get_schema() should return the schema list."""
        schema = ConfigManager.get_schema()
        assert schema == FIELDS_SCHEMA
        assert len(schema) > 0
        # Check structure
        for field in schema:
            assert "key" in field
            assert "label" in field
            assert "type" in field

    def test_get_schema_is_independent_copy(self):
        """get_schema() should not leak mutations."""
        schema = ConfigManager.get_schema()
        schema.append({"key": "fake", "label": "Fake", "type": "text"})
        assert len(ConfigManager.get_schema()) == len(FIELDS_SCHEMA)

    def test_default_port_value(self, tmp_path: Path):
        """The default app_port should be 8500."""
        cm = ConfigManager(tmp_path / "new.json")
        assert cm.get("app_port") == 8500

    def test_save_preserves_full_json_structure(self, tmp_path: Path):
        """After save, the JSON file should contain all keys (defaults + overrides)."""
        config_path = tmp_path / "full_test.json"
        cm = ConfigManager(config_path)
        cm.set("watched_folders_root", "/infohub/docs")
        cm.set("anythingllm_api_key", "secret-abc")
        cm.save()

        with open(config_path) as f:
            saved = json.load(f)

        assert saved["watched_folders_root"] == "/infohub/docs"
        assert saved["anythingllm_api_key"] == "secret-abc"
        assert saved["app_port"] == 8500  # default preserved

    def test_set_non_string_value(self, tmp_path: Path):
        """set() should handle non-string values like int and bool."""
        cm = ConfigManager(tmp_path / "types.json")
        cm.set("app_port", 3000)
        cm.set("image_description_active", False)
        cm.save()

        cm2 = ConfigManager(tmp_path / "types.json")
        assert cm2.get("app_port") == 3000
        assert cm2.get("image_description_active") is False
