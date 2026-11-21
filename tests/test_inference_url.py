"""Inference base URL normalization (LLManifold / OpenAI-compatible)."""

from benchbase.config import inference_openai_v1_root, inference_server_origin

REVENTANT = "http://revenant.jackalope-bicolor.ts.net:20004"


def test_openai_v1_root_appends_v1_when_missing():
    assert inference_openai_v1_root(REVENTANT) == f"{REVENTANT}/v1"


def test_openai_v1_root_accepts_trailing_v1():
    assert (
        inference_openai_v1_root(f"{REVENTANT}/v1")
        == f"{REVENTANT}/v1"
    )


def test_server_origin_strips_v1_suffix():
    assert inference_server_origin(f"{REVENTANT}/v1") == REVENTANT
    assert inference_server_origin(REVENTANT) == REVENTANT