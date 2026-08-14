"""Unit tests for extract-then-compare scorers and prompt audits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchbase.controls import control_respond
from benchbase.runners.quality_common import (
    extract_final_number,
    extract_mc_letter,
    load_fixture_items,
    visible_completion,
)
from benchbase.runners.coding import _extract_python
from benchbase.runners.instruction import check_rule

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus" / "suites"


def test_mc_rejects_echo_and_first_letter_anywhere():
    prompt = (
        "Which planet?\nA) Venus\nB) Mars\nC) Jupiter\nD) Saturn\n"
        "Answer with A, B, C, or D only."
    )
    letter, reason = extract_mc_letter(prompt)
    assert letter is None
    assert reason == "unparseable"

    letter, reason = extract_mc_letter("B")
    assert letter == "B"
    assert reason is None

    letter, reason = extract_mc_letter("The answer is C.")
    assert letter == "C"


def test_mc_empty_unparseable():
    letter, reason = extract_mc_letter("")
    assert letter is None
    assert reason == "unparseable"


def test_visible_completion_drops_thinking_not_reasoning_fallback():
    assert visible_completion({"reasoning_content": "secret chain", "content": ""}) == ""
    assert visible_completion({"content": "<think>ramble</think>\nB"}) == "B"
    dump = (
        "Thinking Process:\n\n1. Analyze the Request:\n   - Options: A) air B) iron\n"
        "The answer is A."
    )
    visible = visible_completion({"content": dump})
    letter, reason = extract_mc_letter(visible)
    assert letter == "A"
    assert reason is None


def test_math_prefers_hash_delimiter_not_any_number():
    text = "Step 1: compute 15. Step 2: add 3. #### 42"
    got, reason = extract_final_number(text)
    assert got == "42"
    assert reason is None

    got, reason = extract_final_number("I think about 15 then 3 then maybe")
    assert got is None
    assert reason == "unparseable"


def test_coding_empty_code_unparseable():
    assert _extract_python("") is None
    assert _extract_python("just prose") is None
    assert _extract_python("```python\ndef f():\n  return 1\n```") is not None


def test_echo_control_fails_mc_extraction():
    prompt = (
        "Pick one.\nA) one\nB) two\nC) three\nD) four\n"
        "Answer with A, B, C, or D only."
    )
    echoed = control_respond("__control_echo__", [{"role": "user", "content": prompt}])
    letter, reason = extract_mc_letter(echoed)
    assert letter is None
    assert reason == "unparseable"


def test_null_control_empty():
    assert control_respond("__control_null__", [{"role": "user", "content": "hi"}]) == ""


def test_instruction_word_count():
    ok, reason = check_rule("one two three", {"type": "word_count", "n": 3})
    assert ok and reason is None
    ok, reason = check_rule("", {"type": "word_count", "n": 3})
    assert not ok and reason == "unparseable"


@pytest.mark.parametrize(
    "axis,gold_keys",
    [
        ("knowledge", ["answer"]),
        ("reasoning", ["answer"]),
        ("math", ["answer"]),
    ],
)
def test_prompt_audit_no_gold_leak(axis: str, gold_keys: list[str]):
    items = load_fixture_items(axis, "v2")
    assert items, f"missing corpus for {axis}"
    item = items[0]
    prompt = item["prompt"]
    for key in gold_keys:
        gold = str(item.get(key, ""))
        if not gold:
            continue
        # Gold letter alone can appear in "Answer with A, B, C, or D" — check option text leak.
        if axis in ("knowledge", "reasoning"):
            choices = item.get("choices") or []
            ans = item.get("answer")
            idx = "ABCD".index(ans) if ans in "ABCD" else -1
            if idx >= 0 and idx < len(choices):
                gold_text = str(choices[idx])
                # The correct option text appears once as the labeled choice — that's OK.
                # Fail if gold text appears outside the option list lines.
                assert f"{ans}) {gold_text}" in prompt
            assert "correct_" not in prompt
        else:
            # Math: numeric gold must not appear as a spoon-fed answer line.
            assert f"Answer: {gold}" not in prompt
            assert f"#### {gold}" not in prompt


def test_knowledge_is_real_tinymmlu_not_stub():
    items = load_fixture_items("knowledge", "v2")
    assert len(items) == 100
    assert "correct_0" not in items[0]["prompt"]
    manifest = json.loads((CORPUS / "knowledge" / "v2" / "MANIFEST.json").read_text())
    assert "tinyMMLU" in manifest["source"]
    assert manifest["item_count"] == 100


def test_coding_is_livecodebench_stratified():
    items = load_fixture_items("coding", "v2")
    assert len(items) >= 40
    diffs = {it["difficulty"] for it in items}
    assert diffs == {"easy", "medium", "hard"}
    assert items[0]["harness"] == "stdin"
    assert items[0]["tests"]
