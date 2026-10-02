# AI Agent Radar — Agent Product Roadmap

This roadmap describes intended evolution. **Planned items are not implemented features.** The existing Daily / Company / Weekly pipelines remain the reliability backbone throughout the migration.

## Release naming and current stage

The original V0 roadmap below uses architecture-stage labels. Actual releases have now shipped as **V1 = application-layer Weekly cards**, **V2 = bounded learning Agent**, and **V2.1 = real source search + usability evaluation**. Future stage labels below are planning labels, not release numbers or implementation claims.

V2.1 is merged via PR #3. The medical live case confirmed a real model/source path and exposed prompt-scope and output-format problems, which were corrected. One case does not establish quality across the product.

Current focus: V2.2 learning usability. The primary product is a personal Agent learning radar: a short Weekly report or an on-demand question should explain what to know, where it applies, how deeply to learn it and one small practice task. Implement free questions through Actions, use one learning-card contract for Weekly and research, and run all eight real-model scenarios with explicit review of relevance, source support and exercise scope. Preserve latency and reported token usage without inventing a currency cost.

Next gate: complete this usable learning path and classify the observed failures. Then choose semantic reranking, state/checkpoint recovery or role separation when it solves a measured problem. Learning history, historical RAG and a Web UI remain later work.

## North-star product

AI Agent Radar should evolve from automated report generation into a source-backed AI intelligence product that can:

1. continuously collect AI research, products and company updates;
2. reliably produce Daily / Company / Weekly Radar even when advanced AI features degrade;
3. adaptively research ambiguous/high-value topics with bounded Agent execution;
4. use specialist Agent roles only where role separation improves quality;
5. remember entities and trends across runs with provenance and freshness;
6. answer questions over current + historical Radar knowledge with citations;
7. expose reports, history, Agent activity, evidence and system health through a web product.

## Architecture principle

```text
Reliable pipeline first
        +
Bounded intelligence second
        +
Memory / retrieval third
        +
Product surface and production infrastructure as justified
```

## V0 — Baseline and architecture contract

**Status:** implemented by documentation branch; no business-logic change.

Goals:
- freeze the current architecture as source of truth;
- document deterministic vs LLM boundaries;
- record state semantics and current reliability behavior;
- define the Pipeline-first / Agent-enhanced product direction;
- record architecture decisions before adding dependencies.

Artifacts:
- `PROJECT_STATE.md`
- `ROADMAP_AGENT.md`
- `DECISIONS.md`

Exit criteria:
- existing Radar workflows unchanged;
- latest baseline understood;
- roadmap functionality clearly marked as planned.

## Stage 1 — Bounded single-Agent experiment (released as V2)

**Status:** implemented as an isolated experiment and merged via PR #3; extended by V2.1.

Learning goals:
- fixed workflow vs conditional workflow vs ReAct-style execution;
- explicit Agent state;
- conditional routing;
- bounded execution.

Small target task:

> Find notable Agent framework updates from the past 7 days.

Proposed state includes:

```text
task_id
user_query
plan
current_step
max_steps
observations
selected_items
last_action
no_progress_count
status
final_answer
```

Allowed decisions initially:

```text
search_more
analyze
finish
```

The existing scheduled Radar pipelines stay operational and are not replaced by this experiment.

Exit criteria:
- hard step limit;
- explicit terminal states;
- deterministic test for bounded execution;
- failure experiment documented;
- interview explanation comparing DAG and Agent execution.

## Stage 2 — Agent reliability and tool contracts

**Status:** planned.

Add:
- no-progress detection;
- duplicate action detection;
- retry budget;
- replan/terminate behavior;
- typed/validated tool input schemas;
- deterministic validation before execution;
- permission boundaries for future side effects.

Exit criteria:
- a reproducible loop failure test;
- malformed tool call tests;
- no infinite retry path.

## Stage 3 — Memory model

**Status:** planned.

Separate:

```text
Run State
Seen State
Entity Memory
Trend Memory
Historical Knowledge
User Preference Memory (optional)
```

Entity/trend facts should carry source and time metadata. Define TTL/validity and conflict behavior before adding a vector store.

Product examples:
- show how often an entity appeared in the last 30 days;
- distinguish a new event from a repeated marketing link;
- compare today's topic signal with previous Radar runs.

Exit criteria:
- state/memory schemas documented and tested;
- transient retry counters never leak into long-term memory;
- stale/conflicting memory behavior defined.

## Stage 4 — Multi-Agent analysis layer

**Status:** planned.

First candidate roles:

### Research Agent
Determines whether available evidence is sufficient and requests bounded additional retrieval when needed.

### Analyst Agent
Evaluates relevance, novelty, relationships and trend implications from supplied evidence.

### Verifier Agent
Checks citations, source support, duplicates and unsupported claims. It can reject/downgrade a claim but should not silently invent replacement evidence.

### Publisher
Prefer deterministic rendering/templates. Do not make Publisher an Agent unless a future product requirement justifies autonomous behavior.

Communication should use structured contracts, not unconstrained Agent-to-Agent chat.

Exit criteria:
- role-specific input/output schemas;
- minimum necessary context per role;
- role-specific tests;
- documented comparison against a single Agent + tools baseline.

## Stage 5 — Historical RAG

**Status:** planned.

Build a searchable knowledge layer from Radar history and selected source material.

Incremental capabilities:
- ingestion and canonical document IDs;
- chunking + metadata;
- query rewrite/expansion while retaining original query;
- keyword/BM25 retrieval;
- vector retrieval;
- hybrid fusion;
- reranking;
- citation/provenance;
- metadata/ACL filtering where relevant.

Evaluation should distinguish ingestion, chunking, embedding, recall, reranking and generation failures.

## Stage 6 — Evaluation, security and observability

**Status:** planned.

Evaluation:
- task success;
- retrieval recall/relevance;
- citation correctness;
- classification quality;
- latency;
- cost.

Security:
- treat web pages, papers and retrieved documents as untrusted content;
- test prompt injection;
- keep tool authority in application policy, not retrieved text.

Tracing:

```text
request/session
  → task
  → run
  → step
  → retrieval / tool / LLM
  → validation
  → final result
```

Record model/prompt/tool-definition versions where practical.

## Stage 7 — Web product

**Status:** planned.

Initial user-facing surfaces:
- Today / Must Read / Worth Scanning;
- Company Radar;
- Weekly trends;
- article/detail evidence view;
- entity history;
- trend history;
- run health and Agent activity;
- source/citation links.

Later candidate feature: **Ask Radar** — cited questions over current and historical Radar knowledge, with bounded current-source research when historical retrieval is insufficient.

Backend direction: reuse/extract Python application logic, then expose a small API (FastAPI is a candidate). Frontend direction: React/Next.js is a candidate. These choices are intentionally not locked during V0.

## Stage 8 — Production execution and recovery

**Status:** planned and only justified after product behavior is stable.

Potential capabilities:
- API/worker separation;
- persistent checkpoints;
- idempotency;
- concurrent task isolation (`user_id`, `session_id`, `task_id`, `run_id`, `step_id`);
- bounded exponential backoff + jitter;
- timeout/circuit breaker/backpressure;
- graceful degradation;
- queue-aware scaling;
- Docker;
- Kubernetes only if deployment/scale requirements justify it.

## Phase rule

For every implementation phase:

1. explain the engineering concept;
2. identify the concrete Radar problem it solves;
3. design the minimum implementation;
4. make a small, reviewable code change;
5. add tests and a failure experiment;
6. run validation;
7. document what changed and what remains experimental;
8. prepare a concise interview explanation;
9. stop before implementing the next phase.
