"""Stream lm-eval prompts and model outputs to stdout for BenchBase run logs."""

from __future__ import annotations

import itertools
from typing import Any

from benchbase.runners.sample_transcript import _prompt_from_messages, log_lm_eval_exchange


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
        index = next(counter)
        prompt = _prompt_from_messages(messages)
        if generate:
            parsed = (
                self.parse_generations(outputs=result)
                if result is not None
                else None
            )
            log_lm_eval_exchange(
                index=index, generate=True, prompt=prompt, response=parsed
            )
        else:
            ctxlens = kwargs.get("ctxlens")
            parsed = (
                self.parse_logprobs(
                    outputs=result,
                    tokens=messages,
                    ctxlens=ctxlens,
                )
                if result is not None
                else None
            )
            log_lm_eval_exchange(
                index=index, generate=False, prompt=prompt, response=parsed
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
        index = next(counter)
        prompt = _prompt_from_messages(messages)
        log_lm_eval_exchange(
            index=index,
            generate=generate,
            prompt=prompt,
            response=answers,
        )
        return answers

    TemplateAPI.model_call = model_call_patched  # type: ignore[method-assign]
    TemplateAPI.amodel_call = amodel_call_patched  # type: ignore[method-assign]
    TemplateAPI._benchbase_log_patch_applied = True
