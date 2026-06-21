# Local LLM Benchmark Dashboard Product Definition

## Purpose
Create a single web-based evaluation surface for locally hosted LLMs exposed through OpenAI-compatible endpoints such as LiteLLM. The product solves the current fragmentation problem: existing tools tend to measure only one dimension well, such as throughput, prompt comparison, or academic benchmark accuracy, which makes it hard to judge specialist local models in one place.[1][2][3]

## Problems to Solve
The first problem is fragmentation. Speed testing, coding benchmarks, reasoning benchmarks, and tool-use evaluation are usually spread across separate utilities, leaving no unified view of trade-offs between quality and performance.[1][2][4]

The second problem is comparability over time. Local model testing often changes across quantizations, runtimes, hosts, and prompt sets, so results become anecdotal unless each run is captured with consistent metadata and displayed side by side.[3][4]

The third problem is relevance. Generic benchmark tools do not fully represent practical agent workflows, especially instruction following and tool calling, so the product needs room for custom task packs in addition to standard public benchmarks.[2][5][4]

## Product Scope
The product should present one dashboard for four evaluation areas:

- Serving speed: latency, time to first token, prompt processing, generation throughput, and stability under repeated runs.[1]
- Coding ability: standardized code-generation and test-passing benchmarks such as HumanEval-style tasks.[2][5]
- Instruction following and tool use: scenario-based evaluations that verify schema adherence, action selection, and tool-call correctness.[4]
- Complex problem solving: established reasoning suites such as GSM8K-, MMLU-, or similar benchmark families that provide comparable scores across models.[5][6]

The product should not try to become a new benchmark framework. It should act as an orchestration and visualization layer over proven existing runners.[1][2]

## Best-Fit Existing Software
| Need | Best-fit software | Why it fits |
|---|---|---|
| Serving performance | llama-benchy | Designed for OpenAI-compatible endpoints and focused on latency, throughput, and related runtime metrics.[1] |
| Standard academic and coding benchmarks | LiteBench or lm-evaluation-harness-style runners | Existing benchmark ecosystems already cover tasks like HumanEval, GSM8K, and MMLU through reusable harnesses.[2][5] |
| Broader quality checks including tool use | Purpose-built custom eval pack, potentially informed by existing quality benchmark products | Off-the-shelf tools are weaker on realistic local-agent workflows, so custom task definitions are the best fit here.[4] |
| Reference pattern for combined results UI | Emerging benchmark dashboards such as opencode-benchmark-dashboard | Shows that a combined latency-and-correctness dashboard pattern is viable, even if it is not yet a complete turnkey solution.[3] |

## Suggested Technological Fixes
Use a single web application as the control plane and results surface, while delegating benchmark execution to specialized existing tools behind the scenes.[1][2]

Use a persistent results store so every run records the model endpoint, backend runtime, quantization, host, benchmark suite, and date. This fixes the common problem of benchmark results becoming disconnected from the exact model configuration that produced them.[3][4]

Use a plugin-style benchmark registry so standard suites and custom tool-use tasks can appear in the same UI without forcing one scoring method onto every test family.[2][4]

Normalize outputs into a common scorecard that keeps raw benchmark scores visible but also groups them into the four product dimensions users actually care about: speed, coding, tool use, and complex reasoning.[1][2][5]

## Success Criteria
The product succeeds if a user can select several local models, launch a benchmark run, and view one coherent results page that shows performance and capability trade-offs together rather than across disconnected tools.[1][3]

It also succeeds if repeated runs produce a trustworthy baseline for future model swaps, quantization changes, and runtime experiments without requiring spreadsheet-based manual analysis.[3][4]

## Tech Stack
This should be a Python-based CLI runner with the ability to interface with the website frontend. The project dependencies are managed through UV and using pyproject.toml. The project should use:
- FastAPI for interfacing with the command line and gathering information
- a SQLite or Postgres SQL local database for maintaining scores
- TypeScript React using the Mantine library

The entire project should be runnable in a Docker container, which can be managed through Portainer. 

All dependent applications and frameworks should be stored in the Docker container such that the entire stack could be enabled or disabled at the same time and without a lot of local dependencies. If there are a number of installs, they should go in one folder. 

## End user features and Usability 
This is a local application. No authentication is required. 
There should be a Settings Panel with an expandable list of configuration options. This should sync to persistent settings stored in YAML or .env files. 
It should be straightforward to connect to the LiteLLM portal exposing a variety of models. These should become available for comparison in the web interface. It should be possible to do head-to-head comparisons of different models' scores after running a sequence of related tests. 
There should be a subjective arena mode where it's possible to talk to multiple models simultaneously. The same prompt will be sent to each model, and the results viewed in real time with metrics such as:
- time to first token
- tokens per second
- throughput
- token counts both in and out

There should be light and dark theming. Easily switchable. 
