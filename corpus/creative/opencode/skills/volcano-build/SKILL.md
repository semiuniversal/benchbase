---
name: Volcano Build
description: Scaffold and iterate on the volcano-skunk-v1 React+Vite+Canvas app per challenge brief
metadata:
  opencode/autoinvoke: true
---

## When to use

Starting a creative attempt or when the preview is blank / below 60 FPS / missing skunk or sliders.

## Scope

- Edit only under `project/`.
- Read `project/BRIEF.md` for the full challenge text.
- Stack: React, Vite, Tailwind CSS, HTML5 Canvas with `requestAnimationFrame`.

## Workflow

1. If `project/` is empty, scaffold with Vite React + Tailwind (`npm create vite@latest` patterns).
2. Implement canvas loop: magma, lava chunks, ash; particle pool sized by slider (50–2000).
3. Sliders: Emitted Particle Density, Magma Viscosity, Gas Pressure.
4. Preset buttons: Hawaiian vs Plinian behavior profiles.
5. Volcano silhouette: particles collide, cool, recycle on ground hit.
6. Visual depth: asymmetric volcano, rich sky, glow from vent.
7. Bonus: foreground skunk with occasional spray animation.
8. Run `npm install` and `npm run build` in `project/`; fix build errors before finishing.

## Do not

- Read or write outside the attempt workspace.
- Commit secrets or call `git push`.