"""Mantine-compatible model color palette and assignment."""

from __future__ import annotations

# Bright, contrasting hues (Mantine default palette names).
MODEL_COLOR_PALETTE: tuple[str, ...] = (
    "cyan",
    "orange",
    "grape",
    "lime",
    "pink",
    "teal",
    "yellow",
    "indigo",
    "red",
    "violet",
    "blue",
    "green",
)

DEFAULT_MODEL_COLOR = "blue"


def is_valid_model_color(color: str) -> bool:
    return color in MODEL_COLOR_PALETTE


def pick_model_color(used_colors: set[str]) -> str:
    """Pick the next unused palette color; cycle if the palette is exhausted."""
    for color in MODEL_COLOR_PALETTE:
        if color not in used_colors:
            return color
    return MODEL_COLOR_PALETTE[len(used_colors) % len(MODEL_COLOR_PALETTE)]
