"""Configuration loading with YAML security."""
from pathlib import Path
from typing import Any

import yaml

from .models import LocationConfig


def load_config_secure(config_path: Path) -> dict[str, Any]:
    """Load YAML configuration with security hardening.

    CRITICAL: Uses safe_load() to prevent code execution attacks.
    Never use yaml.load() without a SafeLoader.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        Dictionary containing the configuration.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If config is not a valid dictionary.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        # CRITICAL: Use safe_load() - never yaml.load()
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError("Configuration must be a dictionary")

    return config


def load_locations(config_path: Path) -> list[LocationConfig]:
    """Load location configurations from YAML file.

    Args:
        config_path: Path to the locations YAML file.

    Returns:
        List of LocationConfig objects for each store.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If provinces section is missing or invalid.
    """
    config = load_config_secure(config_path)

    if "provinces" not in config:
        raise ValueError("Configuration must contain 'provinces' section")

    locations: list[LocationConfig] = []

    for province_code, stores in config["provinces"].items():
        if not isinstance(stores, list):
            continue

        for store in stores:
            if not isinstance(store, dict):
                continue

            # Support both "city" (new) and "address" (legacy) keys
            city_or_address = store.get("city") or store.get("address", "")

            locations.append(
                LocationConfig(
                    store_name=store.get("store_name", f"{province_code} Store"),
                    address=city_or_address,
                    province=province_code,
                )
            )

    return locations


def load_settings(config_path: Path) -> dict[str, Any]:
    """Load settings configuration from YAML file.

    Args:
        config_path: Path to the settings YAML file.

    Returns:
        Dictionary containing settings with defaults applied.
    """
    config = load_config_secure(config_path)

    # Apply defaults
    defaults = {
        "timeout_ms": 30000,
        "headless": True,
        "max_concurrent": 5,
        "retry_attempts": 3,
        "base_delay_ms": 1000,
        "min_delay_ms": 2000,
        "max_delay_ms": 5000,
    }

    for key, value in defaults.items():
        config.setdefault(key, value)

    return config
