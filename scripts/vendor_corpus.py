#!/usr/bin/env python3
"""Vendor BenchBase v2 suite corpora into corpus/suites/<axis>/v2/.

Downloads tinyBenchmarks IRT anchors, LiveCodeBench, BFCL, and IFEval snapshots,
authors the structured ladder and seeded NIAH items, and writes MANIFEST.json
files. Committed artifacts are the source of truth; re-run to rebuild/audit.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "corpus" / "suites"
VERSION = "v2"
SNAPSHOT_DATE = date.today().isoformat()
LETTERS = "ABCD"

# LiveCodeBench: keep problems at or after this date (contamination-minded default).
LCB_CUTOFF = "2024-01-01"
LCB_TARGET = {"easy": 15, "medium": 15, "hard": 15}  # 45 total; smoke uses first 5


def _hash_items(items: list[dict[str, Any]]) -> str:
    blob = json.dumps(items, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _write_suite(
    axis: str,
    items: list[dict[str, Any]],
    *,
    source: str,
    license_name: str,
    notes: dict[str, Any] | None = None,
    extra_manifest: dict[str, Any] | None = None,
    version: str = VERSION,
) -> None:
    dest = OUT / axis / version
    dest.mkdir(parents=True, exist_ok=True)
    payload = {"version": version, "items": items}
    (dest / "items.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    content_hash = _hash_items(items)
    manifest = {
        "axis": axis,
        "suite_version": version,
        "source": source,
        "snapshot_date": SNAPSHOT_DATE,
        "license": license_name,
        "item_count": len(items),
        "content_hash": content_hash,
        "notes": notes or {},
        **(extra_manifest or {}),
    }
    (dest / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[ok] {axis}/{version}: {len(items)} items hash={content_hash[:12]}")


def _mc_prompt(question: str, choices: list[str], *, subject: str | None = None) -> str:
    lines = []
    if subject:
        lines.append(f"Subject: {subject}")
    lines.append(question.strip())
    for i, c in enumerate(choices[:4]):
        lines.append(f"{LETTERS[i]}) {c}")
    lines.append("Answer with A, B, C, or D only.")
    return "\n".join(lines)


def vendor_tiny_mmlu() -> None:
    from datasets import load_dataset

    ds = load_dataset("tinyBenchmarks/tinyMMLU")["test"]
    assert len(ds) == 100, f"expected 100 tinyMMLU anchors, got {len(ds)}"
    items = []
    anchor_ids = []
    for i, row in enumerate(ds):
        choices = list(row["choices"])
        ans_idx = int(row["answer"])
        item_id = f"tinymmlu_{i:03d}"
        anchor_ids.append(item_id)
        items.append(
            {
                "item_id": item_id,
                "source_index": i,
                "subject": row.get("subject"),
                "question": row["question"],
                "choices": choices,
                "prompt": _mc_prompt(row["question"], choices, subject=row.get("subject")),
                "answer": LETTERS[ans_idx],
            }
        )
    # Spot-check: order-preserving 100 anchors (tinyBenchmarks test split IS the IRT set).
    assert [it["source_index"] for it in items] == list(range(100))
    _write_suite(
        "knowledge",
        items,
        source="huggingface:tinyBenchmarks/tinyMMLU@test",
        license_name="See tinyBenchmarks / MMLU upstream licenses",
        notes={
            "anchor_set": "tinyBenchmarks IRT anchors (100)",
            "anchor_ids": anchor_ids,
            "irt_deferred": True,
        },
        extra_manifest={"hf_dataset": "tinyBenchmarks/tinyMMLU", "hf_split": "test"},
    )


def vendor_tiny_arc() -> None:
    from datasets import load_dataset

    ds = load_dataset("tinyBenchmarks/tinyAI2_arc")["test"]
    assert len(ds) == 100, f"expected 100 tinyARC anchors, got {len(ds)}"
    items = []
    anchor_ids = []
    for i, row in enumerate(ds):
        labels = list(row["choices"]["label"])
        texts = list(row["choices"]["text"])
        # Normalize to A-D by label order.
        paired = list(zip(labels, texts))
        paired.sort(key=lambda x: x[0])
        choices = [t for _, t in paired[:4]]
        key = str(row["answerKey"]).strip().upper()
        if key.isdigit():
            key = LETTERS[int(key) - 1]
        item_id = str(row.get("id") or f"tinyarc_{i:03d}")
        anchor_ids.append(item_id)
        items.append(
            {
                "item_id": item_id,
                "source_index": i,
                "question": row["question"],
                "choices": choices,
                "prompt": _mc_prompt(row["question"], choices),
                "answer": key if key in LETTERS else LETTERS[0],
            }
        )
    assert [it["source_index"] for it in items] == list(range(100))
    _write_suite(
        "reasoning",
        items,
        source="huggingface:tinyBenchmarks/tinyAI2_arc@test",
        license_name="See tinyBenchmarks / AI2 ARC upstream licenses",
        notes={
            "anchor_set": "tinyBenchmarks IRT anchors (100)",
            "anchor_ids": anchor_ids,
            "irt_deferred": True,
        },
        extra_manifest={"hf_dataset": "tinyBenchmarks/tinyAI2_arc", "hf_split": "test"},
    )


def _gsm8k_final(answer: str) -> str:
    m = re.search(r"####\s*(-?\d+(?:\.\d+)?)", answer.replace(",", ""))
    if m:
        return m.group(1)
    nums = re.findall(r"-?\d+(?:\.\d+)?", answer.replace(",", ""))
    return nums[-1] if nums else ""


def vendor_tiny_gsm8k() -> None:
    from datasets import load_dataset

    ds = load_dataset("tinyBenchmarks/tinyGSM8k")["test"]
    assert len(ds) == 100, f"expected 100 tinyGSM8k anchors, got {len(ds)}"
    items = []
    for i, row in enumerate(ds):
        gold = _gsm8k_final(row["answer"])
        items.append(
            {
                "item_id": f"tinygsm8k_{i:03d}",
                "source_index": i,
                "question": row["question"],
                "prompt": (
                    f"{row['question'].strip()}\n\n"
                    "Show your work. Put the final numeric answer on the last line "
                    "after #### (GSM8K convention)."
                ),
                "answer": gold,
            }
        )
    assert [it["source_index"] for it in items] == list(range(100))
    _write_suite(
        "math",
        items,
        source="huggingface:tinyBenchmarks/tinyGSM8k@test",
        license_name="See tinyBenchmarks / GSM8K upstream licenses",
        notes={"anchor_set": "tinyBenchmarks IRT anchors (100)", "irt_deferred": True},
        extra_manifest={"hf_dataset": "tinyBenchmarks/tinyGSM8k", "hf_split": "test"},
    )


def vendor_livecodebench() -> None:
    from huggingface_hub import hf_hub_download

    # Prefer latest release file; fall back through older shards.
    rows: list[dict[str, Any]] = []
    used_files: list[str] = []
    for fname in ["test6.jsonl", "test5.jsonl", "test4.jsonl", "test3.jsonl"]:
        try:
            path = hf_hub_download(
                "livecodebench/code_generation_lite", fname, repo_type="dataset"
            )
        except Exception:
            continue
        used_files.append(fname)
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
        if rows:
            break
    if not rows:
        raise RuntimeError("Failed to download LiveCodeBench jsonl")

    by_diff: dict[str, list] = defaultdict(list)
    for row in rows:
        cdate = (row.get("contest_date") or "")[:10]
        if cdate and cdate < LCB_CUTOFF:
            continue
        diff = (row.get("difficulty") or "medium").lower()
        if diff not in LCB_TARGET:
            continue
        public = row.get("public_test_cases") or "[]"
        if isinstance(public, str):
            try:
                tests = json.loads(public)
            except json.JSONDecodeError:
                continue
        else:
            tests = public
        if not tests:
            continue
        # Prefer stdin harness tests.
        stdin_tests = [t for t in tests if t.get("testtype") == "stdin" or "input" in t]
        if not stdin_tests:
            continue
        by_diff[diff].append((cdate, row, stdin_tests))

    selected: list[dict[str, Any]] = []
    for diff, need in LCB_TARGET.items():
        pool = sorted(by_diff[diff], key=lambda x: x[0] or "")
        # Take a spread: newest-first for harder contamination resistance.
        pool = list(reversed(pool))
        for cdate, row, tests in pool[:need]:
            harness_tests = [
                {"input": t.get("input", ""), "output": str(t.get("output", "")).rstrip("\n")}
                for t in tests[:8]
            ]
            starter = row.get("starter_code") or ""
            prompt = (
                f"Solve the following programming problem in Python 3.\n\n"
                f"Title: {row.get('question_title')}\n"
                f"Platform: {row.get('platform')} · Difficulty: {diff}\n\n"
                f"{row.get('question_content')}\n\n"
            )
            if starter.strip():
                prompt += f"Starter code:\n```python\n{starter}\n```\n\n"
            prompt += (
                "Write a complete Python solution that reads from stdin and writes to stdout. "
                "Put the solution in a ```python``` code block."
            )
            selected.append(
                {
                    "item_id": str(row.get("question_id") or f"lcb_{len(selected)}"),
                    "difficulty": diff,
                    "contest_date": cdate,
                    "platform": row.get("platform"),
                    "prompt": prompt,
                    "tests": harness_tests,
                    "harness": "stdin",
                    "entry_point": None,
                }
            )

    # Stable order: easy → medium → hard (smoke prefix = easy first 5).
    order = {"easy": 0, "medium": 1, "hard": 2}
    selected.sort(key=lambda x: (order.get(x["difficulty"], 9), x["contest_date"], x["item_id"]))
    if len(selected) < 40:
        raise RuntimeError(f"LiveCodeBench selection too small: {len(selected)}")

    _write_suite(
        "coding",
        selected,
        source="huggingface:livecodebench/code_generation_lite",
        license_name="LiveCodeBench (see upstream dataset card)",
        notes={
            "date_filter": f"contest_date >= {LCB_CUTOFF}",
            "tests": "public_test_cases only (stdin harness)",
            "stratification": dict(LCB_TARGET),
            "files": used_files,
        },
        extra_manifest={"cutoff_date": LCB_CUTOFF, "hf_dataset": "livecodebench/code_generation_lite"},
    )


def _bfcl_load_jsonl(name: str) -> list[dict[str, Any]]:
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(
        "gorilla-llm/Berkeley-Function-Calling-Leaderboard", name, repo_type="dataset"
    )
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _bfcl_gt_to_expect(gt: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert BFCL ground_truth entry to list of {name, arguments} with preferred values."""
    calls: list[dict[str, Any]] = []
    for entry in gt.get("ground_truth") or []:
        if isinstance(entry, str):
            # multi-turn python-style call strings — skip for first-turn JSON mode
            continue
        if not isinstance(entry, dict):
            continue
        for name, params in entry.items():
            args: dict[str, Any] = {}
            if isinstance(params, dict):
                for k, opts in params.items():
                    if isinstance(opts, list) and opts:
                        # Prefer first non-empty option.
                        val = next((o for o in opts if o != ""), opts[0])
                        args[k] = val
                    else:
                        args[k] = opts
            calls.append({"name": name, "arguments": args})
    return calls


def vendor_bfcl() -> None:
    categories = {
        "simple": ("BFCL_v3_simple.json", "possible_answer/BFCL_v3_simple.json"),
        "multiple": ("BFCL_v3_multiple.json", "possible_answer/BFCL_v3_multiple.json"),
        "parallel": ("BFCL_v3_parallel.json", "possible_answer/BFCL_v3_parallel.json"),
        "irrelevance": ("BFCL_v3_irrelevance.json", None),
        "multi_turn": ("BFCL_v3_multi_turn_base.json", "possible_answer/BFCL_v3_multi_turn_base.json"),
    }
    items: list[dict[str, Any]] = []
    per_cat = 25

    # Function docs for multi-turn
    from huggingface_hub import hf_hub_download

    func_docs: dict[str, Any] = {}
    for doc in [
        "gorilla_file_system.json",
        "math_api.json",
        "message_api.json",
        "posting_api.json",
        "ticket_api.json",
        "trading_bot.json",
        "travel_booking.json",
        "vehicle_control.json",
    ]:
        try:
            p = hf_hub_download(
                "gorilla-llm/Berkeley-Function-Calling-Leaderboard",
                f"multi_turn_func_doc/{doc}",
                repo_type="dataset",
            )
            func_docs[doc.replace(".json", "")] = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            pass

    for cat, (prob_file, ans_file) in categories.items():
        probs = _bfcl_load_jsonl(prob_file)
        answers = {a["id"]: a for a in (_bfcl_load_jsonl(ans_file) if ans_file else [])}
        taken = 0
        for row in probs:
            if taken >= per_cat:
                break
            rid = row["id"]
            if cat == "multi_turn":
                # First user turn only; functions from involved classes if available.
                turns = row.get("question") or []
                if not turns or not turns[0]:
                    continue
                user_msg = turns[0][0].get("content", "")
                tools = []
                for cls in row.get("involved_classes") or []:
                    # Map class name loosely to func doc keys.
                    key = None
                    for k in func_docs:
                        if k.replace("_", "").lower() in cls.replace("_", "").lower() or cls.lower() in k.lower():
                            key = k
                            break
                    if key:
                        doc = func_docs[key]
                        if isinstance(doc, list):
                            tools.extend(doc)
                        elif isinstance(doc, dict):
                            tools.append(doc)
                gt = answers.get(rid, {})
                # First turn ground truth is list of python-call strings — mark expected names.
                first = (gt.get("ground_truth") or [[]])[0]
                expected_names = []
                for call in first:
                    if isinstance(call, str):
                        m = re.match(r"([A-Za-z0-9_\.]+)\(", call)
                        if m:
                            expected_names.append(m.group(1))
                prompt = (
                    "You are a function-calling assistant. Available tools are described below.\n"
                    f"{json.dumps(tools[:12], ensure_ascii=False)[:4000]}\n\n"
                    f"User: {user_msg}\n\n"
                    'Respond with ONLY JSON: {"name":"...","arguments":{...}} '
                    "for the first required tool call."
                )
                items.append(
                    {
                        "item_id": rid,
                        "category": cat,
                        "prompt": prompt,
                        "tools": tools[:12],
                        "expected_name": expected_names[0] if expected_names else None,
                        "expected_args": None,  # name-only match for multi-turn first call
                        "expected_names_any": expected_names,
                        "match_mode": "name_only",
                    }
                )
                taken += 1
                continue

            # Single-turn categories
            q = row.get("question") or []
            user_msg = ""
            if q and q[0] and isinstance(q[0][0], dict):
                user_msg = q[0][0].get("content", "")
            tools = row.get("function") or []
            if cat == "irrelevance":
                prompt = (
                    "You are given tools, but the user request may be answerable without them. "
                    "If no tool is appropriate, reply with plain text and do NOT emit a tool call.\n"
                    f"Tools: {json.dumps(tools, ensure_ascii=False)[:3000]}\n\n"
                    f"User: {user_msg}"
                )
                items.append(
                    {
                        "item_id": rid,
                        "category": cat,
                        "prompt": prompt,
                        "tools": tools,
                        "expected_name": None,
                        "expected_args": None,
                        "match_mode": "irrelevance",
                    }
                )
                taken += 1
                continue

            gt = answers.get(rid)
            if not gt:
                continue
            expects = _bfcl_gt_to_expect(gt)
            if not expects:
                continue
            primary = expects[0]
            extra = (
                " You may need multiple tools; emit a JSON array of calls if needed."
                if cat in ("parallel", "multiple")
                else ""
            )
            prompt = (
                "You are a function-calling assistant. Use the tools below when appropriate.\n"
                f"Tools: {json.dumps(tools, ensure_ascii=False)[:3500]}\n\n"
                f"User: {user_msg}\n\n"
                'Respond with ONLY JSON: {"name":"...","arguments":{...}}'
                f"{extra}"
            )
            items.append(
                {
                    "item_id": rid,
                    "category": cat,
                    "prompt": prompt,
                    "tools": tools,
                    "expected_name": primary["name"],
                    "expected_args": primary["arguments"],
                    "expected_calls": expects,
                    "match_mode": "name_args" if cat == "simple" else "name_args_primary",
                }
            )
            taken += 1

        if taken < per_cat:
            print(f"[warn] BFCL {cat}: only {taken}/{per_cat}", file=sys.stderr)

    # Stable category order for smoke prefix diversity.
    cat_order = {"simple": 0, "multiple": 1, "parallel": 2, "irrelevance": 3, "multi_turn": 4}
    items.sort(key=lambda x: (cat_order.get(x["category"], 9), x["item_id"]))
    _write_suite(
        "tool_calling",
        items,
        source="huggingface:gorilla-llm/Berkeley-Function-Calling-Leaderboard (BFCL v3)",
        license_name="Apache-2.0",
        notes={
            "categories": list(categories),
            "per_category": per_cat,
            "multi_turn": "first-turn only subset of BFCL_v3_multi_turn_base",
        },
        extra_manifest={"hf_dataset": "gorilla-llm/Berkeley-Function-Calling-Leaderboard", "bfcl_version": "v3"},
    )


def _ifeval_rule(instruction_ids: list[str], kwargs: list[dict]) -> dict[str, Any] | None:
    """Map a subset of IFEval instruction ids to our rule checker."""
    for iid, kw in zip(instruction_ids, kwargs or []):
        kw = kw or {}
        if iid == "length_constraints:number_words":
            return {"type": "word_count", "n": int(kw.get("num_words") or 0)}
        if iid == "keywords:forbidden_words":
            return {"type": "forbidden_words", "words": list(kw.get("forbidden_words") or [])}
        if iid == "keywords:existence":
            return {"type": "required_words", "words": list(kw.get("keywords") or [])}
        if iid == "change_case:english_capital":
            return {"type": "all_caps"}
        if iid == "change_case:english_lowercase":
            return {"type": "all_lowercase"}
        if iid == "punctuation:no_comma":
            return {"type": "no_comma"}
        if iid == "startend:end_checker":
            return {"type": "ends_with", "value": str(kw.get("end_phrase") or "")}
        if iid == "startend:quotation":
            return {"type": "wrapped_quotes"}
        if iid == "detectable_format:number_highlighted_sections":
            return {"type": "min_highlights", "n": int(kw.get("num_highlights") or 1)}
        if iid == "detectable_format:title":
            return {"type": "has_title"}
        if iid == "length_constraints:number_paragraphs":
            return {"type": "paragraph_count", "n": int(kw.get("num_paragraphs") or 0)}
        if iid == "length_constraints:number_sentences":
            return {"type": "sentence_count", "n": int(kw.get("num_sentences") or 0)}
        if iid == "detectable_content:number_placeholders":
            return {"type": "placeholder_count", "n": int(kw.get("num_placeholders") or 0)}
    return None


def vendor_ifeval() -> None:
    from datasets import load_dataset

    ds = load_dataset("google/IFEval")["train"]
    items = []
    for row in ds:
        ids = list(row["instruction_id_list"] or [])
        kwargs = list(row["kwargs"] or [])
        rule = _ifeval_rule(ids, kwargs)
        if not rule:
            continue
        items.append(
            {
                "item_id": f"ifeval_{row['key']}",
                "prompt": row["prompt"],
                "instruction_id_list": ids,
                "rule": rule,
            }
        )
        if len(items) >= 50:
            break
    if len(items) < 50:
        raise RuntimeError(f"IFEval subset too small: {len(items)}")
    _write_suite(
        "instruction",
        items,
        source="huggingface:google/IFEval",
        license_name="See google/IFEval dataset card",
        notes={"subset": "first 50 items with supported rule types", "rule_coverage": True},
        extra_manifest={"hf_dataset": "google/IFEval"},
    )


def vendor_structured() -> None:
    """Authored graded schema ladder (spec §4 axis 7)."""
    schemas = [
        # Flat
        {
            "id": "flat_person",
            "level": "flat",
            "schema": {
                "type": "object",
                "required": ["name", "age"],
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
            },
            "ask": "Return a JSON object for a person named Ada with age 36.",
        },
        {
            "id": "flat_product",
            "level": "flat",
            "schema": {
                "type": "object",
                "required": ["sku", "price", "in_stock"],
                "properties": {
                    "sku": {"type": "string"},
                    "price": {"type": "number"},
                    "in_stock": {"type": "boolean"},
                },
            },
            "ask": "Return a JSON product with sku 'AB-9', price 12.5, in_stock true.",
        },
        # Nested
        {
            "id": "nested_user",
            "level": "nested",
            "schema": {
                "type": "object",
                "required": ["user", "meta"],
                "properties": {
                    "user": {
                        "type": "object",
                        "required": ["id", "email"],
                        "properties": {
                            "id": {"type": "integer"},
                            "email": {"type": "string"},
                        },
                    },
                    "meta": {
                        "type": "object",
                        "required": ["source"],
                        "properties": {"source": {"type": "string"}},
                    },
                },
            },
            "ask": "Return JSON with user{id:1,email:'a@b.co'} and meta{source:'web'}.",
        },
        {
            "id": "nested_order",
            "level": "nested",
            "schema": {
                "type": "object",
                "required": ["order_id", "shipping"],
                "properties": {
                    "order_id": {"type": "string"},
                    "shipping": {
                        "type": "object",
                        "required": ["city", "zip"],
                        "properties": {
                            "city": {"type": "string"},
                            "zip": {"type": "string"},
                        },
                    },
                },
            },
            "ask": "Return an order JSON with order_id 'O1' and shipping city 'Paris' zip '75001'.",
        },
        # Arrays
        {
            "id": "array_tags",
            "level": "arrays",
            "schema": {
                "type": "object",
                "required": ["title", "tags"],
                "properties": {
                    "title": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
            },
            "ask": "Return JSON with title 'Note' and tags ['a','b','c'].",
        },
        {
            "id": "array_points",
            "level": "arrays",
            "schema": {
                "type": "object",
                "required": ["points"],
                "properties": {
                    "points": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["x", "y"],
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                            },
                        },
                    }
                },
            },
            "ask": "Return JSON with points [{x:0,y:0},{x:1,y:2}].",
        },
        # Enums / unions
        {
            "id": "enum_status",
            "level": "enums",
            "schema": {
                "type": "object",
                "required": ["status", "code"],
                "properties": {
                    "status": {"type": "string", "enum": ["ok", "error", "pending"]},
                    "code": {"type": "integer"},
                },
            },
            "ask": "Return JSON with status one of ok|error|pending and code 200.",
        },
        {
            "id": "union_payload",
            "level": "unions",
            "schema": {
                "type": "object",
                "required": ["kind", "value"],
                "properties": {
                    "kind": {"type": "string", "enum": ["text", "number"]},
                    "value": {},  # any — validated specially as str|number by runner via oneOf hint
                },
                "oneOf_hint": True,
            },
            "ask": "Return JSON {kind:'text', value:'hello'} matching kind enum text|number.",
        },
    ]

    # Expand to 30 by varying asks while keeping schemas.
    items: list[dict[str, Any]] = []
    variants = [
        "",
        " Use double quotes. No markdown.",
        " Output JSON only.",
        " Do not wrap in code fences.",
    ]
    i = 0
    while len(items) < 30:
        base = schemas[i % len(schemas)]
        v = variants[(len(items) // len(schemas)) % len(variants)]
        schema = base["schema"]
        prompt = (
            f"{base['ask']}{v}\n\n"
            f"The response must validate against this JSON Schema:\n"
            f"{json.dumps(schema)}"
        )
        # Do not put a gold instance in the prompt beyond what's asked — schema has no gold answer string.
        items.append(
            {
                "item_id": f"structured_{len(items):02d}_{base['id']}",
                "level": base["level"],
                "prompt": prompt,
                "schema": schema,
            }
        )
        i += 1

    _write_suite(
        "structured",
        items,
        source="benchbase-authored",
        license_name="Apache-2.0 (BenchBase)",
        notes={"ladder": ["flat", "nested", "arrays", "enums", "unions"], "count": 30},
    )


def vendor_long_context() -> None:
    """Harder long-context v3: no << >> markers, multi-needle, positions, VT."""
    seed = 20260815
    rng = random.Random(seed)
    version = "v3"
    lengths = [8000, 16000, 32000]
    positions = ("start", "middle", "end")
    items: list[dict[str, Any]] = []

    niah_prompt = (
        "You will be given a long document. Somewhere inside it is a special "
        "retrieval code that starts with NEEDLE-. Retrieve that code exactly. "
        "Reply with only the code."
    )
    for length in lengths:
        for position in positions:
            for i in range(4):
                needle = f"NEEDLE-{length}-{position[0].upper()}{i:02d}-{rng.randint(100000, 999999)}"
                items.append(
                    {
                        "item_id": f"niah_{length}_{position}_{i:02d}",
                        "kind": "niah",
                        "length": length,
                        "position": position,
                        "needle": needle,
                        "prompt_template": niah_prompt,
                    }
                )

    multi_prompt = (
        "You will be given a long document containing several labeled codes "
        "(ALPHA, BETA, GAMMA). Retrieve the requested label's code exactly. "
        "Reply with only that code."
    )
    labels = ("ALPHA", "BETA", "GAMMA")
    for length in lengths:
        for i in range(3):
            needles = {
                lab: f"{lab}-{length}-{i:02d}-{rng.randint(10000, 99999)}"
                for lab in labels
            }
            ask = labels[i % len(labels)]
            items.append(
                {
                    "item_id": f"multi_{length}_{i:02d}",
                    "kind": "multi_needle",
                    "length": length,
                    "position": "middle",
                    "needles": needles,
                    "ask_label": ask,
                    "needle": needles[ask],
                    "prompt_template": multi_prompt + f" Which code is labeled {ask}?",
                }
            )

    vt_prompt = (
        "You will be given a long document that includes a short variable-tracking "
        "snippet. Report the final value of the named variable. Reply with only "
        "the value."
    )
    for length in (8000, 16000, 32000):
        for i in range(4):
            names = [f"v{j}" for j in range(4)]
            values = [rng.randint(10, 99) for _ in names]
            # Rebind last name to an earlier value so tracking matters.
            final_name = names[-1]
            final_value = values[i % 3]
            lines = [f"Let {n} = {v}." for n, v in zip(names, values)]
            lines.append(f"Now set {final_name} = {names[i % 3]}.")
            items.append(
                {
                    "item_id": f"vt_{length}_{i:02d}",
                    "kind": "variable_tracking",
                    "length": length,
                    "position": positions[i % 3],
                    "snippet": " ".join(lines),
                    "ask_var": final_name,
                    "needle": str(final_value),
                    "prompt_template": (
                        vt_prompt + f" What is the final value of {final_name}?"
                    ),
                }
            )

    _write_suite(
        "long_context",
        items,
        source="benchbase-seeded-niah-v3",
        license_name="Apache-2.0 (BenchBase)",
        notes={
            "generator": "scripts/vendor_corpus.py::vendor_long_context",
            "seed": seed,
            "no_delimiters": True,
            "kinds": ["niah", "multi_needle", "variable_tracking"],
        },
        extra_manifest={
            "seed": seed,
            "lengths": lengths,
            "positions": list(positions),
            "tasks_per_length_niah": 12,
            "tasks_per_length_multi": 3,
            "tasks_per_length_vt": 4,
        },
        version=version,
    )


def vendor_smoke() -> None:
    """Format probes without gold leakage."""
    items = [
        {
            "item_id": "smoke_coherency_0",
            "check": "coherency",
            "prompt": "Reply with one short sentence about the color of the sky.",
        },
        {
            "item_id": "smoke_coherency_1",
            "check": "coherency",
            "prompt": "Name two common kitchen utensils in one sentence.",
        },
        {
            "item_id": "smoke_coherency_2",
            "check": "coherency",
            "prompt": "What is 2+2? Answer in a complete sentence.",
        },
        {
            "item_id": "smoke_code_0",
            "check": "code_extract",
            "prompt": (
                "Write a Python function `add(a, b)` that returns the sum. "
                "Put the code in a ```python``` fence. Do not explain."
            ),
        },
        {
            "item_id": "smoke_code_1",
            "check": "code_extract",
            "prompt": (
                "Write a Python function `is_even(n)` returning True if n is even. "
                "Use a ```python``` code block only."
            ),
        },
        {
            "item_id": "smoke_code_2",
            "check": "code_extract",
            "prompt": (
                "Write Python `def greet(name):` that returns 'hi ' + name. "
                "Code fence only."
            ),
        },
        {
            "item_id": "smoke_json_0",
            "check": "json_parse",
            "prompt": (
                'Return a JSON object with keys "city" (string) and "pop" (integer). '
                "No markdown fences."
            ),
        },
        {
            "item_id": "smoke_json_1",
            "check": "json_parse",
            "prompt": 'Return ONLY a JSON object: {"ok": true, "n": <integer>}.',
        },
        {
            "item_id": "smoke_json_2",
            "check": "json_parse",
            "prompt": "Emit a JSON object with fields title (string) and tags (array of strings).",
        },
        {
            "item_id": "smoke_tool_0",
            "check": "tool_call_syntax",
            "prompt": (
                "Emit a tool call as JSON with keys name and arguments "
                '(object). Example shape only — invent a get_weather call for Paris.'
            ),
        },
        {
            "item_id": "smoke_tool_1",
            "check": "tool_call_syntax",
            "prompt": (
                'Respond with ONLY JSON like {"name":"search","arguments":{"q":"..."}} '
                "for a search about cats."
            ),
        },
        {
            "item_id": "smoke_tool_2",
            "check": "tool_call_syntax",
            "prompt": (
                "Output a single JSON tool call object with name and arguments "
                "to convert 10 USD to EUR."
            ),
        },
        {
            "item_id": "smoke_mc_0",
            "check": "mc_letter",
            "prompt": (
                "Which planet is known as the Red Planet?\n"
                "A) Venus\nB) Mars\nC) Jupiter\nD) Saturn\n"
                "Answer with A, B, C, or D only."
            ),
            "answer": "B",
        },
        {
            "item_id": "smoke_mc_1",
            "check": "mc_letter",
            "prompt": (
                "What is H2O commonly called?\n"
                "A) Salt\nB) Oxygen\nC) Water\nD) Hydrogen\n"
                "Answer with A, B, C, or D only."
            ),
            "answer": "C",
        },
        {
            "item_id": "smoke_mc_2",
            "check": "mc_letter",
            "prompt": (
                "How many sides does a triangle have?\n"
                "A) 2\nB) 3\nC) 4\nD) 5\n"
                "Answer with A, B, C, or D only."
            ),
            "answer": "B",
        },
    ]
    # Pad to 25 with more coherency / format probes.
    while len(items) < 25:
        i = len(items)
        items.append(
            {
                "item_id": f"smoke_coherency_extra_{i}",
                "check": "coherency",
                "prompt": f"In one sentence, mention a fruit and a color. (probe {i})",
            }
        )
    _write_suite(
        "smoke",
        items,
        source="benchbase-authored",
        license_name="Apache-2.0 (BenchBase)",
        notes={"format_probes": True, "no_gold_in_options_labels": True},
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    vendor_tiny_mmlu()
    vendor_tiny_arc()
    vendor_tiny_gsm8k()
    vendor_livecodebench()
    vendor_bfcl()
    vendor_ifeval()
    vendor_structured()
    vendor_long_context()
    vendor_smoke()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
