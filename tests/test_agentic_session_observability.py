"""Tests for agentic session persist + workspace/transcript APIs."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benchbase.agentic.session_store import (
    AttemptEventBus,
    TranscriptWriter,
    normalize_events,
    read_raw_events,
    transcript_abspath,
)
from benchbase.agentic.workspace_view import list_fixture_tree, read_fixture_file, resolve_fixture_for_item
from benchbase.db.models import (
    Base,
    BenchmarkAxis,
    BenchmarkSuite,
    Model,
    ModelStatus,
    Run,
    RunStatus,
    RunTier,
)
from benchbase.runners.agentic import AgenticRunner


FIXTURE = Path(__file__).parent / "fixtures" / "omp_sessions" / "trivial_edit.jsonl"


def test_normalize_fixture_and_rpc_shapes():
    raw = [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.startswith("{")]
    turns = normalize_events(raw)
    kinds = [t["kind"] for t in turns]
    assert "assistant" in kinds
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    assert "end" in kinds

    rpcish = [
        {
            "type": "message_end",
            "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        },
        {
            "type": "tool_execution_start",
            "toolName": "read",
            "args": {"path": "a.py"},
        },
        {
            "type": "tool_execution_end",
            "toolName": "read",
            "result": "ok",
        },
    ]
    turns2 = normalize_events(rpcish)
    assert turns2[0]["kind"] == "user"
    assert turns2[1]["kind"] == "tool_call"
    assert turns2[1]["tool"] == "read"
    assert turns2[2]["kind"] == "tool_result"


def test_transcript_writer_persists_and_publishes():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "t.jsonl"
        bus = AttemptEventBus.open(999001, "greet-welcome:seed0")
        writer = TranscriptWriter(path, bus=bus)
        writer.write_event({"type": "idle"})
        writer.close()
        AttemptEventBus.close(999001, "greet-welcome:seed0")
        events = read_raw_events(path)
        assert len(events) == 1
        assert events[0]["type"] == "idle"


def test_fixture_workspace_tree_safe():
    fixture = resolve_fixture_for_item("greet-welcome", "mvp")
    assert fixture
    tree = list_fixture_tree(fixture)
    assert any(e["path"].endswith("greet.py") for e in tree if e["type"] == "file")
    content = read_fixture_file(fixture, "src/greet.py")
    assert "Hello" in content or "greet" in content.lower()
    with pytest.raises(PermissionError):
        read_fixture_file(fixture, "../etc/passwd")


async def _mock_run_with_transcript(db_path: Path) -> int:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id: int
    async with factory() as db_session:
        model = Model(
            name="mock-model",
            endpoint_url="http://127.0.0.1:9",
            status=ModelStatus.ACTIVE,
            is_active=True,
            color="blue",
        )
        suite = BenchmarkSuite(
            name="Finalist · Agentic (OMP)",
            axis=BenchmarkAxis.AGENTIC,
            category=BenchmarkAxis.AGENTIC,
            runner_class="agentic",
            suite_version="mvp",
        )
        db_session.add_all([model, suite])
        await db_session.flush()
        meta = {
            "suite_version": "mvp",
            "n_seeds": 1,
            "task_ids": ["greet-welcome"],
            "mock": True,
        }
        run = Run(
            model_id=model.id,
            suite_id=suite.id,
            status=RunStatus.RUNNING,
            tier=RunTier.THOROUGH,
            metadata_json=json.dumps(meta),
            config_json=json.dumps(meta),
        )
        db_session.add(run)
        await db_session.commit()
        run_id = run.id
        await AgenticRunner().run(run, db_session)
        await db_session.commit()

        from sqlalchemy import select
        from benchbase.db.models import Result, ResultItem

        items = (
            await db_session.execute(
                select(ResultItem)
                .join(Result, ResultItem.result_id == Result.id)
                .where(Result.run_id == run_id)
            )
        ).scalars().all()
        assert items
        detail = json.loads(items[0].detail_json or "{}")
        assert detail.get("transcript_path")
        assert detail.get("fixture")
        assert detail.get("instruction")
    await engine.dispose()
    return run_id


def test_agentic_mock_persists_transcript_path(monkeypatch, tmp_path):
    # Point DATA_DIR agentic store at tmp via monkeypatch on session_store.AGENTIC_DIR
    import benchbase.agentic.session_store as ss

    agentic_root = tmp_path / "agentic"
    monkeypatch.setattr(ss, "AGENTIC_DIR", agentic_root)

    run_id = asyncio.run(_mock_run_with_transcript(tmp_path / "t.db"))
    path = transcript_abspath(run_id, "greet-welcome", 0)
    assert path.is_file()
    turns = normalize_events(read_raw_events(path))
    assert any(t["kind"] == "user" for t in turns)
    assert any(t["kind"] in {"assistant", "tool_call"} for t in turns)


def test_attempt_event_bus_subscribe_closes():
    async def _run() -> None:
        from benchbase.agentic.session_store import AttemptEvent

        bus = AttemptEventBus.open(424242, "x:seed0")
        bus.bind_loop()

        async def publish_later() -> None:
            await asyncio.sleep(0.05)
            bus.publish(AttemptEvent(raw={"type": "idle"}))
            AttemptEventBus.close(424242, "x:seed0")

        asyncio.create_task(publish_later())
        got = []
        async for entry in bus.subscribe():
            got.append(entry.raw.get("type"))
        assert got == ["idle"]

    asyncio.run(_run())
