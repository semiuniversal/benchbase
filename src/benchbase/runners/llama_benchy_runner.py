"""In-process llama-benchy entry point with BenchBase stream parser fix."""

from __future__ import annotations

import asyncio
import datetime
import sys

from benchbase.runners.llama_benchy_fix import apply_llama_benchy_stream_fix
from benchbase.runners.llama_benchy_results_patch import apply_llama_benchy_results_patch

apply_llama_benchy_stream_fix()
apply_llama_benchy_results_patch()

from llama_benchy import __version__
from llama_benchy.client import LLMClient
from llama_benchy.config import BenchmarkConfig
from llama_benchy.corpus import TokenizedCorpus
from llama_benchy.prompts import PromptGenerator
from llama_benchy.runner import BenchmarkRunner


async def main_async() -> None:
    config = BenchmarkConfig.from_args()

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"llama-benchy ({__version__})")
    print(f"Date: {current_time}")
    print(f"Benchmarking model: {config.model} at {config.base_url}")
    print(f"Concurrency levels: {config.concurrency_levels}")

    corpus = TokenizedCorpus(config.book_url, config.tokenizer, config.model)
    print(f"Total tokens available in text corpus: {len(corpus)}")

    prompt_gen = PromptGenerator(corpus)
    client = LLMClient(
        config.base_url,
        config.api_key,
        config.served_model_name,
        config.extra_body,
        config.exact_tg,
    )
    runner = BenchmarkRunner(config, client, prompt_gen)
    await runner.run_suite()

    print(f"\nllama-benchy ({__version__})")
    print(f"date: {current_time} | latency mode: {config.latency_mode}")


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
