"""Parse base-model names and nominal quantization ranks from model IDs."""

from __future__ import annotations

import re

# Longer / more specific suffixes first.
_VARIANT_SUFFIXES = (
    "-int4-autoround",
    "-int8-autoround",
    "-nvfp4-nothink",
    "-nvfp4",
    "-nothink",
    "-think",
    "-q8_0",
    "-q6_k",
    "-q5_k_m",
    "-q5_k_s",
    "-q4_k_m",
    "-q4_k_s",
    "-q4_0",
    "-q3_k_m",
    "-q2_k",
    "-fp16",
    "-bf16",
    "-dual",
    "-low",
)

_QUANT_PATTERNS: list[tuple[re.Pattern[str], int, str]] = [
    (re.compile(r"fp16|bf16|f16", re.I), 100, "fp16"),
    (re.compile(r"q8|int8", re.I), 80, "q8"),
    (re.compile(r"q6", re.I), 60, "q6"),
    (re.compile(r"q5", re.I), 50, "q5"),
    (re.compile(r"nvfp4|fp4", re.I), 45, "fp4"),
    (re.compile(r"q4|int4|autoround", re.I), 40, "q4"),
    (re.compile(r"q3", re.I), 30, "q3"),
    (re.compile(r"q2", re.I), 20, "q2"),
]


def parse_base_model(name: str) -> str:
    """Strip known quant/variant suffixes; default to full name on failure."""
    base = name.strip()
    # Drop org prefix for grouping only when a slash is present? Spec says strip
    # quant/variant suffixes from model name — keep org if present.
    lowered = base.lower()
    changed = True
    while changed:
        changed = False
        for suffix in _VARIANT_SUFFIXES:
            if lowered.endswith(suffix):
                base = base[: -len(suffix)]
                lowered = base.lower()
                changed = True
                break
    return base or name


def infer_quant_rank(name: str, quantization: str | None = None) -> int:
    """Higher = more precision. Used for family-mode ring ordering."""
    hay = f"{name} {quantization or ''}".lower()
    for pattern, rank, _ in _QUANT_PATTERNS:
        if pattern.search(hay):
            return rank
    return 70  # unknown mid default


def infer_quant_label(name: str, quantization: str | None = None) -> str | None:
    if quantization:
        return quantization
    hay = name.lower()
    for pattern, _, label in _QUANT_PATTERNS:
        if pattern.search(hay):
            return label
    return None
