"""Application configuration backed by settings.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.yaml"

_DEFAULTS: dict[str, Any] = {
    "litellm_base_url": "http://localhost:4000",
    "litellm_api_key": "",
    "database_url": "sqlite+aiosqlite:///benchbase.db",
    "theme": "dark",
    "default_models": [],
    "benchmark_suites": ["speed"],
}


class Settings(BaseModel):
    litellm_base_url: str = _DEFAULTS["litellm_base_url"]
    litellm_api_key: str = _DEFAULTS["litellm_api_key"]
    database_url: str = _DEFAULTS["database_url"]
    theme: str = _DEFAULTS["theme"]
    default_models: list[str] = []
    benchmark_suites: list[str] = ["speed"]


def load_settings() -> Settings:
    """Load settings from YAML, falling back to defaults."""
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            data = yaml.safe_load(f) or {}
        return Settings(**{**_DEFAULTS, **data})
    return Settings()


def save_settings(settings: Settings) -> None:
    """Persist settings to YAML."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        yaml.dump(settings.model_dump(), f, default_flow_style=False, sort_keys=False)
