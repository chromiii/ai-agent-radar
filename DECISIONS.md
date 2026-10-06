# Architecture Decisions

This file records important engineering choices and the reasons behind them. Decisions should be updated when evidence changes.

## ADR-001 — Keep the deterministic pipelines as the reliability backbone

**Status:** Accepted

**Decision:** Daily, Company, and Weekly remain deterministic top-level pipelines. Agent capabilities are introduced as bounded stages or separate execution paths rather than replacing all control flow.

**Why:** Fetching, normalization, deduplication, persistence, rendering, and delivery have known steps and do not benefit from open-ended reasoning. Making them Agent-controlled would increase cost and failure modes without adding product value.

**Consequence:** A future Agent layer should degrade gracefully to a simpler pipeline result where possible.

---

## ADR-002 — Do not claim Multi-Agent before role boundaries exist

**Status:** Accepted

**Decision:** V0 is documented as an AI-assisted pipeline, not a Multi-Agent platform.

A component becomes a distinct Agent only when it has a defensible combination of:
- a distinct responsibility;
- a clear input/output contract;
- constrained tools/permissions;
- context isolation or specialist information;
- independent testability; or
- useful parallelism.

**Why:** Multiple LLM prompts or personas are not, by themselves, useful Multi-Agent architecture.

---

## ADR-003 — Target Multi-Agent shape: Research → Analyst → Verifier

**Status:** Planned, not implemented

**Decision:** The first production-oriented Multi-Agent shape should be small:

```text
Orchestrator
    ↓
Research Agent
    ↓
Analyst Agent
    ↓
Verifier Agent
    ↓
Publisher (deterministic where possible)
```

Source fetchers are tools/workers unless later evidence justifies Agent autonomy. Publisher should primarily be deterministic formatting rather than another free-form Agent.

**Why:** These roles correspond to genuinely different failure modes: missing evidence, poor interpretation, and unsupported claims.

---

## ADR-004 — Memory is infrastructure, not an Agent

**Status:** Accepted

**Decision:** Memory will be modeled separately from Agent roles.

Target categories:
- Run State — current execution, step budget, observations, errors;
- Seen State — duplicate suppression already present today;
- Entity Memory — history for companies/projects/models/entities;
- Trend Memory — topic observations across runs;
- Knowledge/Retrieval Store — source-backed historical documents for RAG;
- User Preference Memory — optional product preferences, kept separate from factual knowledge.

Long-lived factual memory should carry source, timestamp, version/provenance where possible, validity/TTL where appropriate, and conflict handling.

**Why:** Mixing transient execution state and long-term facts creates stale-memory and concurrency bugs.

---

## ADR-005 — Introduce LangGraph only when conditional bounded execution is implemented

**Status:** Planned

**Decision:** V0 adds no LangGraph dependency. A later phase may introduce it for a small Agent path with explicit state, conditional routing, `max_steps`, and termination rules.

**Why:** Adding an orchestration framework before there is adaptive control flow would be framework-driven development rather than problem-driven development.

---

## ADR-006 — Build RAG after memory boundaries and evaluation questions are clear

**Status:** Planned

**Decision:** Do not immediately add a vector database. First define what historical questions the product must answer and what metadata/citations are required. Then implement ingestion, chunking, lexical/vector retrieval, hybrid retrieval and reranking incrementally.

**Why:** A vector database is not a RAG architecture by itself. Retrieval quality must be diagnosable.

---

## ADR-007 — Web UI is a product surface, not the system of record

**Status:** Planned

**Decision:** A future web application will expose Radar outputs, trends, entity history, source evidence, run health and Agent activity. The backend/persistence layer remains authoritative; UI state must not become the only copy of system state.

Likely evolution:

```text
existing Python pipelines
        ↓
shared application/service layer
        ↓
FastAPI
        ↓
Web UI (React/Next.js candidate)
```

The exact frontend stack is not locked in during V0.

---

## ADR-008 — Prefer incremental infrastructure

**Status:** Accepted

**Decision:** Start with the smallest storage/deployment technology that satisfies the current phase. Do not add Redis, Qdrant, Kafka, Kubernetes or similar infrastructure solely for portfolio appearance.

**Why:** Every dependency must solve an observed reliability, scale, retrieval, concurrency, or deployment problem.

---

## ADR-009 — Documentation must distinguish implemented, validated, experimental and planned

**Status:** Accepted

**Decision:** Architecture documentation and README claims must not present roadmap functionality as shipped functionality.

**Why:** The repository should be defensible in an engineering interview and useful to future maintainers/agents.

---

## ADR-010 — Add real source discovery before orchestration frameworks

**Status:** Experimental, V2.1

**Decision:** Extend the isolated bounded Agent with HF/arXiv/GitHub discovery and optional Tavily. Retain Weekly-only mode for regression. Introduce no new runtime dependency or production scheduler.

**Why:** The medical-Agent usability case exposed a retrieval bottleneck: no control-flow framework can recover sources missing from the Weekly report. Keep original query, alias expansion, date window, API calls, filter counts and source metadata visible.

**Limits:** Alias expansion and lexical relevance are not general semantic search. Repository metadata and abstracts are incomplete evidence. Failed source APIs and missing Tavily configuration are disclosed, not silently treated as comprehensive coverage.

## ADR-011 — Date and evidence level are part of the answer contract

**Status:** Experimental, V2.1

**Decision:** Reject unknown/old/future dates for recent findings; canonicalize the same HF/arXiv paper; require citation IDs from selected evidence. At least two distinct sources support a research answer. A finding labeled trend needs two distinct publication-dated sources; pushed repositories support activity signals.

**Why:** A real link alone does not establish freshness, independent evidence, or a trend. Keep application implications and suggested experiments attached to each finding.

**Limits:** The verifier checks structure/provenance. It cannot prove semantic entailment, source independence in the scientific sense, deployment, or clinical efficacy.

## ADR-012 — Evaluation has three distinct verification levels

**Status:** Implemented harness, V2.1

**Decision:** Offline replay uses clearly labeled synthetic sources and scripted decisions; retrieval evaluation makes network calls without generating findings; live evaluation calls the configured model and requires human review. Do not merge their success counts.

**Why:** Deterministic tests should detect regressions without network/cost/randomness. Their success cannot prove model quality. Keep evidence-level metrics visible so multiple repository updates are not mistaken for validated recent publications.

## ADR-013 — Make learning outputs useful before adding more orchestration

**Status:** V2.2 implementation

**Decision:** Add a free-question Actions entry using repository secrets. Weekly and research answers share a card contract and renderer: definition, application, learning depth, learning points, a small timeboxed practice, an observable completion criterion and validated source references. Keep technical traces in a separate JSON artifact.

**Why:** A cited research paragraph alone does not give the user a manageable learning task. Existing examples also need broader real-model evaluation before additional architecture is justified.

**Limits:** A schema can check required fields and timebox values, but cannot prove that a task fits the timebox or that a citation entails a claim. Recorded token usage is not a currency cost estimate. Excerpt-level review is separate from structural PASS and full-document validation.


## ADR-014 — Keep quick learning and verified research as separate execution modes

**Status:** Experimental, V3

**Decision:** Keep V2.2 Ask Radar as the default quick-learning path. Add V3 Research → Analyst → Verifier as an explicit verified-research mode rather than replacing every Agent request with Multi-Agent orchestration.

V3 role authority is intentionally narrow:

- Research may assess evidence coverage and request bounded search, but cannot publish findings.
- Analyst may propose source-backed findings, but cannot execute search/tool actions.
- Verifier may accept or reject exact findings, but cannot rewrite claims or invent replacement evidence.
- Publisher remains deterministic.
- Deterministic provenance checks run before and after semantic verification.

**Why:** Live A/B runs show that role separation adds inspectability but also measurable latency/token overhead. The product benefit is strongest when claim-level evidence review matters; ordinary learning questions do not automatically justify that cost.

**Observed baseline:** In one post-prompt-tightening live medical-Agent case, V2.2 finished with 2 model calls / 8,548 reported tokens / 16.2 s, while V3 finished with 3 calls / 13,875 tokens / 26.9 s. Both produced three findings from 12 selected sources. This is one run, not a stable quality benchmark.

**Consequence:** Multi-Agent is a product mode with an explicit reason, not a repository-wide default. Future evaluation should compare claim support, verifier rejection quality, repair frequency and failure attribution across several cases.

**Framework consequence:** Do not introduce LangGraph merely because V3 now has three roles. Reconsider it only if persistent checkpoints, resumability, branching/re-entry, human approval, or more complex state transitions solve an observed problem that the current bounded Python executor cannot handle cleanly.
