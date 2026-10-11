# V3 Role-separated Research Experiment

V3 adds an **isolated experimental path** for role-separated research. It does not replace Daily Radar, Company Radar, Weekly Learning Radar, or Ask Radar.

## Why this exists

The V2.x bounded Agent proved that adaptive search can be useful, but one model still owned several responsibilities at once: deciding whether to search, forming claims, and deciding when those claims were good enough.

V3 tests a narrower question:

> Does separating evidence collection, claim formation, and claim verification improve inspectability enough to justify Multi-Agent orchestration?

The answer is not assumed in advance. This branch keeps the existing single-Agent path as the baseline.

## Architecture

```text
User question
    |
    v
Deterministic query plan + seed retrieval
    |
    v
Research Agent
  - judges evidence coverage
  - may request bounded follow-up search
  - cannot write final findings
    |
    v
Analyst Agent
  - proposes 1-3 findings
  - must cite retrieved evidence IDs
  - cannot search or execute tools
    |
    v
Deterministic provenance gate
  - citation IDs must exist
  - trend claims need >=2 publication-dated sources
  - research answer needs >=2 distinct sources
    |
    v
Verifier Agent
  - accept/reject only
  - cannot rewrite claims
  - checks claim-to-evidence support and scope
    |
    v
Deterministic provenance gate again
    |
    v
Deterministic Publisher
```

This is deliberately **not** free-form Agent-to-Agent chat.

## Role contracts

### Research Agent

Allowed actions:

- `search_more`
- `ready`
- `insufficient_evidence`

It receives the query plan and current evidence. It cannot produce findings, recommendations, URLs, or final learning cards.

The initial retrieval is deterministic so the first model call is evidence-aware. Follow-up search remains bounded by the existing `EvidenceSearch` request budget.

### Analyst Agent

The Analyst receives only the user question, date window, and selected evidence.

It returns the existing learning-card finding contract:

- topic
- claim
- claim type
- evidence IDs
- application
- small practice
- learning depth
- completion criterion

The existing deterministic `verify_findings` function runs before semantic verification. This prevents the Verifier from being asked to evaluate structurally invalid or invented citations.

### Verifier Agent

The Verifier receives only the proposed findings and their cited evidence.

For each finding it can return only:

- `accept`
- `reject`

It cannot rewrite a claim or invent replacement evidence. This is intentional: otherwise verification quietly becomes a second generation step and provenance becomes harder to inspect.

After semantic rejection, the deterministic provenance rules run **again**. If the Verifier removes one source and the answer no longer satisfies the multi-source gate, the system returns `finished_insufficient_evidence` rather than publishing a weaker answer.

### Publisher

Publisher remains deterministic Python rendering. There is no Publisher Agent.

## Failure isolation

The experiment uses explicit terminal states:

- `finished`
- `finished_insufficient_evidence`
- `failed_research`
- `failed_analysis`
- `failed_verification`

A role failure does not fall back to an unverified model answer.

The scheduled Radar workflows do not depend on this path.

## Run it locally

```bash
python -m pip install -r requirements.txt
python role_research.py "最近医药 Agent 有哪些值得关注的应用层信号？"
```

The run record is written under `state/agent_runs/*-roles.json` by default.

A manual GitHub Actions workflow is also included as **Role-separated Research**. It saves:

- `answer.md`
- `run.json`
- console output

as a seven-day artifact.

## Tests added in V3

`tests/test_role_research.py` checks:

- a successful two-source Research → Analyst → Verifier path;
- semantic rejection followed by a second multi-source provenance gate;
- Research can stop before Analyst is invoked;
- Research cannot take an Analyst-style action;
- `search_more` requires concrete queries;
- Verifier must cover every finding exactly once;
- extra Verifier rewrite fields cannot change the published Analyst claim;
- research-round limits are bounded.

These are structural and orchestration tests. They do not prove real-model semantic quality.

## What this does not prove

V3 still does **not** establish:

- that model-based verification is equivalent to full-document entailment checking;
- that three roles outperform the single-Agent baseline on quality, latency, or cost;
- production deployment evidence for retrieved projects;
- cross-run memory;
- historical RAG;
- general semantic retrieval;
- a need for LangGraph.

The next useful evaluation is an A/B suite using the same questions and evidence windows for:

1. V2.2 single Agent + tools;
2. V3 role-separated path.

Compare accepted claim support, unsupported-claim rate, useful-answer rate, latency, token usage, and failure mode clarity.

Only after that comparison should an orchestration framework be considered. LangGraph is useful when checkpointing, resumability, branching, or more complex state transitions solve an observed problem; it is not required merely to call three model roles.
