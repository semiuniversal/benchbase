"""Parse OMP RPC/print JSONL (or session files) into AttemptLedger."""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from benchbase.agentic.ledger import AttemptLedger

# Tool-result text that indicates a hash-anchored edit rejection.
_HASHLINE_RE = re.compile(
    r"(hashline|stale\s+(anchor|hash)|anchor\s+mismatch|content\s+hash\s+mismatch|"
    r"file\s+has\s+changed|edit\s+rejected|hash[-\s]?anchored)",
    re.I,
)

_TOOL_NAME_KEYS = ("name", "toolName", "tool_name", "tool")


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _tool_name(obj: dict[str, Any]) -> str | None:
    for k in _TOOL_NAME_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v:
            return v
    tool = obj.get("tool")
    if isinstance(tool, dict):
        for k in _TOOL_NAME_KEYS:
            v = tool.get(k)
            if isinstance(v, str) and v:
                return v
    return None


def _usage_from(obj: dict[str, Any]) -> tuple[int, int, int]:
    usage = obj.get("usage") or obj.get("token_usage") or {}
    if not isinstance(usage, dict):
        return 0, 0, 0
    prompt = int(
        usage.get("input")
        or usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or 0
    )
    completion = int(
        usage.get("output")
        or usage.get("completion_tokens")
        or usage.get("output_tokens")
        or 0
    )
    thinking = int(
        usage.get("thinking")
        or usage.get("thinking_tokens")
        or usage.get("reasoning_tokens")
        or 0
    )
    return prompt, completion, thinking


def _is_hashline_reject(text: str) -> bool:
    return bool(_HASHLINE_RE.search(text or ""))


def parse_events(events: Iterable[dict[str, Any]], *, wall_seconds: float | None = None) -> AttemptLedger:
    """Build AttemptLedger from a stream of OMP JSON event/response objects."""
    ledger = AttemptLedger(wall_seconds=float(wall_seconds or 0.0))
    turns = 0
    tool_calls = 0
    rejects = 0
    prompt_tokens = 0
    completion_tokens = 0
    thinking_tokens = 0
    thrash = 0
    tool_sig_counts: Counter[str] = Counter()
    session_id: str | None = None
    session_file: str | None = None
    prompt_injected = False

    for ev in events:
        etype = str(ev.get("type") or ev.get("event") or "")
        role = str(ev.get("role") or "")
        msg = ev.get("message") if isinstance(ev.get("message"), dict) else None

        if etype == "prompt" or (etype == "response" and ev.get("command") == "prompt" and ev.get("success")):
            prompt_injected = True

        if etype in {"assistant", "message"} or role == "assistant":
            turns += 1
            p, c, t = _usage_from(ev if "usage" in ev else (msg or {}))
            if p or c or t:
                prompt_tokens += p
                completion_tokens += c
                thinking_tokens += t
            elif msg:
                p, c, t = _usage_from(msg)
                prompt_tokens += p
                completion_tokens += c
                thinking_tokens += t

        # OMP RPC streams use message_end / turn_end rather than role=assistant events.
        if etype == "message_end" and isinstance(msg, dict) and msg.get("role") == "assistant":
            p, c, t = _usage_from(msg)
            if p or c or t:
                prompt_tokens = max(prompt_tokens, p)
                completion_tokens = max(completion_tokens, c)
                thinking_tokens = max(thinking_tokens, t)
        if etype == "turn_end":
            turns += 1

        if etype in {
            "tool_call",
            "toolUse",
            "tool_use",
            "tool_execution_start",
        } or ev.get("toolCall") or ev.get("tool_call"):
            tool_calls += 1
            name = (
                _tool_name(ev)
                or str(ev.get("toolName") or "")
                or _tool_name(ev.get("toolCall") or {})
                or "unknown"
            )
            args = ev.get("arguments") or ev.get("args") or ev.get("input") or {}
            try:
                sig = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
            except TypeError:
                sig = f"{name}:{args!r}"
            tool_sig_counts[sig] += 1
            if tool_sig_counts[sig] == 3:
                thrash += 1

        if etype in {
            "tool_result",
            "toolResult",
            "tool_result_error",
            "tool_execution_end",
        }:
            text = ""
            if isinstance(ev.get("content"), str):
                text = ev["content"]
            elif isinstance(ev.get("result"), str):
                text = ev["result"]
            elif isinstance(ev.get("error"), str):
                text = ev["error"]
            elif isinstance(ev.get("output"), str):
                text = ev["output"]
            if _is_hashline_reject(text):
                rejects += 1
            # Nested details
            details = ev.get("details") or ev.get("data") or {}
            if isinstance(details, dict):
                nested = str(details.get("error") or details.get("message") or "")
                if _is_hashline_reject(nested):
                    rejects += 1
            result = ev.get("result")
            if isinstance(result, dict):
                nested = str(result.get("error") or result.get("message") or result.get("output") or "")
                if _is_hashline_reject(nested):
                    rejects += 1
            elif isinstance(result, str) and _is_hashline_reject(result):
                rejects += 1

        # Session state payloads
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        if data.get("sessionId"):
            session_id = str(data["sessionId"])
        if data.get("session_id"):
            session_id = str(data["session_id"])
        if data.get("sessionFile"):
            session_file = str(data["sessionFile"])
        if data.get("session_file"):
            session_file = str(data["session_file"])
        if ev.get("sessionId"):
            session_id = str(ev["sessionId"])
        if ev.get("sessionFile"):
            session_file = str(ev["sessionFile"])

        # Aggregated stats response
        if etype == "response" and ev.get("command") == "get_session_stats" and isinstance(data, dict):
            usage = data.get("usage") or data.get("tokenUsage") or {}
            if isinstance(usage, dict):
                p, c, t = _usage_from({"usage": usage})
                if p or c or t:
                    prompt_tokens = max(prompt_tokens, p)
                    completion_tokens = max(completion_tokens, c)
                    thinking_tokens = max(thinking_tokens, t)

    ledger.turns = turns
    ledger.tool_calls = tool_calls
    ledger.hashline_rejected_edits = rejects
    ledger.tokens_prompt = prompt_tokens
    ledger.tokens_completion = completion_tokens
    ledger.tokens_thinking = thinking_tokens
    ledger.thrash_cutoffs = thrash
    ledger.session_id = session_id
    ledger.session_file = session_file
    ledger.prompt_injected = prompt_injected
    return ledger


def parse_session_file(path: Path | str, *, wall_seconds: float | None = None) -> AttemptLedger:
    """Parse a checked-in or on-disk OMP session JSONL into AttemptLedger."""
    p = Path(path)
    return parse_events(_iter_jsonl(p), wall_seconds=wall_seconds)


class OmpDriver:
    """Drive one OMP attempt: inject prompt, wait, parse ledger.

    Live mode invokes the pinned OMP CLI (`--mode rpc` preferred).
    Fixture/mock mode parses a JSONL transcript (CI; no model required).
    """

    def __init__(
        self,
        *,
        omp_bin: str | None = None,
        cwd: str | Path | None = None,
        model: str | None = None,
        provider: str | None = None,
        timeout_s: float = 300.0,
        thrash_limit: int = 3,
        spin_turns: int = 8,
        fixture_transcript: Path | str | None = None,
        mock_ledger: AttemptLedger | None = None,
        env: dict[str, str] | None = None,
        transcript_path: str | Path | None = None,
        transcript_relpath: str | None = None,
        on_event: Any | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self.omp_bin = omp_bin or "omp"
        self.cwd = Path(cwd) if cwd else None
        self.model = model
        self.provider = provider
        self.timeout_s = timeout_s
        self.thrash_limit = thrash_limit
        self.spin_turns = spin_turns
        self.fixture_transcript = Path(fixture_transcript) if fixture_transcript else None
        self.mock_ledger = mock_ledger
        self.env = env
        self.transcript_path = Path(transcript_path) if transcript_path else None
        self.transcript_relpath = transcript_relpath
        self.on_event = on_event
        self.event_bus = event_bus
    def run_attempt(self, instruction: str) -> AttemptLedger:
        if self.mock_ledger is not None:
            ledger = AttemptLedger.from_dict(self.mock_ledger.to_dict())
            ledger.prompt_injected = True
            if self.transcript_relpath:
                ledger.transcript_path = self.transcript_relpath
            return ledger
        if self.fixture_transcript is not None:
            t0 = time.monotonic()
            ledger = parse_session_file(self.fixture_transcript)
            if ledger.wall_seconds <= 0:
                ledger.wall_seconds = time.monotonic() - t0
            ledger.prompt_injected = True
            ledger.extra["instruction_len"] = len(instruction)
            if self.transcript_relpath:
                ledger.transcript_path = self.transcript_relpath
            # Mirror fixture into durable transcript when path provided (tests / mock CI).
            if self.transcript_path is not None:
                from benchbase.agentic.session_store import TranscriptWriter

                with TranscriptWriter(
                    self.transcript_path, bus=self.event_bus
                ) as writer:
                    writer.write_event(
                        {
                            "type": "message_end",
                            "message": {
                                "role": "user",
                                "content": [{"type": "text", "text": instruction}],
                            },
                            "synthetic": True,
                            "source": "benchbase_prompt",
                        }
                    )
                    for line in self.fixture_transcript.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line.startswith("{"):
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(ev, dict):
                            writer.write_event(ev)
            return ledger
        return self._run_live_rpc(instruction)

    def _record(self, ev: dict[str, Any], events: list[dict[str, Any]], writer: Any) -> None:
        events.append(ev)
        if writer is not None:
            writer.write_event(ev)
        if self.on_event is not None:
            try:
                self.on_event(ev)
            except Exception:
                pass

    def _run_live_rpc(self, instruction: str) -> AttemptLedger:
        """Start OMP in RPC mode, send prompt, collect events until idle/timeout."""
        import select
        import subprocess

        from benchbase.agentic.session_store import TranscriptWriter

        cmd = [self.omp_bin, "--mode", "rpc", "--no-session"]
        if self.provider:
            cmd.extend(["--provider", self.provider])
        if self.model:
            cmd.extend(["--model", self.model])
        t0 = time.monotonic()
        events: list[dict[str, Any]] = []
        timed_out = False
        aborted = False
        cutoff_reason: str | None = None
        run_env = os.environ.copy()
        if self.env:
            run_env.update({k: str(v) for k, v in self.env.items() if v is not None})
        writer: TranscriptWriter | None = None
        if self.transcript_path is not None:
            writer = TranscriptWriter(self.transcript_path, bus=self.event_bus)
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=str(self.cwd) if self.cwd else None,
                env=run_env,
            )
            assert proc.stdin and proc.stdout
            # Persist the injected instruction as a synthetic user message for Inspect Session.
            self._record(
                {
                    "type": "message_end",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": instruction}],
                    },
                    "synthetic": True,
                    "source": "benchbase_prompt",
                },
                events,
                writer,
            )
            prompt_cmd = json.dumps({"id": "1", "type": "prompt", "message": instruction}) + "\n"
            proc.stdin.write(prompt_cmd)
            proc.stdin.flush()
            # Keep reading until agent_end/idle/done, thrash, process exit, or timeout.
            # Never block forever on readline: OMP holds stdin open after agent_end and
            # waits for more RPC, so a bare readline() would hang past timeout_s.
            deadline = t0 + self.timeout_s
            tool_sig_counts: Counter[str] = Counter()
            stdout_fd = proc.stdout.fileno()

            def _readline_deadline(until: float) -> str | None:
                remaining = until - time.monotonic()
                if remaining <= 0:
                    return None
                ready, _, _ = select.select([stdout_fd], [], [], remaining)
                if not ready:
                    return None
                return proc.stdout.readline()

            while True:
                now = time.monotonic()
                if now >= deadline:
                    timed_out = True
                    cutoff_reason = cutoff_reason or "timeout"
                    break
                line = _readline_deadline(deadline)
                if line is None:
                    if proc.poll() is not None:
                        break
                    timed_out = True
                    cutoff_reason = cutoff_reason or "timeout"
                    break
                if not line:
                    if proc.poll() is not None:
                        break
                    continue
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(ev, dict):
                    continue
                self._record(ev, events, writer)
                etype = str(ev.get("type") or "")
                if etype in {"tool_call", "toolUse", "tool_use", "tool_execution_start"}:
                    name = (
                        _tool_name(ev)
                        or str(ev.get("toolName") or "")
                        or "unknown"
                    )
                    args = ev.get("arguments") or ev.get("args") or {}
                    sig = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
                    tool_sig_counts[sig] += 1
                    if tool_sig_counts[sig] >= self.thrash_limit:
                        cutoff_reason = "thrash"
                        aborted = True
                        break
                # turn_end is mid-trajectory (tool loops); only terminal events stop us.
                if etype in {"agent_end", "idle", "done"}:
                    break
                if etype == "response" and ev.get("command") == "prompt" and not ev.get("success", True):
                    break

            try:
                stats_cmd = json.dumps({"id": "stats", "type": "get_session_stats"}) + "\n"
                proc.stdin.write(stats_cmd)
                proc.stdin.flush()
                # Brief drain (select so we do not hang if OMP is silent)
                drain_deadline = time.monotonic() + 2.0
                while time.monotonic() < drain_deadline:
                    line = _readline_deadline(drain_deadline)
                    if not line:
                        break
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            self._record(json.loads(line), events, writer)
                        except json.JSONDecodeError:
                            pass
            except BrokenPipeError:
                pass

            try:
                proc.stdin.write(json.dumps({"id": "abort", "type": "abort"}) + "\n")
                proc.stdin.flush()
            except BrokenPipeError:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"OMP binary not found ({self.omp_bin}). "
                "Install pinned Oh My Pi on the runner host — see doc/omp-pin.md"
            ) from exc
        finally:
            if writer is not None:
                writer.close()

        wall = time.monotonic() - t0
        ledger = parse_events(events, wall_seconds=wall)
        ledger.timed_out = timed_out
        ledger.aborted = aborted
        ledger.cutoff_reason = cutoff_reason
        ledger.prompt_injected = True
        if self.transcript_relpath:
            ledger.transcript_path = self.transcript_relpath
        if cutoff_reason == "thrash":
            ledger.thrash_cutoffs = max(ledger.thrash_cutoffs, 1)
        return ledger
