"""Format benchmark Q&A for live run log streaming."""

from __future__ import annotations

import json
from typing import Any

# Keep logs readable in the UI without flooding SSE clients.
DEFAULT_MAX_CHARS = 4000
CODE_MAX_CHARS = 6000


def truncate_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars // 2
    omitted = len(text) - head - tail
    return f"{text[:head]}\n... [{omitted} chars omitted] ...\n{text[-tail:]}"


def _format_target(target: str | list[str]) -> str:
    if isinstance(target, list):
        return "\n".join(str(item) for item in target)
    return str(target)


def _print_block(label: str, body: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> None:
    if not body.strip():
        return
    print(f"{label}:", flush=True)
    print(truncate_text(body, max_chars), flush=True)


def log_litebench_sample(done: int, total: int, result: Any) -> None:
    """Print a HumanEval / litebench sample transcript to stdout."""
    status = "PASS" if result.correct else "FAIL"
    score = getattr(result, "score", None)
    score_bit = f" score={score:.2f}" if isinstance(score, (int, float)) else ""
    print(
        f"\n--- [{done}/{total}] {result.sample_id} {status}{score_bit} "
        f"({result.latency_ms}ms) ---",
        flush=True,
    )

    if getattr(result, "error", None):
        print(f"ERROR: {result.error}", flush=True)

    _print_block("PROMPT", result.input, max_chars=CODE_MAX_CHARS)
    _print_block("MODEL", result.prediction or "", max_chars=CODE_MAX_CHARS)

    target = _format_target(result.target)
    if target.strip():
        label = "EXPECTED" if result.correct else "EXPECTED (reference)"
        _print_block(label, target, max_chars=CODE_MAX_CHARS)

    tool_calls = getattr(result, "tool_calls", None)
    if tool_calls:
        print("TOOL CALLS:", flush=True)
        for index, call in enumerate(tool_calls, start=1):
            name = call.get("name", "?")
            args = call.get("arguments", call.get("args", ""))
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False)
            out = call.get("result", call.get("output", ""))
            err = call.get("error")
            print(f"  [{index}] {name}({truncate_text(str(args), 500)})", flush=True)
            if out:
                _print_block("    result", str(out), max_chars=1500)
            if err:
                print(f"    error: {err}", flush=True)

    steps = getattr(result, "steps", 0)
    if steps and steps > 1:
        print(f"AGENT STEPS: {steps}", flush=True)

    print("---", flush=True)


def _prompt_from_messages(messages: Any) -> str:
    if messages is None:
        return ""
    if isinstance(messages, str):
        return messages
    if isinstance(messages, list):
        if not messages:
            return ""
        if all(isinstance(item, str) for item in messages):
            return messages[0] if len(messages) == 1 else "\n---\n".join(messages)
        if hasattr(messages[0], "prompt"):
            return str(messages[0].prompt)
    return str(messages)


def log_lm_eval_exchange(
    *,
    index: int,
    generate: bool,
    prompt: str,
    response: Any,
) -> None:
    """Print one lm-eval API exchange to stdout."""
    kind = "GENERATE" if generate else "LOGPROBS"
    print(f"\n--- [lm-eval #{index}] {kind} ---", flush=True)
    _print_block("PROMPT", prompt)

    if generate:
        if isinstance(response, list):
            for idx, text in enumerate(response, start=1):
                prefix = f"MODEL[{idx}]" if len(response) > 1 else "MODEL"
                _print_block(prefix, str(text))
        elif response is None:
            print("MODEL: (null response)", flush=True)
        else:
            _print_block("MODEL", str(response))
    else:
        if isinstance(response, list):
            for idx, item in enumerate(response, start=1):
                if isinstance(item, tuple) and len(item) >= 2:
                    logprob, greedy = item[0], item[1]
                    print(
                        f"  [{idx}] logprob={logprob:.4f} greedy={greedy}",
                        flush=True,
                    )
                else:
                    print(f"  [{idx}] {item}", flush=True)
        else:
            print(f"RESULT: {response}", flush=True)

    print("---", flush=True)
