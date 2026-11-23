# BenchBase — Future Expansion: Engine Telemetry Adapters & Plugin Ecosystem

**Status:** FUTURE / PROPOSAL — **not authorized for the current implementation sprint**  
**Planning horizon:** “Next-next” (after the current decode-TPS simplification and existing vNext work)  
**Document version:** 1.0 · 2026-11-23  
**Suggested repository location:** `docs/future/ENGINE_TELEMETRY_PLUGINS.md`  
**Related documents:** `DECODE_TPS_FRICTION.md`; `BenchBase_vNext_Addendum_Decode_TPS_v1.0.md`; BenchBase vNext specification

> **Instruction to coding agents:** This document is a future architectural proposal. Do not begin implementing it merely because it exists in the repository. First finish and validate the *current* minimal decode-TPS solution. Do not expand the present PR into an adapter framework, plugin manager, extensive runtime discovery system, or Creative Arena work.

## 1. Executive decision

**Proposed direction:** Add a small, vendor-agnostic *inference telemetry subsystem* to BenchBase, with **engine-family adapters**, a **generic streaming fallback**, and an optional, controlled **plugin interface** for future engines.

BenchBase should not maintain dozens of independent benchmark runners. The existing model-evaluation harness should remain responsible for issuing requests; adapters should be responsible only for discovering, obtaining, and interpreting telemetry about those requests.

**End-user requirement:** A working inference seat should normally produce a numerical speed readout without a special benchmark route or nonportable forcing arguments. The number must always identify **what was actually measured**. Never manufacture decode TPS from incompatible data just to fill a UI cell.

The immediate design goals are:

1. Preserve the familiar headline **decode tok/s** in Models and Compare.
2. Prefer authoritative **per-request, engine-side measurements** when available.
3. Make runtime changes and new forks cheap to accommodate.
4. Avoid making LLManifold, any particular serving engine, or any one GPU vendor a required dependency.
5. Preserve measurement provenance and historical BenchBase results.
6. Keep the future subsystem small enough for community contributions.

**Not an immediate goal:** Supporting every engine named in this document on day one.

## 2. Why this exists

The first decode-speed addendum implemented a fixed 4K-input / approximately 512-token-output test using `llama-benchy --exact-tg`, `min_tokens`, `ignore_eos`, dedicated LLManifold routing, and a strict replicate gate. In production, backends frequently stopped naturally, ignored or rejected forcing arguments, or produced fewer than the 384 tokens required by the headline gate. Successful quality evaluations consequently displayed `— tok/s` or `PARTIAL`.

That architecture conflates two separate properties:

- **Generation performance:** How quickly did a server actually generate tokens after decoding started?
- **Forced-output compliance:** Did the engine obey an artificial request to keep generating until an exact length?

The former is a primary product metric. The latter is at most an optional diagnostic. Requiring the latter to measure the former is not sustainable across a heterogeneous inference fleet.

The nearer-term correction is a simple natural-output, passively observed decode-speed measurement. **This future proposal extends that correction** by adding native telemetry integrations and a maintainable extension mechanism. It must not block the simpler correction.

## 3. Definitions and measurement invariants

### 3.1 Primary quantities

| Quantity | Meaning | Reporting rule |
|---|---|---|
| `decode_tps` | Output generation throughput **after the first generated token** | Headline when a trustworthy decode interval and token count exist |
| `ttft_ms` | Request start to **first generated token**, when observable | Do not confuse with first visible answer |
| `time_to_visible_answer_ms` | Request start to first visible answer content | Especially useful for thinking models |
| `prefill_tps` | Prompt-processing tokens divided by actual prompt-processing time | Only if accurately separable |
| `effective_tps` | Output-token count divided by a whole-request elapsed interval | Fallback metric, **not decode TPS** |
| `output_tokens` | Generated-token count with an explicit scope | Identify visible-only vs all-generated |
| `measurement_method` | Native engine / observed stream / tokenizer-estimated / effective fallback | Mandatory provenance |

Where the engine provides a first-to-last generated-token interval, a common normalization is:

`decode_tps = (generated_tokens - 1) / decode_interval_seconds`

Use this only when the interval covers the same token sequence as the count. An engine's independently defined `predicted_per_second` or `eval_count / eval_duration` may use different boundary conventions; preserve its native figure and definition and normalize only after verification. **Do not blindly subtract one again from an engine-reported native generation rate.**

A generated-token count cannot safely be combined with timestamps for **visible-only** output if hidden reasoning tokens were produced. Similarly, the first received SSE content chunk is not necessarily the first generated token, because proxies and servers may buffer chunks. Record these limitations as provenance.

### 3.2 Measurement is not perfectly deterministic

A server can provide an authoritative measurement for *a particular request*, but no model has one context-free, invariant tokens/sec figure. Relevant conditions include model revision, quantization, runtime version, context length, KV-cache configuration, batching/concurrency, speculative decoding, CPU/GPU offload, warmup and expert-cache residency.

The headline should identify its **profile** (for example, `natural-4k-c1-v1`), repetition count, and method. Display a median across valid observations when repetitions are available; retain individual samples.

### 3.3 Provenance tiers

| Tier | Definition | UI wording |
|---|---|---|
| A | Native **per-request** decode timing and matching token count | **Measured** |
| B | Reliable generated/visible token count plus client-observed first-to-last streaming interval, with known scope | **Observed** |
| C | Correct model tokenizer applied to observed streamed text plus matching observed interval | **Estimated** |
| D | Only end-to-end elapsed time and output-token count | **Effective tok/s**; do not label as decode |
| E | Too little trustworthy evidence to compute any numeric rate | **Measurement failed** with actionable diagnostics; automatic retry or alternate probe |

One or two valid samples may be published with an explicit low-sample qualifier; do not discard an otherwise valid observation merely because the model stopped before an arbitrary output length. Conversely, short or buffered output can make a particular observation intrinsically unreliable: distinguish *sample quality* from *forced-length compliance*.

**Product contract:** Completing a normal BenchBase benchmark with no numerical throughput should be treated as a measurement-collection problem with a remediation path, not silently as a fully measured result. If only tier D is obtainable, display a **numeric effective rate with its accurate label**. If tier E is unavoidable, report a visible failure and its reason rather than inventing a decode number.

### 3.4 Prohibitions

- Never interpret the number of SSE chunks as generated tokens.
- Never call aggregate server or fleet throughput a single-request decode rate.
- Never query `/metrics` and assume its last completed request belongs to BenchBase.
- Never include prefill or first-token waiting in a metric labeled decode TPS.
- Never mix hidden-reasoning token counts with visible-only streaming intervals.
- Never silently merge results from different speed profiles or incompatible measurement methods.
- Never require `min_tokens` or `ignore_eos` for the ordinary headline metric.

## 4. Architecture and separation of concerns

```text
                         BenchBase UI
                  Models / Compare / Speed
                              |
                  Normalized Measurement API
                              |
        +---------------------+--------------------+
        |                                          |
  Existing inference                            Telemetry
  transport / runner                            collector
  (OpenAI-compatible                             |
   or native)                    +-----------------+------------------+
        |                        |                 |                  |
        v                        v                 v                  v
  LLManifold or            Native adapter     Generic stream    Optional plugin
  direct endpoint          (engine family)    observer          adapters
        |                        |                 |                  |
        +------------------------+-----------------+------------------+
                                 |
                Validated per-request evidence
                                 |
                  Normalizer + provenance
                                 |
            Immutable observations / scored views
```

**Transport** issues the request. **Collector** records or obtains evidence. **Adapter** recognizes and interprets engine-specific telemetry. **Normalizer** enforces metric semantics. **Persistence** retains raw evidence and derived numbers. **UI** presents the appropriate qualifier.

Neither benchmark question runners nor Creative Arena should know whether a server is Strata, vLLM, llama.cpp, FreeToken, or another engine.

### 4.1 Proxy boundaries: LLManifold

BenchBase must work with LLManifold *and* direct inference-server connections. A proxy might strip usage fields, change request IDs, coalesce chunks, or hide engine-specific metrics. Therefore:

- Store a **public inference URL** and, optionally, a separate **private telemetry URL** for each deployment. These may be different services.
- Record whether timing was obtained **before or after the proxy**.
- Prefer explicit request correlation: client-generated correlation ID, engine request ID, or a verified mapping established by the proxy.
- Preserve ordinary usage and timing metadata as faithfully as the proxy permits. This is a desirable LLManifold integration enhancement, not a requirement to fork LLManifold.
- Never query privileged native admin APIs through an untrusted URL supplied by a model or an uploaded benchmark response.
- When per-request correlation cannot be established under concurrency, fall back to client observation rather than reading a possibly unrelated native metric.

## 5. Core normalized record

The exact storage schema is to be reconciled with existing BenchBase migrations; the following is a semantic contract, **not a mandate to immediately change the database**.

```json
{
  "schema_version": "telemetry.v1",
  "benchbase_run_id": "uuid-for-run",
  "benchbase_request_id": "uuid-for-request",
  "deployment_revision_id": "immutable-deployment-fingerprint",
  "engine": {"family": "vllm", "variant": "upstream", "version": "detected-version"},
  "adapter": {"id": "builtin.vllm", "version": "1.0"},
  "profile_id": "natural-4k-c1-v1",
  "request": {
    "concurrency": 1,
    "thinking_mode": "off",
    "requested_max_output_tokens": 1024,
    "prompt_tokens": 4096
  },
  "measurement": {
    "decode_tps": 57.8,
    "native_decode_tps": null,
    "effective_tps": null,
    "output_tokens": 483,
    "token_scope": "all_generated",
    "decode_interval_ms": 8339,
    "ttft_ms": 380,
    "method": "engine_per_request",
    "confidence": "measured",
    "sample_qualifier": "valid"
  },
  "provenance": {
    "source": "response.metrics",
    "correlation": "matched_request_id",
    "raw_evidence_ref": "internal-artifact-id"
  }
}
```

**Example values are invented and illustrative.** Field values and presence must reflect the actual backend. Fields that cannot be measured remain `null`, not zero. The raw payload or securely redacted capture should remain available for independent review.

Record additional relevant configuration: accelerator type/count, model revision and quantization, KV-cache dtype/size, context occupancy, runtime flags, offload placement, request sizes, concurrency, and any speculative-decoding settings that materially affect comparison. Keep hardware-specific diagnostic fields in an optional `extras` namespace rather than expanding the common contract for every engine.

## 6. Extensible adapter contract

Favor a **small, versioned Python interface** plus *declarative field-mapping plugins* for simple engines. The following is conceptual pseudocode:

```python
class EngineTelemetryAdapter:
    id: str
    api_version: str = "telemetry-adapter-v1"

    async def detect(self, endpoint_info) -> "DetectionResult": ...
    async def capabilities(self, endpoint_info) -> "Capabilities": ...
    async def from_response(self, request, response) -> "Evidence | None": ...
    async def from_stream(self, request, events) -> "Evidence | None": ...
    async def fetch_request_metrics(self, request, telemetry_client) -> "Evidence | None": ...
```

An adapter **does not** run benchmarks, modify user prompts, choose models, decide rankings, manage GPUs, or install software. It identifies what telemetry is available and returns evidence with precisely documented units and token scope.

### 6.1 Capability discovery

A deployment-specific detection result should include:

- Engine family, variant/fork and reported version, with confidence.
- API protocol (`openai_chat`, `openai_responses`, `ollama`, `llama_native`, custom).
- `per_request_decode_timing`: `yes | no | unknown`.
- `native_output_token_count`: `yes | no | unknown`.
- `streaming_timestamps`: supported client-side unless the stream is nonincremental.
- `hidden_reasoning_accounting`: `yes | no | unknown`.
- `request_correlation`: `verified | unverified | unavailable`.
- Required, *explicitly approved*, read-only metrics endpoints or launch flags.

Detection must be **side-effect-free by default**. Optional active probes must be opt-in, inexpensive, and performed only against configured endpoints.

### 6.2 Adapter precedence

1. Operator-pinned adapter (if compatible).
2. Exact native engine/version adapter with verified probe.
3. Compatible family adapter (schema-based matching, not project-name matching).
4. Generic streaming observer.
5. Explicitly labeled effective-throughput fallback.

If two adapters identify the same endpoint, provide the operator a clear conflict/override mechanism. Cache detection against a deployment revision, with re-detection on version or configuration change.

### 6.3 Plugin packaging

**Phase-one plugin support** may simply be a static registry of trusted in-repository adapters. Later public distribution can support:

- A manifest with plugin ID, author, adapter API version, supported protocols and detection rules.
- A declarative mapping for JSON response fields and permitted endpoint paths.
- Python plugins only where field mapping is insufficient.
- Compatibility checks and contract tests before enabling.
- Visible installation/version/disable/override controls.
- No automatic execution of repository-provided plugins on import.

**Security:** Treat downloaded plugins as executable code, not harmless configuration. Community Python adapters require deliberate installation and trusted execution/isolation. Constrain HTTP telemetry access to administrator-configured hosts; implement timeouts, size limits, credential isolation, redaction, SSRF protection and read-only access. Never let an inference model choose a plugin URL or metrics target through prompt content.

## 7. Engine-family coverage plan

This is an **investigation and prioritization list, not a promise that all engines have native per-request telemetry**. Forks can reuse an adapter only after schema and timing semantics are verified. A project being “OpenAI-compatible” proves nothing about whether native telemetry survives the API boundary.

### Phase A — first-class built-ins

| Family | Proposed investigation | Important caution |
|---|---|---|
| **vLLM** | Optional per-request response metrics (`generation_time_ms`, token counts, mean ITL) | Its field named `tokens_per_second` may include prefill; do not copy as decode TPS |
| **llama.cpp** | Native completion timing (`timings`, predicted tokens/s) | Some compatible endpoints expose different fields from native routes |
| **Strata family** | Request-correlated `decode_tok_s` or corresponding native record | Variants may diverge; do not assume `/metrics` is per-request or correlatable |
| **SGLang** | Request-level benchmark/tracing if available; otherwise observed streaming | Prometheus TPOT histograms are aggregate, not attributable to a particular request |
| **Generic OpenAI-compatible** | Passive streaming timestamps + reliable usage/tokenizer | Hidden reasoning, proxy chunk buffering, and missing usage require qualifiers |
| **Ollama** | Native `eval_count` and `eval_duration` on native API | Check phase definitions and units before claiming exact first-to-last decode equivalence |

### Phase B — priority community/experimental engines

**Priority to investigate**, based on the lab's actual use: **Project Maya**, **FreeToken / FreeToken-Kai**, **unbiased Strata**, **PolyStrata**, and other Strata forks. Add adapters only where native metrics offer reliable additional information beyond the generic collector. Prefer reusing upstream adapters when the schema truly matches.

### Phase C — broad ecosystem candidates

The following registry is intentionally comprehensive enough to guide future contributors. **It is not an implementation backlog requiring one PR per name**.

| Ecosystem | Candidate engines / frontends |
|---|---|
| Fast architecture-specific / experimental | NInfer (`ninfer-serve`, NInfer Studio), NInfer GPU-specific forks (`ninfer-3090`, `ninfer-3080`, `ninfer-gb10`, Windows/V100 forks), DwarfStar (`ds4`), Splash, llamAmpere, gufo, minfer |
| MoE streaming / offloading | Strata, Strata Metal, PolyStrata, Project Maya, FreeToken / FreeToken-Kai, Edge0 variants, KTransformers, Colibri, AirLLM, PowerInfer / PowerInfer-2, Fiddler, Prima.cpp, ik_llama.cpp |
| High-throughput serving | vLLM, SGLang, NVIDIA TensorRT-LLM, Hugging Face TGI, LMDeploy, Aphrodite Engine, LoRAX, LightLLM, RayLLM |
| Turnkey serving / product wrappers | Ollama, LM Studio, Jan, Docker Model Runner, Microsoft Foundry Local, GPT4All, Msty, Lemonade Server, LocalAI, AnythingLLM, llama-swap, Pinokio, Backyard AI, Text Generation WebUI / Oobabooga |
| Foundational and hardware-specific | llama.cpp, Llamafile, Mullama, MLX / MLX-LM, oMLX / mlx-serve, ExLlamaV2 / ExLlamaV3, TabbyAPI, KoboldCpp, MLC LLM, ONNX Runtime GenAI, Intel OpenVINO, BitNet.cpp, Candle, Mistral.rs, Burn, WebLLM |

Some entries are client wrappers or launchers, not standalone inference engines. Discovery must distinguish **front-end product**, **API protocol**, and **actual model execution backend** to avoid double-counting compatibility. Names and project health are time-sensitive; verify their current existence and telemetry interfaces before accepting a contributor's adapter.

## 8. Product and operator experience

### 8.1 Endpoint registration

When an operator adds a deployment:

1. Enter inference URL, model alias, and optionally telemetry URL.
2. Select **Auto-detect** or pin a known adapter.
3. Run one inexpensive **Telemetry Test** using normal inference semantics.
4. Show detected engine, available fields, correlation confidence, and method tier.
5. Save the verified adapter selection with the deployment revision.

Do not ask the user to rename LLManifold routes, configure `ignore_eos`, install bench-only models, or alter inference defaults merely to obtain a speed metric.

### 8.2 Visible results

**Models and Compare:** Headline `57.8 tok/s` and a small method label such as `Measured · vLLM`, `Observed · stream`, or `Effective · estimate`. Display profile (`4K natural, c1`), repeat count and timestamp in details. The UI should not drown a simple number in operational badges.

**Details:** Show individual samples, context length, TTFT, prefill (where available), token counts, hidden-reasoning handling, runtime and adapter versions, and provenance. Explain why results are not strictly comparable when profiles or scopes differ.

**Adapter settings:** List installed adapters, enabled/disabled, recognition status, supported versions, diagnostics, and manual override. Basic deployments should be usable without ever opening this screen.

### 8.3 Comparison policies

- Do not blend native engine measurements with end-to-end rates in a single unlabeled ranking.
- Prefer homogeneous protocol/profile cohorts for strict speed comparisons.
- Permit visually comparing qualified observations across engines, but surface provenance on hover or drill-down.
- Keep quality Borda rankings independent from inference speed.
- Preserve all original observations if a future adapter corrects a timing interpretation; derived values should be versioned/recomputed, not overwritten.

## 9. Diagnostics and operational behavior

Provide concise, actionable states, not generic `PARTIAL`:

- **Native metrics not enabled:** Instructions to enable an optional vLLM feature, *without requiring it* for a fallback.
- **Telemetry endpoint inaccessible:** Identify which configured endpoint failed; continue with ordinary streaming.
- **Request correlation unavailable:** Explain why fleet aggregates cannot represent a specific request.
- **Output too short:** Automatically retry with a natural long-response prompt if necessary; publish a qualified short observation where defensible.
- **Hidden reasoning not observable:** Publish an accurately labeled visible-output or effective rate; avoid implying it includes hidden tokens.
- **Proxy buffered output:** Mark streaming timing unreliable; try native timing or an alternate profile.
- **All methods fail:** Record an explicit measurement failure with a reproducible diagnostic bundle. Do not mark a numeric decode result as zero.

An adapter failure must not crash the benchmark, corrupt another result, or take down the inference server.

## 10. Testing requirements

Test at least:

1. vLLM per-request `generation_time_ms` with correctly matched token count and units.
2. vLLM's end-to-end `tokens_per_second` **rejected** as direct decode TPS.
3. llama.cpp native timing parsed without double-adjusting first-token conventions.
4. Ollama nanosecond duration converted correctly; native phase documented.
5. SGLang aggregate Prometheus data **rejected** for a specific unrelated request.
6. Strata `/metrics` containing concurrent requests; correlation required before assignment.
7. A natural EOS after 200 output tokens; a usable observation is not rejected solely for missing 384/512.
8. Single-token output, zero/negative durations, dropped stream, missing final chunk and timeout.
9. Hidden reasoning with output-count/stream-scope mismatch.
10. Buffered chunks with exact counts but unreliable first-to-last token timestamps.
11. LLManifold stripping nonstandard metadata: fallback still works without bench route changes.
12. Engine fork with unexpected telemetry fields: safe fallback rather than silent misinterpretation.
13. Untrusted endpoint or plugin attempting to access a local admin service: blocked.
14. Restart and migration: previous scorecards and historical TPS values remain unchanged and visibly distinguished.
15. Independent and concurrent requests: no cross-contamination of token counts or timing.

Use recorded HTTP/SSE and telemetry fixtures, including example implementations with no native fields. Tests should run offline and should not require access to any of the author's actual machines.

## 11. Phased future implementation

| Future phase | Scope | Exit criterion |
|---|---|---|
| **F0 — Reconnaissance** | Audit current speed runner, existing fields, proxy behavior and at least 3 live backend response schemas | Minimal-change proposal; no database changes |
| **F1 — Normalized evidence** | Define versioned evidence record and collector interface; preserve raw samples | Tests for token/timing scope and all provenance tiers |
| **F2 — Built-in adapters** | vLLM, llama.cpp, Strata family, SGLang, Ollama, generic streaming | Every supported adapter passes recorded real-format fixtures |
| **F3 — Endpoint discovery** | Deployment-specific probing, pinning, status and safe private telemetry URL | Operator can add a seat without special speed routes |
| **F4 — Plugin registry** | Versioned manifests, declarative mappings, limited Python adapters, validation | Community adapter installs/enables/disables without changing benchmark runners |
| **F5 — Long-context and MoE diagnostics** | 32K/64K profiles; expert-cache and KV telemetry where available | Context/speed curves with provenance, not a universal aggregate claim |
| **F6 — Public distribution** | Sample adapters, extension author guide, fixtures, compatibility matrix | Third party can contribute an adapter via documented tests |

**Dependencies:** Complete the simpler decode-TPS fix first. Reconcile with the actual repository schema and current work-package plan. Implement phases as separately reviewable PRs; the table is not an instruction to implement F0–F6 in one session.

## 12. Explicit non-goals

- Replacing existing benchmark questions, scoring or creative application evaluations.
- Mandating LLManifold or direct engine access exclusively.
- Requiring changes to upstream inference servers to use BenchBase.
- Running arbitrary shell commands supplied by a telemetry plugin.
- Creating a universal server-side `/metrics` standard in the first release.
- Claiming **one** TPS number fully characterizes long-context or concurrent performance.
- Supporting every engine or fork in the candidate registry immediately.
- Treating a best-effort tokenizer estimate as equivalent to native server telemetry.

## 13. Final acceptance criteria for the future feature

This future expansion may be considered complete at its intended initial scope when:

- A normal, non-forced request through a supported engine yields a correctly labeled TPS observation automatically.
- Native request telemetry is used when trustworthy and attributable; generic streaming is available otherwise.
- Each measurement carries engine, model/deployment revision, adapter version, timing definition, token scope, provenance and confidence.
- A new engine adapter can be added without changing model benchmark runners or the Compare UI's core logic.
- An upstream fork with altered metrics does not silently produce plausible-but-wrong numbers.
- Metrics plugins cannot silently reach arbitrary hosts, execute privileged operations, or read unrelated secrets.
- Historical scores and raw measurements survive migrations without fabricated reinterpretations.
- The adapter registry has a contributor-facing example, validation fixtures, and a version compatibility policy.
- The everyday UI still answers the simple question first: **“How many tokens per second?”**

## 14. References and points requiring verification

These references document actual native capabilities; they do **not** verify every fork and release in the candidate registry.

- [vLLM per-request metrics](https://docs.vllm.ai/en/latest/features/per_request_metrics/) — opt-in response metrics; verify version and supported APIs.
- [vLLM generation timing definition](https://docs.vllm.ai/en/latest/api/vllm/entrypoints/generate/base/serving/) — decode interval excludes queue/prefill; similarly named overall TPS can include them.
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) — native `timings` / generated-token speed fields.
- [SGLang production metrics](https://sgl-project.github.io/references/production_metrics.html) — production histograms and TPOT; do not assume per-request correlation.
- [SGLang serving benchmark](https://github.com/sgl-project/sglang/blob/main/docs/docs/developer_guide/bench_serving.mdx) — benchmark instrumentation and request metrics.
- [Ollama API usage documentation](https://github.com/ollama/ollama/blob/main/docs/api/usage.mdx) — `eval_count` and `eval_duration` on native API.
- [Time Token Tracker example](https://github.com/owndev/Open-WebUI-Functions/blob/main/filters/time_token_tracker.py) — useful lightweight UI precedent, but its total-request timing is not necessarily strict decode timing.

**Research still required:** precise per-request native telemetry interfaces and version-specific timing semantics for unbiased Strata, PolyStrata, Project Maya, FreeToken and forks; LLManifold metadata forwarding guarantees; safe correlation between routed request IDs and native metrics.

---

**Product principle:** *A single understandable TPS figure should be easy to obtain. Accurate provenance should be available when someone wants to inspect it. Neither goal should make the other impossible.*
