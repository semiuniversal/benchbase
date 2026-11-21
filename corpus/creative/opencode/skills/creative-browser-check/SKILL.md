---
name: Creative Browser Check
description: Headless browser smoke test and screenshot for volcano creative attempts (ZooCode Playwright pattern → OpenCode)
metadata:
  opencode/autoinvoke: false
---

## When to use

After `npm run build` or when validating canvas + sliders in a real browser. Requires Playwright MCP or OpenCode browser tools allowed in `opencode.jsonc`.

## Workflow

1. Serve static preview from `project/dist` or dev server on `127.0.0.1` only (never bind `0.0.0.0` in the worker).
2. Navigate to the app root; wait until `#root` or canvas is visible.
3. Snapshot: verify slider labels include "Emitted Particle Density".
4. Drag density slider; confirm FPS label or particle count changes within 3s.
5. Save screenshot to `media/preview.png` (attempt workspace only).
6. Log failures as text in `logs/browser-check.txt`; do not screenshot host paths.

## Kasm note

Human-in-the-loop Kasm embeds are **not** required for BenchBase scoring. Headless capture into `media/` is sufficient unless the owner enables headed validation in the worker image.

## Permissions

Uses `tool.use` resources matching `mcp_playwright_*` or `browser_*` as configured on `volcano-builder`. Load this skill explicitly if autoinvoke is off.