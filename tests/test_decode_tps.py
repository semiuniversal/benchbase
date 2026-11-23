"""Addendum A: decode TPS semantics and aggregation."""

from __future__ import annotations

import time

from benchbase.decode_tps import (
    generated_decode_from_request,
    median_decode_headline,
    median_decode_headline_natural,
    select_decode_measurement,
)
from benchbase.runners.llama_benchy_stream import throughput_from_timestamps


def test_decode_ignores_prefill_duration():
    start = 1000.0
    first = start + 2.0
    stamps = [first + i * (10.0 / 500) for i in range(501)]
    tps, ttft, dur = throughput_from_timestamps(
        stamps, start_ts=start, first_ts=first, total_tokens=501
    )
    assert dur is not None and abs(dur - 10.0) < 0.01
    assert tps is not None and abs(tps - 50.0) < 0.05
    assert ttft is not None and abs(ttft - 2.0) < 0.01

    slow_start = start
    slow_first = slow_start + 20.0
    slow_stamps = [slow_first + i * (10.0 / 500) for i in range(501)]
    slow_tps, slow_ttft, _ = throughput_from_timestamps(
        slow_stamps, start_ts=slow_start, first_ts=slow_first, total_tokens=501
    )
    assert slow_tps is not None and abs(slow_tps - 50.0) < 0.05
    assert slow_ttft is not None and abs(slow_ttft - 20.0) < 0.01


def test_generated_decode_includes_reasoning_tokens():
    base = time.perf_counter()
    reasoning_ts = [base + 0.1 * i for i in range(2000)]
    output_ts = [reasoning_ts[-1] + 0.02 * (i + 1) for i in range(500)]
    tps, n, _ms, reason = generated_decode_from_request(
        reasoning_ts=reasoning_ts,
        output_ts=output_ts,
        first_reasoning_ts=reasoning_ts[0],
        first_output_ts=output_ts[0],
        reasoning_tokens=2000,
        output_tokens=500,
    )
    assert reason is None
    assert n == 2500
    assert tps is not None and tps > 0


def test_median_headline_excludes_invalid_replicate_exact():
    score, reason, valid, total, conf = median_decode_headline(
        {"values": [512, 512, 512, 512, 100]},
        {"values": [40.0, 55.0, 50.0, 48.0, 52.0]},
        forcing="exact",
    )
    assert reason is None
    assert valid == 4
    assert total == 5
    assert score == 49.0
    assert conf == "high"


def test_median_unavailable_when_too_few_valid_exact():
    score, reason, valid, _total, conf = median_decode_headline(
        {"values": [512, 100, 100]},
        {"values": [50.0, 11.0, 12.0]},
        min_valid=3,
        forcing="exact",
    )
    assert score is None
    assert reason is not None
    assert valid < 3
    assert conf in ("low", None)


def test_natural_publishes_low_confidence():
    score, reason, valid, total, conf = median_decode_headline_natural(
        {"values": [180, 200, 30, 8]},
        {"values": [44.0, 42.0, 50.0, 9.0]},
    )
    assert score is not None
    assert reason is None
    assert valid == 2
    assert total == 4
    assert conf == "low"


def test_natural_fails_without_trustworthy_reps():
    score, reason, valid, total, conf = median_decode_headline_natural(
        {"values": [5, 8, 3]},
        {"values": [100.0, 80.0, 90.0]},
    )
    assert score is None
    assert reason is not None
    assert valid == 0
    assert conf is None


def test_select_decode_measurement_fallback_chain():
    thinking = {
        "output_tg_throughput": {"mean": 30.0, "values": [29.0, 31.0]},
        "output_token_count": {"values": [120, 130]},
    }
    tps, tok, method, _src = select_decode_measurement(thinking, {})
    assert tps is not None
    assert method.endswith("streaming") or "streaming" in method


def test_legacy_output_tps_unchanged_without_decode_row():
    from types import SimpleNamespace

    from benchbase.scoring import _extract_speed

    results = [
        SimpleNamespace(
            task_name="speed:output_tps2048",
            score=38.0,
            metrics_json=None,
            raw_output_json=None,
        ),
    ]
    speed = _extract_speed(results)
    assert speed["decode_tps"] is None
    assert speed["output_tps"] == 38.0


def test_visible_only_aggregate_does_not_fake_generated():
    tps, n, _ms, reason = generated_decode_from_request(
        reasoning_ts=[],
        output_ts=[1.0, 2.0],
        first_reasoning_ts=None,
        first_output_ts=1.0,
        reasoning_tokens=2000,
        output_tokens=0,
    )
    assert tps is None
    assert reason is not None