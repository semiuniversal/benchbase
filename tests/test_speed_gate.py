"""Speed short-EOS / collapsed-prefill gate and historical rescore rewriter."""

from __future__ import annotations

import json

from benchbase.speed_gate import (
    decode_invalid_reason,
    implied_prompt_tokens,
    prefill_invalid_reason,
    rewrite_speed_row,
)


def test_three_token_cell_invalid():
    reason = decode_invalid_reason(3.0, 2048)
    assert reason is not None
    assert "short EOS" in reason


def test_2048_token_cell_kept():
    assert decode_invalid_reason(2048.0, 2048) is None


def test_half_tg_still_required():
    # 40 tokens clears the absolute floor but is nowhere near tg=2048.
    reason = decode_invalid_reason(40.0, 2048)
    assert reason is not None
    assert "0.5 * tg" in reason


def test_pp_times_est_ppt_approx_one_invalidates_prefill():
    # Live Sharp signature: 6.78 tok/s * 148 ms ≈ 1 prompt token.
    implied = implied_prompt_tokens(6.78, 148.0)
    assert implied is not None
    assert implied < 8
    reason = prefill_invalid_reason(6.78, 148.0, 128)
    assert reason is not None
    assert "pp≈1" in reason


def test_real_128_token_prefill_kept():
    # 850 tok/s * 150 ms ≈ 127.5 prompt tokens.
    assert implied_prompt_tokens(850.0, 150.0) > 100
    assert prefill_invalid_reason(850.0, 150.0, 128) is None


def test_tiny_prompt_size_invalidates_prefill():
    reason = prefill_invalid_reason(900.0, 10.0, 1)
    assert reason is not None
    assert "prompt_size" in reason


def test_rewrite_nulls_short_decode_without_inventing_tps():
    row = {
        "task_name": "speed:output_tps2048",
        "score": 11.04,
        "metrics_json": json.dumps({
            "type": "output_tps",
            "throughput_mean": 11.04,
            "output_token_count": {"mean": 3.0, "std": 0.8, "values": [3, 2, 4]},
        }),
        "raw_output_json": json.dumps({
            "response_size": 2048,
            "benchbase_thinking": {
                "output_token_count": {"mean": 3.0, "values": [3, 2, 4]},
            },
        }),
    }
    patch = rewrite_speed_row(row)
    assert patch is not None
    assert patch["score"] is None
    metrics = json.loads(patch["metrics_json"])
    assert metrics["original_score"] == 11.04
    assert "short EOS" in metrics["invalid_reason"]
    assert "output_tps" not in patch or patch.get("score") is None


def test_rewrite_keeps_full_length_decode():
    row = {
        "task_name": "speed:output_tps2048",
        "score": 42.0,
        "metrics_json": json.dumps({
            "output_token_count": {"mean": 2048.0},
        }),
        "raw_output_json": json.dumps({"response_size": 2048}),
    }
    assert rewrite_speed_row(row) is None


def test_rewrite_nulls_collapsed_prefill():
    row = {
        "task_name": "speed:prefill_tps128",
        "score": 6.78,
        "metrics_json": json.dumps({
            "type": "prefill_tps",
            "throughput_mean": 6.78,
            "est_ppt": {"mean": 147.5, "std": 1.0},
        }),
        "raw_output_json": json.dumps({
            "prompt_size": 128,
            "pp_throughput": {"mean": 6.78},
            "est_ppt": {"mean": 147.5},
        }),
    }
    patch = rewrite_speed_row(row)
    assert patch is not None
    assert patch["score"] is None
    metrics = json.loads(patch["metrics_json"])
    assert metrics["original_score"] == 6.78
    assert "collapsed prefill" in metrics["invalid_reason"]


def test_rewrite_idempotent_when_already_invalid():
    row = {
        "task_name": "speed:output_tps2048",
        "score": None,
        "metrics_json": json.dumps({
            "original_score": 11.04,
            "invalid_reason": "short EOS: output_token_count.mean=3.0 < 32",
            "output_token_count": {"mean": 3.0},
        }),
        "raw_output_json": json.dumps({"response_size": 2048}),
    }
    assert rewrite_speed_row(row) is None


def test_rewrite_ignores_ttft_rows():
    row = {
        "task_name": "speed:ttft_ms2048",
        "score": 389.0,
        "metrics_json": "{}",
        "raw_output_json": "{}",
    }
    assert rewrite_speed_row(row) is None
