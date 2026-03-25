"""Configuration loader with YAML support and deep merging."""

import sys
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


class HoleSignal(BaseModel):
    """Hole detection pattern."""
    pattern: Optional[str] = None
    capture: Optional[dict[str, str]] = None


class ToleratedLengthSignal(BaseModel):
    """Tolerated length pattern."""
    pattern: Optional[str] = None
    description: Optional[str] = None


class SurfaceTreatmentOption(BaseModel):
    """Surface treatment option."""
    display_name: str = Field(alias="displayName")
    keywords: list[str] = []

    class Config:
        populate_by_name = True


class SurfaceTreatments(BaseModel):
    """Surface treatments configuration."""
    enabled: bool = False
    options: list[SurfaceTreatmentOption] = []


class Signals(BaseModel):
    """Signal patterns for extraction."""
    tolerated_lengths: list[ToleratedLengthSignal] = Field(
        default_factory=list
    )
    holes: list[HoleSignal] = []


class PromptAdditions(BaseModel):
    """Additional prompt instructions."""
    holes: list[str] = []
    tolerated_lengths: list[str] = []
    surface_treatment: list[str] = []
    material: list[str] = []


class PromptOptions(BaseModel):
    """Prompt configuration options."""
    max_signal_prompt_entries: int = 5


class CustomerConfig(BaseModel):
    """Customer-specific configuration."""
    customer_name: Optional[str] = Field(None, alias="customerName")
    signals: Optional[Signals] = None
    surface_treatments: Optional[SurfaceTreatments] = Field(
        None, alias="surfaceTreatments"
    )
    material_patterns: list[str] = []
    prompt_additions: Optional[PromptAdditions] = None
    prompt_options: Optional[PromptOptions] = None

    class Config:
        populate_by_name = True
        extra = "allow"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries. Override values take precedence."""
    result = base.copy()
    for key, val in override.items():
        if isinstance(val, list):
            result[key] = val
        elif isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def find_config_root() -> Path:
    """Find the config root directory."""
    # When bundled by PyInstaller, data files are extracted under _MEIPASS.
    meipass = getattr(sys, "_MEIPASS", None)

    # Check multiple possible locations
    possible_paths = [
        Path(meipass) / "config" if meipass else None,
        Path(__file__).parent.parent / "config",
        Path.cwd() / "config",
        Path.cwd() / "python_version" / "config",
    ]

    for path in possible_paths:
        if path is None:
            continue
        if path.exists():
            return path

    # Default to config in current directory
    return Path.cwd() / "config"


def load_yaml(file_path: Path, required: bool = False) -> dict[str, Any]:
    """Load a YAML file.

    Args:
        file_path: Path to the YAML file
        required: If True, raise FileNotFoundError when file doesn't exist

    Returns:
        Parsed YAML content as dictionary

    Raises:
        FileNotFoundError: If required=True and file doesn't exist
    """
    if not file_path.exists():
        if required:
            raise FileNotFoundError(f"Required config file not found: {file_path}")
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_customer_config(customer_id: str) -> CustomerConfig:
    """
    Load customer configuration with base merging.

    Config hierarchy:
    1. base.yaml (default settings)
    2. customers/<customer>/config.yaml (customer-specific overrides)
    3. customers/<customer>/surface-treatments.yaml (surface treatments)
    """
    config_root = find_config_root()

    # Load base config (required)
    base_yaml_path = config_root / "base.yaml"
    base_config = load_yaml(base_yaml_path, required=True)

    if customer_id == "base":
        # For 'base' customer, just use base.yaml directly
        return CustomerConfig(**base_config)

    # Load customer-specific config
    customer_root = config_root / "customers" / customer_id
    customer_yaml_path = customer_root / "config.yaml"
    surface_yaml_path = customer_root / "surface-treatments.yaml"

    customer_config = load_yaml(customer_yaml_path)
    surface_treatments = load_yaml(surface_yaml_path)

    # Deep merge base with customer config
    merged_config = deep_merge(base_config, customer_config)

    # Add surface treatments if they exist
    if surface_treatments:
        merged_config["surfaceTreatments"] = surface_treatments

    return CustomerConfig(**merged_config)


def get_max_signal_prompt_entries(config: CustomerConfig) -> int:
    """Get the maximum number of signal prompt entries."""
    if config.prompt_options and config.prompt_options.max_signal_prompt_entries:
        return config.prompt_options.max_signal_prompt_entries
    return 5
