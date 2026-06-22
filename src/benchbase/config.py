"""Application configuration backed by settings.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.yaml"
DATA_DIR = Path(os.environ.get("BENCHBASE_DATA_DIR", CONFIG_DIR.parent))

_DEFAULTS: dict[str, Any] = {
    "litellm_base_url": "http://localhost:4000",
    "litellm_api_key": "",
    "database_url": "sqlite+aiosqlite:///benchbase.db",
    "theme": "dark",
    "default_models": [],
    "benchmark_suites": ["speed"],
    "litebench_timeout_seconds": 600,
    "batch_sample_limit": 10,
    "routine_sample_limit": 50,
}


class Settings(BaseModel):
    litellm_base_url: str = _DEFAULTS["litellm_base_url"]
    litellm_api_key: str = _DEFAULTS["litellm_api_key"]
    database_url: str = _DEFAULTS["database_url"]
    theme: str = _DEFAULTS["theme"]
    default_models: list[str] = []
    benchmark_suites: list[str] = ["speed"]
    litebench_timeout_seconds: int = _DEFAULTS["litebench_timeout_seconds"]
    batch_sample_limit: int = Field(default=10, ge=1, le=500)
    routine_sample_limit: int = Field(default=50, ge=10, le=500)


def load_settings() -> Settings:
    """Load settings from YAML, falling back to defaults."""
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            data = yaml.safe_load(f) or {}
        settings = Settings(**{**_DEFAULTS, **data})
    else:
        settings = Settings()

    db_url = os.environ.get("BENCHBASE_DB_URL")
    if db_url:
        settings = settings.model_copy(update={"database_url": db_url})
    return settings


def save_settings(settings: Settings) -> None:
    """Persist settings to YAML."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        yaml.dump(settings.model_dump(), f, default_flow_style=False, sort_keys=False)
