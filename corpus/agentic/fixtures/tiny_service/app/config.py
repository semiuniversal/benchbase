"""Service settings."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Settings:
    name: str = "tiny-service"
    port: int = 8080  # task may change default
    cors_origin: str = ""  # empty = no CORS; task may set *
