# BenchBase Agentic Extension
## Trajectory-level evaluation via OMP, with the T_eff efficiency metric

Companion to the fit/performance estimator spec and the directed-search spec. BenchBase today measures raw capability deterministically, single-turn. This extension adds the layer those scores can't see: multi-step agentic reliability and operational efficiency, measured through a fixed harness against real tasks, producing one headline scalar with a three-factor diagnostic decomposition.

Design stance, inherited from BenchBase: **deterministic verdicts only.** No LLM judges in the scoring path. The harness observes; checkers assert; the only subjectivity permitted is in choosing the tasks.

---

## 1. Architecture

Four fixed components, one variable:

```
Task suite  →  OMP (fixed harness)  →  LiteLLM (per-model profile)  →  vLLM/sparkrun deployment
                                                                        ↑ the only variable
```

OMP is the standardized tool surface — every model faces the identical 31-tool schema, system prompt, and edit mechanics. LiteLLM makes each candidate deployment one profile entry. The unit under test is therefore a **deployment** (package hash + profile), not an abstract model — consistent with the package-identity discipline in the estimator spec. Results are keyed to (package_hash, profile, harness_version, suite_version); a change to any of the four is a new experiment, because harness prompts and tool schemas are as much a part of the measured system as the weights.

Two acknowledged consequences of fixing the harness. Measured capability is "capability *in OMP*" — a model tuned for a different scaffold may underperform its potential; since OMP is the daily-driver harness, this is the relevant quantity, but record it as a scoping fact. And harness upgrades reset comparability: keep an archived OMP version pinned per suite_version, upgrade deliberately, re-baseline the reference model when you do.

Prefix caching stays enabled and constant across all runs — agent loops re-ingest system prompt and tool schemas every turn, and cache behavior is part of the deployment being measured.

## 2. Task definition

A task is a directory containing:

```
task.yaml          # id, title, instruction, category, timeout, seeds, expected: solvable|unsolvable
repo/              # initial state — a git repo, files, fixtures (reset = git clean + checkout)
check.sh           # the oracle: exit 0 = resolved, nonzero = not; runs after the agent finishes
```

Rules for tasks:

- **Drawn from real work.** Tasks come from things actually asked of agents on this stack — sparkrun recipe edits, file wrangling, small feature-with-tests, config debugging, data munging. Invented puzzles predict nothing about your experience.
- **State-checked, never transcript-checked.** `check.sh` asserts on the world (tests pass, file contents, git diff shape, mock-API state), never on what the agent said. This is the τ-bench principle: score the end state, and the trajectory becomes the model's private business.
- **Strict checkers.** A time-pressured metric selects for models that skip verification. The checker is the only defense against rewarding recklessness; when in doubt, assert more. Checkers must also be *checker-tested*: verify each one passes on a known-good solution and fails on the initial state.
- **Sized for statistics.** Target 20–40 tasks, each completable by a competent agent in 2–10 minutes. Long epics have terrible variance-per-hour; short tasks buy the repetitions that pass^k needs.
- **Failure-injection variants.** For a subset of tasks, a mock tool or fixture deterministically fails on first invocation (flaky test, transient API error, locked file). Recovery-after-failure is the most differentiating agentic behavior available at any price; it costs one line per mock.
- **Calibration probes.** A small subset (~10–15%) are `expected: unsolvable` — the task is impossible or critically underspecified (missing credential, contradictory requirements, referenced file absent). Correct behavior is halting with a clear statement of the blocker; `check.sh` for these asserts *non-action* (no fabricated output, no destructive attempts) plus an explicit abstention marker. These probes measure **false confidence** — the trait separating an agent you can leave alone from one you babysit.

## 2b. Fixtures: the subject under test

Tasks need something real to act on. The fixture layer is the expensive part of the suite and gets its own rules.

**Structure.** A single `benchbase-fixtures` git repo holds 2–4 purpose-built projects (e.g., a small REST service with a database, a CLI data pipeline, a legacy module with refactoring seams) — a few hundred lines each, realistic but unglamorous, with *designed seams* where scenarios attach. A task references its fixture as `(fixture_name, base_ref SHA)`; scenarios and fixtures form a matrix (one fixture serves several scenarios; a task = fixture@SHA + card + checker + golden trajectory).

**Instantiation, not reset.** Workspaces are never reverted — reverting misses untracked artifacts, caches, and installed state. Every run instantiates fresh: clone the fixture at its pinned SHA inside a disposable container, run, destroy the container. Verify instantiation by comparing the workspace hash against the fixture's recorded initial state-hash (§6.5 machinery), which also detects fixture drift. Reset occurs at **task** boundaries only; within a task, rounds inherit the agent's own evolving workspace by design — that inheritance is the property under test.

**Contamination.** Never use popular OSS repos as fixtures: they are in training corpora, and passing their tests measures recall, not capability. Purpose-build, or mutate an obscure real project (rename, restructure, re-domain) to break memorization while keeping realism. Fixtures are private by default; anything published is considered burned into future training sets — for community release, publish a subset and retain a private battery (the rotation policy of §5 applies).

**Fixed scenario battery.** The scenario set is fixed per suite version and identical for every candidate — the SPEC-benchmark posture: all between-model variance is signal because the workload is constant. Divergent solutions are expected and required: checkers assert observable behavior, never implementation shape, so structurally different correct solutions pass identically. The golden trajectory proves satisfiability; it is *a* path, not *the* path.

## 3. Execution protocol

Per (deployment, task): run `n` independent seeds (default n = 5; n = 8 for the headline suite when time permits). Each run: reset state → launch OMP with the task instruction → hard timeout from task.yaml → run checker → collect the ledger. Runs are sequential per deployment (no resource contention between candidates on shared hardware — concurrency would contaminate timing).

The ledger per run, harvested from OMP transcripts and LiteLLM logs:

| Field | Source | Feeds |
|---|---|---|
| resolved (0/1) | check.sh | P(success) |
| wall seconds | harness | T_eff |
| total tokens (prompt + completion, incl. thinking) | LiteLLM usage | tokens/attempt |
| turns, tool calls | OMP transcript | diagnostics |
| rejected edits (hashline failures) | OMP transcript | per-step error rate |
| retry loops (same tool+args ≥3×) | transcript analysis | thrash detection |
| abstained (0/1) | checker marker | calibration |

The rejected-edit counter deserves emphasis: OMP's hash-anchored edits fail deterministically when the model's mental picture of a file is stale, so hashline rejections are a free, harness-native measurement of per-step state-tracking error — the "per-step survival probability" made directly observable.

## 4. Metrics

### 4.1 Headline: expected time to resolution

```
T_eff = mean(wall_seconds per attempt) / P(success)
```

Units: seconds per resolved task, computed per task, on solvable tasks only. This is the operational number: how long until the work is actually done, retries included. Its asymptotics are honest — a 50%-reliable model doubles its effective time; a model that cannot do the task diverges to infinity rather than merely scoring low. P(success) uses the same runs that produce pass^k, so consistency reporting comes free: publish pass@1, pass^n, and T_eff together.

### 4.2 The three-factor decomposition

```
T_eff = (tokens per attempt) × (seconds per token) / P(success)
        └─ action economy ─┘   └─ deployment speed ┘  └ reliability ┘
```

Each factor isolates a pathology and names its owner:

- **Tokens per attempt** — action economy. A pure model/prompt property, hardware-independent and therefore portable across deployments. High values are the *spewer*: narration, re-reading, thinking loops that don't convert to state changes. Fix with prompting, thinking budget, or model swap — never with hardware.
- **Seconds per token** — deployment speed. A pure recipe/hardware property, predictable from the roofline model in the estimator spec before any run. Fix with quant, flags (cf. `enforce-eager`), topology.
- **1/P(success)** — reliability. The *reckless over-committer* lives here: cheap attempts, expensive expectation. Fix with model choice, task routing, or harness guardrails; correlates with rejected-edit and retry-loop diagnostics, which localize *where* in trajectories it dies.

Because factor one is hardware-independent and factor two is model-independent, the decomposition predicts T_eff for *unmeasured* (model, deployment) combinations: measured action economy × roofline-predicted speed ÷ measured reliability. That plugs directly into directed search as a calibrated-tier estimate.

### 4.3 Aggregation

Per-task T_eff values span orders of magnitude, so aggregate as SPEC does: fix a **reference deployment** (current default daily driver), compute per-task ratios `T_eff(ref) / T_eff(candidate)`, and take the geometric mean. The headline is one number — "1.4× the reference" — robust to task-size imbalance, stable when tasks are added (re-baseline on suite_version change). Report alongside it: pass^n on solvable tasks, false-confidence rate on probes (fabrication attempts ÷ probe runs), and recovery rate on failure-injection variants.

### 4.4 What is deliberately excluded

Subjective conversation quality stays in its own track (paired comparisons, judged, clearly labeled) and never mixes into T_eff. Token *cost* in currency is omitted — on owned hardware, tokens are priced in seconds, and wall-clock already collects the bill. Partial credit is omitted: a task that would need partial credit is two tasks; split it.

## 5. Interpretation discipline

Three ranked deployments with overlapping T_eff confidence intervals are *tied*; report ties as ties (bootstrap the CI from per-run values — n×tasks runs give enough resamples). Expect the convergence result from the capability radar **not** to reproduce here: means converge under shared training targets, but consistency, recovery, and calibration are not leaderboard-optimized properties, and pass^n / false-confidence spreads are where near-peer models genuinely differ. If they *still* tie on those — that is a real finding, and the correct response is routing by speed and role, with a clear conscience.

Goodhart watch, standing items: models that learn the suite (rotate a held-out subset each quarter); checkers that under-assert (audit any task with a suspiciously high pass rate across all models); timeouts doing the failing (a timeout is a failure *by* the metric but check the transcript tail — a model at 95% completion at timeout is a different animal from one in a retry loop, and only the diagnostics distinguish them).

---

## 6. Interactive mode: the three-actor protocol

Single-instruction tasks (Parts 2–4) measure autonomous execution. Interactive mode adds the dimension they cannot: eliciting requirements from a human who is vague, changeable, and opinionated. Three actors: a **user simulator** (goal-directed LLM), the **agent under test**, and an **evaluator** (checkers first, frontier judge last). The governing principle: interactive runs cannot be replay-deterministic — trajectories branch on the agent's own words — but they must be **policy-deterministic** (every source of randomness pinned) and **verdict-deterministic** (the verdict insensitive to which valid path was taken).

### 6.1 The goal card

Ground truth for each interactive task is a hidden structured card, shared by simulator and checkers, never shown to the agent:

- **Objective** — the true task, stated precisely (this is what checkers assert against).
- **Persona** — tone, expertise level, patience budget (after N clarifying questions, responses become terse; excessive interrogation must cost something, because over-questioning is a real failure mode symmetric to reckless assumption).
- **Information-release policy** — every fact the user "knows," each with a release condition: `volunteered` (stated in the opening message), `on-direct-question`, `on-wrong-artifact` (only revealed when the agent produces something violating it), `never` (a taste preference the agent must intuit or ask about). Facts tagged `must-elicit` feed the elicitation score.
- **Scripted pivots** — mid-task requirement changes with **state-based triggers**, not turn numbers ("after the agent first delivers an artifact, the format requirement changes to CSV"). State-triggering ensures every model meets the pivot at the equivalent moment of *its own* trajectory, which is what makes the pivot fair.

The three difficulty levers requested — lack of specificity, changing criteria, taste — are thus card fields, not simulator improvisation. Difficulty is authored, versioned with the suite, and identical for every candidate.

### 6.2 Determinism budget

Pin: simulator model (package hash — see below), simulator temperature 0, judge model + version, seeds, card version. Accept: trajectory divergence. Absorb: residual stochasticity via n-seed runs and pass^k, which converts noise into a measured consistency statistic. The simulator does not need frontier intelligence — it needs frontier *consistency* — so a pinned local model on the second Spark is preferred over an API frontier model for the role: API snapshots drift silently; a local package hash never does. The judge is where frontier capability is actually worth buying.

### 6.3 Simulator discipline: no mercy, no spite

The simulator releases information solely per the card's conditions — never adapting to how well the agent is doing, never hinting, never punishing. Because it is an LLM it will sometimes violate this; therefore every transcript is **audited post-hoc against the card**: any fact released without its condition met (leak) or withheld when its condition was met (stonewall) invalidates the run before scoring. The simulator is part of the instrument, and instruments get calibrated.

### 6.4 Scoring hierarchy

1. **State checkers** (unchanged from Part 2) — did the end state satisfy the card's objective, including post-pivot requirements. Primary verdict.
2. **Mechanical transcript checks** — elicitation score (must-elicit facts obtained before irreversible action?), assumption count (acting on facts never obtained), pivot response (post-pivot work satisfies new requirement without regression on unchanged ones), question economy (clarifying questions vs. patience budget).
3. **Judge, last and least** — only the axes checkers cannot reach: clarity, tone, UX taste on `never`-tagged preferences. Constraints: *binarized rubric items* ("confirmed the destructive action before executing: Y/N"), not holistic scores — binary items make judge output near-deterministic and auditable; paired comparison against a pinned reference transcript with order-swapping to cancel position bias; judge from a different model family than every agent under test (self-preference bias); judge transcripts stored with results. Judge-derived numbers are reported in their own labeled column, never blended into T_eff.

### 6.5 State lineage and loop detection

After every mutating tool call, hash the workspace state; the hash sequence is the trajectory's **state lineage**. From it, deterministically: cycles (revisited hash = the agent literally undid and redid its way back), thrash (repeated (tool, args) n-grams), spinning (turns with no state change), and a **progress rate** (novel states per turn) as a standing diagnostic. Only *semantic* loops — the agent rephrasing the same doomed plan in fresh words — remain for the judge. Every detector demoted from judge to checker is a gain in determinism and cost.

### 6.6 Instrument verification: golden scenarios and puppet agents

The three-actor apparatus is itself testable, and must be — the field's reference implementation (τ²-bench) shipped tasks whose checkers contradicted their own policies, requiring a third-party verified fork. Verification uses **puppet agents**: scripted, non-LLM actors substituted for the model under test, with required verdicts.

- **Golden puppet** — plays the authored ideal trajectory for the card (asks for the schema, receives it, delivers the ORM implementation). Must pass end-to-end. One run exercises the simulator's release logic, all checkers, transcript metrics, and plumbing, deterministically.
- **Defective puppets** — one per detector, each engineered to trip exactly one: never-asks (elicitation), constraint-ignorer (raw SQL despite correction), looper (state-lineage cycle), fabricator on an unsolvable card (calibration probe), over-interrogator (patience budget).

Any wrong verdict from a puppet invalidates the day's model results. Puppets run in CI on every change to cards, checkers, simulator prompts, or harness version. Each new scenario card ships with its golden trajectory as part of authoring — writing the ideal path is also how the author discovers whether the card is coherent (τ²-bench's failure was, precisely, cards that had never been played through).

### 6.7 Prior art and assembly strategy

Build as little as possible; three existing systems cover most of the machinery:

- **EvoCode-Bench / Harbor** ([arXiv:2605.24110](https://arxiv.org/abs/2605.24110)) — persistent-workspace multi-turn coding evaluation: one container and session across 5–15 rounds, cumulative verifiers swapped per round, fail-stop scoring, snapshot/resume, state lineage. Open-sourced. Use as the execution engine. Its findings independently confirm this spec's premises: single-round scores overstate multi-turn reliability by 22–40 points and change model rankings; pass rates halve by round 5; variance grows with depth; failing rounds consume more tokens; failure modes are tier-dependent (weak agents miss requirements early, strong agents regress late). Note its fail-stop deliberately measures *preservation only* — recovery measurement (our failure-injection variants) remains ours to add.
- **DeepEval** ([multi-turn guide](https://deepeval.com/guides/guides-multi-turn-evaluation)) — `ConversationalGolden` is a lightweight goal card; `ConversationSimulator` is the user-simulator loop; `ConversationalGEval` hosts binarized judge rubrics. Caution: its metric library is predominantly LLM-judged — use it for the simulator scaffolding and the subjective track, never as the deterministic scoring layer.
- **τ²-bench** ([sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench)) — reference for goal-directed user simulation against database-backed tools; its verified fork documents the authoring failure modes §6.6 defends against.
- **openevals / agentevals** ([openevals](https://pypi.org/project/openevals/), [agentevals](https://github.com/langchain-ai/agentevals)) — small MIT-licensed evaluator *primitives* (not a framework): `create_llm_as_judge` with binary scoring implements §6.4's binarized rubric items directly, and accepts a plain OpenAI client pointed at the LiteLLM gateway — so the judge can be a pinned local package hash rather than a drifting API snapshot. `create_json_match_evaluator` (exact mode) serves as a checker primitive for structured outputs. agentevals adds trajectory evaluators for the transcript layer. Preferred over DeepEval for the metric layer precisely because BenchBase owns the runner: primitives compose, frameworks annex. Pin ≥0.2.0.

Remaining original scope: release-condition goal cards with post-hoc simulator audit, failure-injection recovery measurement, puppet-agent instrument verification, T_eff and its decomposition, and integration with the package-hash calibration store and directed search.

**Adoption posture (governing rule).** For any result intended to leave the building: run *published* suites **verbatim**, with each suite's **native harness** (EvoCode → Terminus-2/Harbor; τ² → its own runner) — never a substitute harness, which breaks comparability with published numbers and reopens methodology debates. Report native metrics untouched. The original contribution rides alongside as a pure **operational ledger** — wall-clock, tokens, package hash, hardware profile — from which T_eff is derived arithmetic over standard scores, not a methodology requiring anyone's assent. The publishable gap this fills: leaderboards measure models via frontier APIs at unknown precision; no one publishes established-benchmark results keyed to exact (quant, recipe, hardware) deployments. Custom instruments (goal cards, puppets, OMP task suites) are *internal* — used for routing and calibration decisions where the only required trust is one's own — and are held to this spec's verification regime precisely because they lack external consensus.

### 6.8 Metrics carry over

T_eff applies unchanged — wall-clock and tokens now include conversational overhead, correctly, since an agent needing eight clarifying turns is slower in real use too. The decomposition gains one interactive-mode diagnostic per factor: action economy splits out question economy; reliability splits out assumption-driven failures (fixable by prompting the agent to elicit) vs. execution failures (not). False-confidence probes extend naturally: an interactive card whose objective is unsatisfiable behind a `never`-release fact tests whether the agent discovers the blocker by asking — the deepest form of the calibration test.
