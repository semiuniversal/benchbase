"""Use a fill-in coherence probe instead of a one-word trivia ask.

Diffusion LMs (and some chat models) often emit empty / early-EOS replies for
\"reply with one word only\" prompts while still completing sentence-shaped
text reliably. The fill-in form keeps the same Paris check for ordinary models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp

from llama_benchy.client import LLMClient

_COHERENCE_PROMPT = "Complete the sentence: The capital of France is"


async def _run_coherence_test_fill_in(self: LLMClient, session: aiohttp.ClientSession) -> bool:
    """Run coherence test after warmup to verify model responds correctly."""
    print("\nRunning coherence test...")
    payload = {
        "model": self.model_name,
        "messages": [{"role": "user", "content": _COHERENCE_PROMPT}],
        "max_tokens": 512,
    }

    try:
        async with session.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=self.headers,
        ) as response:
            response_json = await response.json()

            if "choices" not in response_json or len(response_json["choices"]) == 0:
                print("Coherence test FAILED: No choices in response")
                return False

            choice = response_json["choices"][0].get("message", {})
            content = choice.get("content") or ""
            reasoning = choice.get("reasoning") or choice.get("reasoning_content") or ""
            full_content = (content + reasoning).lower()

            if "paris" in full_content:
                print("Coherence test PASSED.")
                return True

            shown = (content or "").strip() or "(empty)"
            print(f"Coherence test FAILED: Expected 'Paris'. Got: {shown[:200]}")
            return False
    except Exception as e:
        print(f"Coherence test FAILED with error: {e}")
        return False


def apply_llama_benchy_coherence_patch() -> None:
    """Replace one-word coherence probe with a sentence fill-in (safe to call repeatedly)."""
    LLMClient.run_coherence_test = _run_coherence_test_fill_in
