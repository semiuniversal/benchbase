"""Offline-safe corpus loading for llama-benchy in Docker."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import requests

from llama_benchy.corpus import TokenizedCorpus

BUNDLED_CORPUS = Path("/app/corpus/sherlock1661.txt")
REPO_CORPUS = (
    Path(__file__).resolve().parent.parent.parent.parent / "docker" / "corpus" / "sherlock1661.txt"
)
DEFAULT_BOOK_URL = "https://www.gutenberg.org/files/1661/1661-0.txt"


def default_corpus_source() -> str:
    """Prefer bundled local corpus; fall back to Gutenberg URL when online."""
    if BUNDLED_CORPUS.is_file():
        return str(BUNDLED_CORPUS)
    if REPO_CORPUS.is_file():
        return str(REPO_CORPUS)
    return DEFAULT_BOOK_URL


def _cache_dir() -> Path:
    data_dir = os.environ.get("BENCHBASE_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "llama-benchy-cache"
    return Path.home() / ".cache" / "llama-benchy"


def _trim_gutenberg(text: str) -> str:
    start_idx = text.find("*** START OF THE PROJECT GUTENBERG EBOOK")
    if start_idx != -1:
        return text[start_idx:]
    return text


def _read_corpus_text(source: str) -> str:
    path = Path(source)
    if path.is_file():
        print(f"Loading text from local corpus: {path}")
        return _trim_gutenberg(path.read_text(encoding="utf-8"))

    cache_dir = _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.md5(source.encode()).hexdigest()
    cache_file = cache_dir / f"{url_hash}.txt"

    if cache_file.is_file():
        print(f"Loading text from cache: {cache_file}")
        return cache_file.read_text(encoding="utf-8")

    if BUNDLED_CORPUS.is_file():
        print(f"Network corpus unavailable; using bundled file: {BUNDLED_CORPUS}")
        text = _trim_gutenberg(BUNDLED_CORPUS.read_text(encoding="utf-8"))
        cache_file.write_text(text, encoding="utf-8")
        return text

    print(f"Downloading book from {source}...")
    response = requests.get(source, timeout=120)
    response.raise_for_status()
    text = _trim_gutenberg(response.text)
    cache_file.write_text(text, encoding="utf-8")
    print(f"Saved text to cache: {cache_file}")
    return text


def _load_data_patched(self: TokenizedCorpus) -> list[int]:
    try:
        text = _read_corpus_text(self.book_url)
        return self.tokenizer.encode(text, add_special_tokens=False)
    except Exception as exc:
        print(f"Error downloading or processing book: {exc}")
        sys.exit(1)


def apply_llama_benchy_corpus_patch() -> None:
    """Allow local/bundled corpus files and cache under BENCHBASE_DATA_DIR."""
    TokenizedCorpus._load_data = _load_data_patched  # type: ignore[method-assign]
