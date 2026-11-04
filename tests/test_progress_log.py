"""Live quality-log exchanges."""

from benchbase.runners.progress_log import format_exchange, item_expected, item_question


def test_long_context_question_skips_the_document():
    item = {
        "needle": "NEEDLE-1",
        "prompt_template": "Retrieve the code.",
        "document": "HAYSTACK " * 50,
    }
    question = item_question(item)
    assert question == "Retrieve the code."
    assert "HAYSTACK" not in question
    assert item_expected(item) == "NEEDLE-1"


def test_exchange_includes_question_answer_and_expected():
    text = format_exchange(
        3,
        100,
        {
            "item_id": "mmlu-3",
            "passed": False,
            "raw_answer": "C",
        },
        "What is 2+2?\nA. 3\nB. 4",
        "B",
    )
    assert text.startswith("[3/100] FAIL mmlu-3")
    assert "Q: What is 2+2?" in text
    assert "A: C" in text
    assert "expected: B" in text


def test_exchange_marks_scorer_errors():
    text = format_exchange(
        1,
        5,
        {"item_id": "x", "scorer_error": True, "raw_answer": ""},
        "prompt",
        None,
    )
    assert "ERROR x" in text
    assert "A: (empty)" in text
    assert "expected:" not in text
