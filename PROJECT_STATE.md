# AI Agent Radar — Project State

> Baseline snapshot for the V0 architecture phase. This document describes what is implemented today; it is not a claim about roadmap features.

## Product today

AI Agent Radar is an automated intelligence pipeline running on GitHub Actions. It collects public AI information, filters and deduplicates candidates, uses DeepSeek for bounded semantic classification, renders Markdown reports, persists lightweight state, and can deliver reports by QQ email.

The current system is **not yet a general Agent or Multi-Agent system**. Most control flow is deterministic Python. LLM calls are bounded components inside that pipeline.

## Current modules

### Daily Radar

Entry point: `radar.py`

```text
config + state + weekly trend state
        ↓
HF Daily Papers / Spaces / Competitions / arXiv
        ↓
normalization + cross-source deduplication
        ↓
rule scoring + weekly trend boosts/downranks
        ↓
seen filtering + candidate limit
        ↓
DeepSeek: must_read / scan / skip
        ↓
program validation + Markdown rendering
        ↓
inbox/YYYY-MM-DD.md + state.json
        ↓
GitHub Actions commit + optional QQ email
```

Important behavior:
- HF Daily Papers can fall back up to 3 days when the current day is unavailable.
- Only report items become seen state.
- Missing DeepSeek credentials or AI failure has a rule-based fallback.
- Daily intentionally does not perform long-form "deep reading" through the API.

### Company Radar

Entry point: `company_radar.py`

```text
config + company seen state
        ↓
public company pages
        ↓
noise/navigation/job/social filtering
        ↓
TTL-based seen filtering
        ↓
rule scoring
        ↓
DeepSeek compact classification
        ↓
program rendering
        ↓
company/YYYY-MM-DD.md + state/company_seen.json
        ↓
GitHub Actions commit + optional QQ email
```

The company seen state has a default 14-day TTL, so a URL is not permanently suppressed.

### Weekly Trend Radar

Entry point: `weekly_trends.py`

```text
recent HF / arXiv inputs
        ↓
rule-based candidate term extraction
        ↓
DeepSeek trend refinement
        ↓
tier1 / tier2 / downrank / noise
        ↓
weekly/YYYY-MM-DD.md + state/trending_terms.json
        ↓
Daily Radar consumes the trend state
```

If AI trend refinement fails, the workflow writes a safe empty trend state rather than allowing stale/noisy terms to continue influencing Daily ranking.

## Shared capabilities

The three pipelines already share architectural ideas even though they are not yet extracted into common modules:

- public-source collection
- deterministic filtering and scoring
- bounded LLM classification
- program-side validation/fallback
- Markdown publication
- persisted JSON state
- scheduled GitHub Actions execution

Potential future refactoring should extract shared capabilities only when doing so reduces duplication without destabilizing the working workflows.

## Deterministic vs LLM-controlled boundaries

### Deterministic / application controlled

- workflow scheduling
- source requests and parsing
- normalization
- most noise filtering
- deduplication
- seen-state checks
- rule scores
- candidate limits
- report rendering
- state persistence
- email invocation
- fallback behavior

### LLM assisted

- Daily semantic importance classification
- Company semantic classification/summarization
- Weekly trend refinement

The LLM does **not** currently choose arbitrary tools, dynamically create an execution plan, or control an unbounded action loop.

## State today

| State | Purpose | Lifetime |
| --- | --- | --- |
| `state.json` | Daily seen history | cross-run |
| `state/company_seen.json` | Company URL history | cross-run, TTL based |
| `state/trending_terms.json` | Weekly trend signal consumed by Daily | refreshed weekly |

These are persistence mechanisms, but they are not yet a formal Agent memory architecture. Future work must distinguish run state, session/task state, entity memory, trend memory, and long-term knowledge.

## Execution and delivery

GitHub Actions currently runs three independent workflows:

- Daily Radar
- Company Radar
- Weekly Trend Radar

They install Python dependencies, run the relevant script, commit generated report/state changes, and optionally send email. Workflow concurrency groups prevent overlapping runs on the same ref.

## Current reliability properties

Already present:

- bounded candidate counts before LLM calls
- deterministic fallbacks when AI is unavailable
- state-based duplicate suppression
- TTL for company duplicate suppression
- safe Weekly failure state
- workflow concurrency controls
- no empty Daily report when there is no new content

Not yet implemented as a coherent platform capability:

- Agent step budgets
- no-progress / loop detection
- retry budgets and replanning
- typed tool contracts across an Agent runtime
- persistent checkpoints for Agent execution
- retrieval evaluation
- end-to-end tracing
- business-level success metrics
- queue/worker recovery

## Baseline status

At V0 review time, the latest observed scheduled runs for Daily, Company, and Weekly were successful. V0 intentionally makes no business-logic change to those pipelines.

## Product direction

The target architecture is **Pipeline-first, Agent-enhanced**:

```text
Sources
  ↓
Deterministic collection / normalization / dedup / initial scoring
  ↓
Bounded Agent orchestration where adaptive reasoning adds value
  ↓
Research → Analysis → Verification
  ↓
Memory / retrieval infrastructure
  ↓
Guardrails + evaluation
  ↓
Markdown / email / Web UI
```

A future Agent failure must not unnecessarily destroy the ability to produce a basic Radar result. The stable deterministic pipeline remains the reliability backbone.
