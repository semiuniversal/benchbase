"""Stream lm-eval prompts and model outputs to stdout for BenchBase run logs."""

from __future__ import annotations

import itertools
from typing import Any

from benchbase.runners.sample_transcript import _prompt_from_messages, log_lm_eval_exchange


def _log_model_call(
    self: Any,
    *,
    index: int,
    generate: bool,
    messages: Any,
    result: Any,
) -> None:
    """Best-effort logging; must never raise into lm-eval."""
    try:
        if not generate:
            # Loglikelihood requests use token IDs and need ctxlens inside lm-eval.
            # Re-parsing here caused crashes; skip MC logprobs streaming.
            return

        prompt = _prompt_from_messages(messages)
        parsed = (
            self.parse_generations(outputs=result)
            if result is not None
            else None
        )
        log_lm_eval_exchange(
            index=index,
            generate=True,
            prompt=prompt,
            response=parsed,
        )
    except Exception as exc:
        print(f"[benchbase] lm-eval log #{index} skipped: {exc}", flush=True)


def apply_lm_eval_log_patch() -> None:
    from lm_eval.models.api_models import TemplateAPI

    if getattr(TemplateAPI, "_benchbase_log_patch_applied", False):
        return

    original_model_call = TemplateAPI.model_call
    original_amodel_call = TemplateAPI.amodel_call
    counter = itertools.count(1)

    def model_call_patched(
        self: Any,
        messages: Any,
        *,
        generate: bool = True,
        gen_kwargs: dict | None = None,
        **kwargs: Any,
    ) -> Any:
        result = original_model_call(
            self,
            messages,
            generate=generate,
            gen_kwargs=gen_kwargs,
            **kwargs,
        )
        _log_model_call(
            self,
            index=next(counter),
            generate=generate,
            messages=messages,
            result=result,
        )
        return result

    async def amodel_call_patched(
        self: Any,
        session: Any,
        sem: Any,
        messages: Any,
        *,
        generate: bool = True,
        cache_keys: list | None = None,
        ctxlens: list | None = None,
        gen_kwargs: dict | None = None,
        **kwargs: Any,
    ) -> Any:
        answers = await original_amodel_call(
            self,
            session,
            sem,
            messages,
            generate=generate,
            cache_keys=cache_keys,
            ctxlens=ctxlens,
            gen_kwargs=gen_kwargs,
            **kwargs,
        )
        if generate:
            try:
                prompt = _prompt_from_messages(messages)
                log_lm_eval_exchange(
                    index=next(counter),
                    generate=True,
                    prompt=prompt,
                    response=answers,
                )
            except Exception as exc:
                print(f"[benchbase] lm-eval async log skipped: {exc}", flush=True)
        return answers

    TemplateAPI.model_call = model_call_patched  # type: ignore[method-assign]
    TemplateAPI.amodel_call = amodel_call_patched  # type: ignore[method-assign]
    TemplateAPI._benchbase_log_patch_applied = True
