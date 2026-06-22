"""Runtime patches for litebench task bugs."""

from __future__ import annotations

import string
from collections.abc import Iterable

from datasets import load_dataset

from litebench.core.models import Sample
from litebench.tasks.truthfulqa import TruthfulQATask

# LiteBench labels choices A–H (8 options). Cap sample count accordingly.
_TRUTHFULQA_MAX_SAMPLES = 8
_TRUTHFULQA_LETTERS = list(string.ascii_uppercase[:_TRUTHFULQA_MAX_SAMPLES])


def _truthfulqa_load_samples(
    self: TruthfulQATask,
    n: int | None = None,
    split: str = "validation",
) -> Iterable[Sample]:
    if n is not None:
        n = min(n, _TRUTHFULQA_MAX_SAMPLES)
    actual_split = "validation" if split == "test" else split
    ds = load_dataset(
        "truthfulqa/truthful_qa", "multiple_choice", split=actual_split, streaming=True
    )
    taken = 0
    for i, row in enumerate(ds):
        if n is not None and taken >= n:
            break
        mc1 = row["mc1_targets"]
        choices = mc1["choices"]
        labels = mc1["labels"]
        if len(choices) > len(_TRUTHFULQA_LETTERS):
            continue
        try:
            correct_idx = labels.index(1)
        except ValueError:
            continue
        if correct_idx >= len(choices):
            continue
        yield Sample(
            id=f"truthfulqa-{i}",
            input=row["question"],
            target=_TRUTHFULQA_LETTERS[correct_idx],
            metadata={"choices": choices},
        )
        taken += 1


def _truthfulqa_build_prompt(self: TruthfulQATask, sample: Sample) -> str:
    choices = sample.metadata["choices"]
    lines = [f"Question: {sample.input}", "", "Choices:"]
    lines += [f"{_TRUTHFULQA_LETTERS[i]}. {c}" for i, c in enumerate(choices)]
    return "\n".join(lines)


def apply_litebench_patches() -> None:
    """Apply BenchBase fixes for known litebench 0.3.x task bugs."""
    import litebench.tasks.truthfulqa as truthfulqa_mod

    truthfulqa_mod._LETTERS = _TRUTHFULQA_LETTERS
    TruthfulQATask.load_samples = _truthfulqa_load_samples
    TruthfulQATask.build_prompt = _truthfulqa_build_prompt
