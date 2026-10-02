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
