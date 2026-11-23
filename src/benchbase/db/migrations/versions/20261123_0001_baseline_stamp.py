"""Baseline stamp — schema owned by init_db() until first breaking migration.

Revision ID: 20261123_0001
Revises:
Create Date: 2026-11-23
"""

from __future__ import annotations

revision = "20261123_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Existing deployments: alembic stamp head after backup."""
    pass


def downgrade() -> None:
    pass