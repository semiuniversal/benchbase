"""WP9 export redaction smoke test."""

from benchbase.api.routes.export_pkg import _redact


def test_redact_sk_like_tokens():
    raw = {"notes": "key sk-abcdefghijklmnopqrstuvwxyz here"}
    out = _redact(raw)
    assert "sk-abc" not in out["notes"]
    assert "REDACTED" in out["notes"]