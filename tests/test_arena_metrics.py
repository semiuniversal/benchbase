"""WP2: Arena metric provenance (ADR-002)."""

from benchbase.metrics.arena_stream import ArenaStreamAccumulator


def test_no_fake_token_tps_without_usage():
    acc = ArenaStreamAccumulator()
    for _ in range(5):
        acc.note_chunk("content")
    snap = acc.snapshot()
    assert snap["tokens_per_second"] is None
    assert snap["decode_rate_method"] == "unavailable"
    assert snap["output_chunk_rate_per_s"] is not None


def test_provider_usage_yields_token_tps():
    acc = ArenaStreamAccumulator()
    acc.note_chunk("content")
    acc.note_usage({"completion_tokens": 12})
    snap = acc.snapshot()
    assert snap["output_tokens"] == 12
    assert snap["decode_rate_method"] == "provider_usage"