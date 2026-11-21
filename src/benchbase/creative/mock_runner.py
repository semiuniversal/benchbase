"""Simulated OpenCode-style attempt for UI/worker integration tests (WP7)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from benchbase.creative.events import CreativeEvent, emit

_HTML_STUB = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Volcano mock preview</title>
  <style>
    body { margin: 0; background: #0f172a; color: #e2e8f0; font-family: system-ui, sans-serif; }
    canvas { display: block; width: 100%; height: 70vh; }
    .hud { padding: 12px; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
    input[type=range] { width: 160px; }
  </style>
</head>
<body>
  <div class="hud">
    <label>Emitted Particle Density <input id="density" type="range" min="50" max="500" value="120" /></label>
    <span id="fps">mock harness — not full volcano spec</span>
  </div>
  <canvas id="c"></canvas>
  <script>
    const c = document.getElementById('c');
    const ctx = c.getContext('2d');
    function resize() { c.width = c.clientWidth; c.height = c.clientHeight; }
    window.addEventListener('resize', resize); resize();
    let particles = [];
    document.getElementById('density').oninput = (e) => {
      const n = +e.target.value;
      while (particles.length < n) particles.push({ x: c.width/2, y: c.height*0.7, vy: -2-Math.random()*3, vx: (Math.random()-0.5)*4 });
      particles.length = n;
    };
    document.getElementById('density').dispatchEvent(new Event('input'));
    function loop() {
      ctx.fillStyle = 'rgba(15,23,42,0.35)'; ctx.fillRect(0,0,c.width,c.height);
      for (const p of particles) {
        p.vy += 0.08; p.x += p.vx; p.y += p.vy;
        if (p.y > c.height) { p.y = c.height*0.7; p.vy = -2-Math.random()*5; }
        ctx.fillStyle = '#f97316'; ctx.beginPath(); ctx.arc(p.x, p.y, 3, 0, Math.PI*2); ctx.fill();
      }
      requestAnimationFrame(loop);
    }
    loop();
  </script>
</body>
</html>
"""


async def run_mock_attempt(
    workspace_root: Path,
    attempt_uuid: str,
    *,
    model_name: str,
    delay_s: float = 0.35,
) -> None:
    project = workspace_root / "project"
    try:
        await emit(
            workspace_root,
            attempt_uuid,
            CreativeEvent("phase", message="provision", extra={"model": model_name}),
        )
        await asyncio.sleep(delay_s)

        await emit(
            workspace_root,
            attempt_uuid,
            CreativeEvent(
                "tool_start",
                tool="edit",
                path="project/package.json",
                message="Scaffolding Vite + React",
            ),
        )
        (project / "package.json").write_text(
            '{"name":"volcano-mock","private":true,"type":"module"}',
            encoding="utf-8",
        )
        await asyncio.sleep(delay_s)
        await emit(
            workspace_root,
            attempt_uuid,
            CreativeEvent("tool_end", tool="edit", path="project/package.json", message="ok"),
        )

        await emit(
            workspace_root,
            attempt_uuid,
            CreativeEvent(
                "tool_start",
                tool="edit",
                path="project/index.html",
                message="Writing canvas stub (OpenCode would iterate here)",
            ),
        )
        await asyncio.sleep(delay_s * 2)
        (project / "index.html").write_text(_HTML_STUB, encoding="utf-8")
        await emit(
            workspace_root,
            attempt_uuid,
            CreativeEvent("tool_end", tool="edit", path="project/index.html", message="ok"),
        )

        await emit(
            workspace_root,
            attempt_uuid,
            CreativeEvent(
                "tool_start",
                tool="shell",
                message="npm install (simulated — worker will run for real)",
            ),
        )
        await asyncio.sleep(delay_s)
        await emit(
            workspace_root,
            attempt_uuid,
            CreativeEvent("tool_end", tool="shell", message="exit 0 (mock)"),
        )

        await emit(
            workspace_root,
            attempt_uuid,
            CreativeEvent(
                "tool_start",
                tool="browser",
                message="Load creative-browser-check skill when Playwright MCP is pinned in worker",
                extra={
                    "status": "skipped",
                    "reason": "live browser needs worker + opencode pin",
                    "skill": "creative-browser-check",
                },
            ),
        )
        await asyncio.sleep(delay_s)
        await emit(
            workspace_root,
            attempt_uuid,
            CreativeEvent(
                "tool_end",
                tool="browser",
                message="Validation deferred",
                extra={"preview": "project/index.html"},
            ),
        )

        await emit(
            workspace_root,
            attempt_uuid,
            CreativeEvent("text", message="Mock harness finished. Live OpenCode replaces this stream."),
        )
        await emit(
            workspace_root,
            attempt_uuid,
            CreativeEvent("complete", message="completed", extra={"harness": "mock"}),
        )
    except Exception as exc:  # noqa: BLE001
        await emit(
            workspace_root,
            attempt_uuid,
            CreativeEvent("error", message=str(exc)),
        )