# BenchBase — Actionable Headlines Dashboard

**Specification:** DASHBOARD-ACTIONABLE-HEADLINES-v1  
**Status:** Proposed, narrowly scoped UX/product improvement  
**Date:** 2026-11-23  
**Target:** Existing BenchBase FastAPI + React/Mantine application  
**Relationship:** Addendum to *BenchBase vNext Specification v1.2*; does not supersede its persistence, comparability, Creative Arena, or telemetry requirements

> **Core requirement:** Every dashboard item must be a dynamically generated, meaningful entry point into a **specific existing process, result, comparison, or pending action**. An item without a real, working drill-down destination does **not** belong on the dashboard.

## 1. Problem and design intent

The current dashboard displays lifetime totals (models, suites, runs) and a long table of models with mostly `INACTIVE` labels. This reproduces information already available in Models and other detail pages, consumes most of the screen, and provides no compelling reason to return to the homepage. It is an example of a specification-compliant but functionally hollow dashboard.

The dashboard is **not** another data exploration surface, leaderboard, operations center, or analytics report. Its sole role is to guide the user efficiently from a high-level, changing headline to a well-defined, deeper view that already owns the underlying functionality.

A useful dashboard answers three questions:

1. **What is happening right now?**
2. **What happened recently that merits inspection?**
3. **What needs attention or a decision?**

Each item must provide a concise, verifiable answer and link to the relevant record in Benchmarks, Models, Compare, Arena, or Creative Arena.

### 1.1 Product rules — non-negotiable

1. **Navigation-first:** Every displayed headline is clickable (keyboard-accessible) and navigates to a specific, valid destination with applicable record identity, selected tab, filter, or comparison context.
2. **State-derived:** Headlines come from real persisted application state and/or actual live execution status. No static sample headlines, invented milestones, decorative alert counts, hardcoded model names, or synthetic scores in production.
3. **No duplicated detail pages:** The dashboard must not contain a model directory, full leaderboard, benchmark log, full metrics table, charts requiring interpretation, or a second Compare UI.
4. **No dead statistics:** Lifetime counts such as `140 models`, `12 suites`, `2,003 runs` are not featured KPIs. If retained anywhere, they belong in a subordinate About/Statistics view, not the primary dashboard.
5. **Contextual drill-down:** Clicking a headline must reveal the subject of that headline immediately. A generic link to the top of `/compare` or `/benchmarks` does **not** meet this requirement.
6. **Dynamic relevance:** Active processes and pending action outrank historical news. Items appear, update, and disappear as their underlying states change. A stopped experiment is not intrinsically an incident.
7. **Few items:** Prefer 5–8 meaningful headlines maximum, with a simple path to view more recent activity. Fewer is better when there is little to report; never fill unused space with meaningless cards.
8. **Truthful claims:** Do not claim a new record, improvement, degradation, or comparable ranking unless the existing scoring/methodology rules substantiate the claim.
9. **Stable app navigation:** Deep links survive page refresh, browser history, and direct opening in a new tab. Avoid dependence on in-memory component state alone.
10. **Incremental implementation:** Reuse the current database, APIs, routes, Mantine components, and job states. Do not invent a new generic dashboard framework or alter benchmark methodologies to populate headlines.

## 2. Primary user journeys

### Journey A — Follow an ongoing benchmark

- User opens Dashboard while a benchmark is running.
- Headline shows **actual model/deployment**, current axis or phase, progress where known, and last update time.
- Clicking navigates directly to **that run's existing live benchmark console**, including streaming output where available.
- When the run finishes, the headline changes to a recent-completion headline linking to its **persisted results**, not the generic benchmark list.

### Journey B — Inspect a completed experiment

- User returns after several experiments finish.
- Dashboard shows the most recently completed **distinct** benchmark sessions, not every axis/result row.
- Clicking a result opens the relevant completed run detail with its model, tier, suite revision, scores, and measurements.
- Partial or failed runs never appear as successful completed runs.

### Journey C — Resolve an actionable problem

- An interrupted benchmark can be inspected or resumed (only if that action exists in BenchBase).
- Headline identifies the **specific run and actual status**; clicking reveals logs/recovery actions available for that run.
- A historically inactive model is **not** treated as an outage. An endpoint that is supposed to be available but failed health checks may be an alert **only if desired availability is explicitly tracked**.

### Journey D — Review generated creative work

- A completed Creative Arena attempt with a retained artifact and no human quality rating appears as **ready for review**.
- Clicking opens the **specific attempt** at Preview/Source/Transcript/Rating, according to what's implemented; if a runnable preview cannot be started, the artifact/source view remains available.
- After a rating is recorded, the pending-review headline disappears. A recently completed/reviewed attempt may remain under recent activity for a limited period.
- **Do not fabricate a Creative Arena review headline if its underlying implementation is incomplete.**

### Journey E — Investigate an actual comparison-worthy finding

- If evidence establishes a significant result or speed record in a **defined comparable cohort**, dashboard may display a headline.
- Clicking enters Compare with relevant model(s), axis/speed profile, cohort constraints, and baseline already selected.
- If those exact filters and deep links aren't available, **do not show the finding until they are**. A completed-run headline is an acceptable simpler alternative.

## 3. Dashboard information hierarchy

### 3.1 Phase 1: required headline types

| Type ID | Trigger | Headline content | Required destination | Expiry / update |
|---|---|---|---|---|
| `benchmark.running` | Persisted session/job state is running | Model, suite/tier, current axis, progress if known | Exact live run/session console | Updates with progress; becomes completion/error upon terminal transition |
| `benchmark.queued` | Job truly queued and waiting | Model, tier, queue position only if known | Exact queued job detail | Disappears on start/cancel |
| `benchmark.completed` | Session completed successfully | Model, tier, completion timestamp, one useful result if valid | Exact persisted result/sitting detail | Recent window, configurable; deduplicated |
| `benchmark.interrupted` | Recoverable/interrupted/failed job or partial results requiring examination | Model, failure/interrupt reason when known | Exact run detail, diagnostics or recovery view | Until resolved/dismissed or archived |
| `creative.review_pending` | Retained completed attempt has no subjective evaluation | Challenge and model, completion time | Exact Creative Arena attempt/review view | Disappears when evaluated |
| `creative.completed` | Creative attempt finished and is worth recent-activity inclusion | Challenge, model, final state | Exact retained attempt | Recent window; not a duplicate of review-pending item |

If a route, detail page, or state is not yet implemented, that type is **disabled**, not replaced by a generic or fake link. Phase 1 must ship with the types already supported by the live application, especially running/completed/failed benchmarks.

### 3.2 Phase 2: optional derived findings (only with credible evidence)

| Type ID | Trigger | Required destination | Evidence constraint |
|---|---|---|---|
| `finding.quality_record` | New best score in a compatible benchmark cohort | Compare preselected on axis and cohort, with baseline/result | Same corpus version, tier, gate/measurement policy; no smoke-vs-standard comparisons |
| `finding.speed_record` | Best comparable decode TPS in a specified cohort/profile | Compare preselected to profile, models and measurement method | Same speed profile and compatible conditions; no mixing legacy chunks/sec, effective TPS or confidence classes |
| `finding.material_change` | Genuine deployment-versus-baseline difference | Paired Compare/details | Immutable revisions and sufficiently matched evaluation evidence; no claim based on unrelated model versions |
| `comparison.recent` | An actual saved comparison or reproducible comparison state exists | Exact saved/reconstructible comparison | No invented “recent comparisons” based on simply opening the Compare tab |

**Default implementation is to omit these Phase 2 types** until the existing Compare page genuinely supports URL-addressable, methodology-aware comparisons. Do not implement speculative insight-generation simply to make the homepage visually busy.

## 4. Headline content and interaction

Each headline is a compact **actionable sentence**, not a miniature report.

Suggested single-item layout:

```text
[RUNNING]  Qwen 3.8 Flash — Standard benchmark
           Tool calling · 438/602 items · updated 8 sec ago            >

[REVIEW]   Volcano & Skunk — Attempt 004
           Completed on Trellis · needs a rating                       >

[RESULT]   GLM 5.3 Flash — Standard completed
           11 minutes ago · 8 axes, current suite                       >
```

**These are examples only, not production data or prescribed scores.** For each headline:

- The primary title conveys the change or action.
- The secondary line provides one or two factual context fields (model, benchmark type, phase, age, current state), not a dense metric collection.
- A consistent type label or restrained icon may help scanning; avoid excessive badges or alarming colors for routine historical status.
- The whole headline is a real semantic link where possible. Enter/Space behavior and focus indication must work.
- The headline's accessible name describes both the event and destination.
- Where details are missing, omit those details rather than rendering placeholders such as `0 TPS`, `0%`, or fictional progress.

### No duplicate entries for the same process

A running benchmark shouldn't also appear as a recent result. A creative attempt awaiting review shouldn't appear twice in the limited headline stack. Show one most actionable current entry per work item; detailed historical activity belongs on the destination page.

### Navigation behavior

- Open exact run/session/attempt IDs via current router and API; never use mutable model alias as the sole identifier for historical results.
- For Compare, encode selection and methodology constraints in URL/query state or an existing saved-comparison identifier; refresh must restore the exact comparison.
- Preserve the user's ability to return via browser Back without losing context.
- Stale/deleted destination: render a clear “record unavailable” state with a meaningful back link; never silently redirect to a generic list and pretend the link worked.
- Avoid hardcoding guessed route URLs. Inspect the current router and add narrowly scoped deep-link support where required.

## 5. Headline data contract

Implement either a small aggregated dashboard endpoint or an equivalent server-side selector using existing APIs. Prefer **server-side derivation** for cross-page consistency, and avoid calculating complicated domain status separately in React.

Suggested *logical* type, not a mandate to add new database tables:

```typescript
type DashboardHeadline = {
  id: string;                        // Stable event or record-derived key
  type: string;                      // Registered headline type
  title: string;                     // Short factual sentence
  subtitle?: string;
  sourceKind: 'benchmark' | 'creative' | 'comparison' | 'deployment';
  sourceId: string;                  // Immutable run/attempt/etc. ID
  occurredAt: string;                // ISO timestamp; not fabricated
  updatedAt?: string;
  priority: number;                  // Deterministic sorting policy
  destination: {
    routeName: string;               // Existing known application route
    params?: Record<string, string>;
    query?: Record<string, string>;
  };
};
```

The server must only emit a headline if the target resolves to a real detail or filtered state. Treat `routeName` as a typed/internal navigation contract; front end should translate it using registered routes, rather than accepting unrestricted URLs from stored data.

### Data provenance

- Use existing `Model`, `Run`, `Result`, `run_group_id`, immutable deployment revisions and applicable persistent job status.
- A benchmark *sitting* is not necessarily the same as a raw per-axis `Run`; consolidate to the actual top-level process before deriving a completion headline.
- Preserve benchmark suite versions, tier and score-gate compatibility. Don't call a smoke-only result a standard completion.
- If Creative Arena has attempt/session state, use its stored identity, not its filesystem path as a URL.
- Reuse real timestamps and existing health/status semantics. A large historical model list is not a list of actionable outages.
- Avoid database migrations in the MVP unless a critical concept (such as stable job identity) truly cannot be represented.

## 6. Selection, sorting and freshness

The dashboard is **a ranked inbox of actionable events**, not a fixed 3-column layout that demands every slot be filled.

Default sort order:

1. Active, user-visible processes that can be inspected now.
2. Pending user decisions and inspectable failures/interrupted work.
3. Recently completed experiments/results.
4. Derived findings, if implemented and still fresh.

Within a class, order by latest substantive update, with deterministic tie-breaking. Give the user a predictable layout; don't reorder continually due only to clock ticks or health polling.

- Display up to **8** headlines by default. A small **View activity** link may navigate to a filtered existing history page if it exists; do not create a new activity page as a hidden prerequisite.
- Suggested completed-result lookback: latest seven days, then the latest few real historical completions if no recent records. Mark older items with their actual dates; do not imply they occurred today.
- Running/queued/pending-review entries are not limited to seven days, but genuinely stale jobs must be reported with their real persisted state, not as eternally “Running.”
- Avoid absolute user-facing claims of “live” if the data is only refreshed on page load. Poll modestly (e.g. 10–30 seconds while visible), or reuse existing status events. Display last refreshed only where necessary.
- Optional automatic refresh may be paused; user actions such as opening a specific item must never be obstructed by reordering.
- Do not use a single synthetic “needs attention” count unless clicking it reveals a real, already supported filtered list of those exact records. Prefer individual actionable entries where appropriate.

### Empty states

If no active or recent actionable events exist, show a concise truthful message such as “No recent benchmark activity” and a real link to **start a benchmark** or view existing results. Don't fabricate a record, hide the dashboard behind empty statistics, or display a blank error page.

## 7. What to remove from the current dashboard

- The full **Models** table, including its rows of `INACTIVE` status chips and repeated endpoints.
- The top-level lifetime **Models / Suites / Total Runs** KPI cards.
- Any fixed charts, model-ranking mini-tables or novelty stats added solely to occupy space.
- Any ornamental “Recent findings” card that doesn't derive its statements from a verifiable result and link to the corresponding comparison.

Existing Models, Compare, Benchmarks, Arena and Creative navigation stays intact. The dashboard links into those surfaces rather than replacing them.

## 8. Implementation scope and sequence

### Phase D0 — Repository and navigation reconciliation (no production mutation)

- Locate the current dashboard component, FastAPI routes, React router, benchmark sitting/run IDs, job state and creative attempt state.
- Make a matrix: **headline type → reliable source → actual target route → exact record key**.
- Identify which types can ship today without inventing APIs or states.
- Document which deep links need a small targeted route improvement.
- Verify that existing summary queries do not mutate or rescore historical benchmark data.

**Deliverable:** concise route/source matrix and a bounded implementation plan. No full product rearchitecture.

### Phase D1 — Functional MVP

- Replace current model list and lifetime KPI cards with a compact ranked headlines list.
- Implement at minimum `benchmark.running`, `benchmark.completed` and `benchmark.interrupted`, where supported by existing persisted state.
- Wire every item to the **actual** run/session detail, including enough context to know the user arrived at the right record.
- Provide correct empty state, recent lookback, deterministic order and refresh behavior.
- Reuse current Mantine styling. No custom dashboard widget framework.

**Release gate:** The homepage contains only genuine, clickable records and is materially more useful than opening Benchmarks directly.

### Phase D2 — Creative Arena integration

- Only after Creative Arena has stable attempt IDs, retained artifacts and working inspection/review routes, add `creative.review_pending` and `creative.completed`.
- Rating an attempt clears its pending-review headline on the next refresh.
- Preview failures do not make retained artifacts inaccessible.

**Release gate:** A completed attempt can be opened directly from Dashboard and evaluated without navigating manually through Creative Arena.

### Phase D3 — Methodology-aware findings (optional later)

- Add only findings backed by existing Compare semantics and real deep links.
- Start with one rigorously comparable event type; avoid large speculative discovery machinery.
- Preserve references to the exact baseline, profiles, suite versions and deployment revisions that established the finding.

**Release gate:** Every record/improvement claim can be reproduced from its destination view. If unable to prove it, do not emit it.

## 9. Acceptance tests (must automate the core cases)

### 9.1 Source-of-truth tests

1. With one running session, one completed sitting and one interrupted job, return three correctly typed headlines pointing to the corresponding identities.
2. With zero data, produce no fake events and show a real empty state.
3. With 140 archived/inactive model records, produce **zero** “unhealthy model” alerts unless an explicitly desired deployment is genuinely failing.
4. A set of axis-specific results from the same sitting yields **one** completion headline, not eight separate items.
5. A smoke-only session is not described as a standard completed run.
6. A job transition `running → completed` changes the headline to a result link, without duplicating the job.
7. A queued/interrupted run is not mislabeled completed.

### 9.2 Navigation tests — essential

8. Click running headline → opens **exact live run** and visible current progress, not generic Benchmarks.
9. Click completed headline → opens **exact stored results** for the intended model/deployment and suite tier.
10. Click interrupted headline → opens **actual diagnostics/recovery surface**; if recovery doesn't exist, show diagnostics without a fake Resume action.
11. Reload each deep-linked page → same underlying record and filter remain selected.
12. Browser Back returns appropriately to Dashboard.
13. Deleted/unavailable record → truthful not-found/expired state; no silent generic redirect.
14. Keyboard-only navigation and accessible link names work.

### 9.3 Refresh and prioritization tests

15. New session/update appears after documented refresh interval; old data never presented as real time without qualifier.
16. Items sort by actionable priority and substantive recency, not alphabetically or by database insertion order.
17. When >8 eligible headlines exist, display at most 8; deterministic selection; no duplicate source events.
18. When a pending-review attempt receives a rating, it disappears from that queue.
19. Headline lists survive normal service restarts using persisted state, rather than relying solely on in-memory websockets.

### 9.4 Findings (only when Phase D3 exists)

20. A comparison of incompatible suites or smoke against standard yields **no** “new best” headline.
21. Historical speed measurements previously mislabeled chunks/sec or effective TPS never generate a decode TPS record headline.
22. Any quality/speed claim links to a comparison that reproduces the same model(s), profile, cohort and outcome on refresh.

### 9.5 Visual regression / product check

23. Dashboard no longer contains the full Models table or the 3 decorative lifetime KPI cards.
24. Primary desktop viewport gives a scannable group of real headlines; mobile and narrow screens keep click targets legible.
25. For every enabled headline type, a test follows its link to verify the promised destination and subject—not just `200 OK`.

## 10. Definition of done

**A successful dashboard implementation is not demonstrated by a screenshot.** It is demonstrated by a short end-to-end walkthrough using actual records in the running application:

- Start a benchmark; observe its live headline; click directly into its console.
- Finish the benchmark; observe completion; click to its persisted result.
- Inspect one real interrupted/failed run through its dashboard headline.
- If Creative Arena is available, complete an attempt; click to the artifact and enter an evaluation; observe pending-review state clear.
- Refresh and revisit bookmarked deep links; each reconstructs its exact detail state.

Show the developer/tester the source query, URL and target record for each demonstrated headline. Any type that cannot pass this walkthrough must be disabled rather than shipped as a placeholder.

Do **not** consider the work done if the page merely looks better, has an attractive activity timeline, includes sample insight text, or links to the generic top of other tabs.

## 11. Explicit non-goals

- No machine-generated prose summaries, daily briefing service, “AI insights,” push notifications or email digests.
- No new analytics warehouse, event bus, data mart, saved-search framework, or durable dashboard database just for this feature.
- No redefinition of benchmark scores, Borda, suite versioning, speed profiles, or methodology gates.
- No new endpoint probing or inference engine telemetry work. This dashboard consumes results from those systems when they already exist.
- No new Creative Arena capability or attempted repair of its implementation; integrate only what is real and stable.
- No replacement of the existing detailed pages, console, model catalog or Compare UI.
- No arbitrary dashboard personalization, drag-and-drop widgets, configurable cards, or generalized visual builder.

## 12. Implementation instruction for Cursor

> Implement **D0 and D1 only** as a tightly bounded change. First inspect the actual router and persistence model; return a short mapping of supported headline types, data sources and exact deep-link targets. Replace the current dashboard with a dynamically generated headline list that shows running, completed and interrupted benchmarks where grounded in real persisted state. Every item must open the exact record or filtered process it describes. Preserve existing database and detail-page functionality. Do not implement hypothetical findings, Creative Arena placeholders or new dashboards widgets. Provide automated navigation and state-transition tests, followed by an end-to-end demonstration. Ship fewer working headlines rather than more impressive-looking dead cards. Implement D2 and D3 as separate tasks only after their underlying capabilities exist.

---

**Design test:** If all existing processes and results were removed from BenchBase, almost all of the dashboard should disappear. If the dashboard still looks full and impressive, it probably isn't meeting this specification.
