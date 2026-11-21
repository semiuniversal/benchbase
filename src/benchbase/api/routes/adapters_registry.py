"""Upstream benchmark adapter registry (WP6)."""

from __future__ import annotations

from fastapi import APIRouter

from benchbase.adapters.registry import adapter_descriptors
from benchbase.config import load_settings

router = APIRouter()


@router.get("/", operation_id="list_upstream_adapters")
async def list_upstream_adapters():
    settings = load_settings()
    return {
        "schema_version": "benchbase.adapters.v1",
        "upstream_adapters_enabled": settings.upstream_adapters_enabled,
        "adapters": adapter_descriptors(settings),
    }