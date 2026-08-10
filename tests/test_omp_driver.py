"""Unit tests for OMP AttemptLedger parsing (fixture transcript; no live model)."""

from __future__ import annotations

from pathlib import Path

from benchbase.agentic.ledger import AttemptLedger
from benchbase.agentic.omp_driver import OmpDriver, parse_session_file

FIXTURE = Path(__file__).parent / "fixtures" / "omp_sessions" / "trivial_edit.jsonl"


def test_parse_fixture_session_covers_ledger_fields():
    ledger = parse_session_file(FIXTURE, wall_seconds=12.5)
    assert ledger.wall_seconds == 12.5
    assert ledger.turns >= 3
    assert ledger.tool_calls >= 4
    assert ledger.hashline_rejected_edits >= 1
    assert ledger.tokens_prompt > 0
    assert ledger.tokens_completion > 0
    assert ledger.tokens_thinking > 0
    assert ledger.session_id == "fixture-sess-001"
    assert ledger.tokens_total == ledger.tokens_prompt + ledger.tokens_completion + ledger.tokens_thinking


def test_omp_driver_fixture_mode_injects_prompt_flag():
    driver = OmpDriver(fixture_transcript=FIXTURE, timeout_s=60)
    ledger = driver.run_attempt("Fix the greeting to say Welcome.")
    assert ledger.prompt_injected is True
    assert ledger.hashline_rejected_edits >= 1
    assert isinstance(ledger.to_dict(), dict)


def test_attempt_ledger_roundtrip():
    original = AttemptLedger(
        wall_seconds=1.0,
        turns=2,
        tool_calls=3,
        hashline_rejected_edits=1,
        tokens_prompt=10,
        tokens_completion=5,
        tokens_thinking=1,
        prompt_injected=True,
    )
    restored = AttemptLedger.from_dict(original.to_dict())
    assert restored.tokens_total == 16
    assert restored.hashline_rejected_edits == 1
