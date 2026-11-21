---
name: Creative Shell
description: Safe npm and Vite commands inside the attempt project directory
metadata:
  opencode/autoinvoke: true
---

## When to use

Installing deps, running dev/build, or checking bundle output under `project/`.

## Allowed patterns

Run from `project/`:

- `npm install`, `npm run dev`, `npm run build`, `npm run preview`
- `npx vite`, `npx tsc --noEmit`

## Rules

- Never run `git push`, `curl` to internal LAN hosts, or Docker socket commands.
- If a command needs approval (`ask`), explain why in one sentence and retry after approval.