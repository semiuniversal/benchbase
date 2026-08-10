"""Minimal in-process HTTP-ish service (no network required for checkers)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from .config import Settings

@dataclass
class Response:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)

class App:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._fail_once = False  # failure-injection hook

    def enable_fail_once(self) -> None:
        self._fail_once = True

    def handle(self, method: str, path: str) -> Response:
        if self._fail_once:
            self._fail_once = False
            raise ConnectionError("transient upstream failure (injected)")
        if path == "/health":
            # Missing "version" field — task may add it
            return Response(200, {"ok": True, "service": self.settings.name}, headers={})
        if path == "/echo":
            return Response(200, {"echo": True})
        return Response(404, {"error": "not found"})

def create_app() -> App:
    return App()
