"""Tests for configuration loader module."""
from pathlib import Path

import pytest

from src.config_loader import (
    load_config_secure,
    load_locations,
    load_settings,
)
from src.models import LocationConfig


class TestLoadConfigSecure:
    """Tests for secure YAML loading."""

    def test_load_valid_yaml(self, tmp_path):
        """Test loading a valid YAML file."""
        yaml_content = """
key1: value1
key2: 123
nested:
  inner: true
"""
        filepath = tmp_path / "config.yaml"
        filepath.write_text(yaml_content)

        config = load_config_secure(filepath)

        assert config["key1"] == "value1"
        assert config["key2"] == 123
        assert config["nested"]["inner"] is True

    def test_file_not_found(self, tmp_path):
        """Test FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            load_config_secure(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_structure(self, tmp_path):
        """Test ValueError for non-dictionary YAML."""
        yaml_content = "- item1\n- item2\n- item3"
        filepath = tmp_path / "list.yaml"
        filepath.write_text(yaml_content)

        with pytest.raises(ValueError, match="must be a dictionary"):
            load_config_secure(filepath)

    def test_safe_load_prevents_code_execution(self, tmp_path):
        """Test that safe_load prevents YAML code execution.

        CRITICAL: This test verifies that yaml.safe_load() is used,
        which prevents arbitrary code execution attacks.
        """
        # This would execute code with yaml.load() but is safe with safe_load()
        dangerous_yaml = """
!!python/object/apply:os.system
args: ['echo HACKED']
"""
        filepath = tmp_path / "dangerous.yaml"
        filepath.write_text(dangerous_yaml)

        # safe_load should raise an error, not execute the code
        with pytest.raises(Exception):
            load_config_secure(filepath)


class TestLoadLocations:
    """Tests for location configuration loading."""

    @pytest.fixture
    def valid_locations_yaml(self, tmp_path):
        """Create a valid locations YAML file."""
        yaml_content = """
provinces:
  BC:
    - address: "123 Main St, Vancouver, BC V5K 0A1"
      store_name: "Vancouver Downtown"
    - address: "456 Oak St, Victoria, BC V8W 1N4"
      store_name: "Victoria Central"
  AB:
    - address: "789 Centre St, Calgary, AB T2E 2R8"
      store_name: "Calgary Centre"
"""
        filepath = tmp_path / "locations.yaml"
        filepath.write_text(yaml_content)
        return filepath

    def test_load_locations(self, valid_locations_yaml):
        """Test loading location configurations."""
        locations = load_locations(valid_locations_yaml)

        assert len(locations) == 3
        assert all(isinstance(loc, LocationConfig) for loc in locations)

        # Check BC locations
        bc_locations = [loc for loc in locations if loc.province == "BC"]
        assert len(bc_locations) == 2
        assert bc_locations[0].store_name == "Vancouver Downtown"

    def test_missing_provinces_section(self, tmp_path):
        """Test ValueError when provinces section is missing."""
        yaml_content = "categories:\n  - pizzas"
        filepath = tmp_path / "no_provinces.yaml"
        filepath.write_text(yaml_content)

        with pytest.raises(ValueError, match="provinces"):
            load_locations(filepath)

    def test_empty_provinces(self, tmp_path):
        """Test handling of empty provinces section."""
        yaml_content = "provinces: {}"
        filepath = tmp_path / "empty_provinces.yaml"
        filepath.write_text(yaml_content)

        locations = load_locations(filepath)
        assert len(locations) == 0


class TestLoadSettings:
    """Tests for settings configuration loading."""

    def test_load_settings_with_defaults(self, tmp_path):
        """Test that default values are applied."""
        yaml_content = """
custom_setting: custom_value
"""
        filepath = tmp_path / "settings.yaml"
        filepath.write_text(yaml_content)

        settings = load_settings(filepath)

        # Custom setting preserved
        assert settings["custom_setting"] == "custom_value"

        # Defaults applied
        assert settings["timeout_ms"] == 30000
        assert settings["headless"] is True
        assert settings["max_concurrent"] == 5

    def test_override_defaults(self, tmp_path):
        """Test that explicit values override defaults."""
        yaml_content = """
timeout_ms: 60000
headless: false
max_concurrent: 10
"""
        filepath = tmp_path / "settings.yaml"
        filepath.write_text(yaml_content)

        settings = load_settings(filepath)

        assert settings["timeout_ms"] == 60000
        assert settings["headless"] is False
        assert settings["max_concurrent"] == 10
