# AI Agent Radar — Project State

> Updated for V2.2 learning usability. Scheduled pipeline descriptions retain the V0 baseline; isolated Agent capabilities are listed separately below.

## Product today

AI Agent Radar is an automated intelligence pipeline running on GitHub Actions. It collects public AI information, filters and deduplicates candidates, uses DeepSeek for bounded semantic classification, renders Markdown reports, persists lightweight state, and can deliver reports by QQ email.

Production control flow remains deterministic Python. An experimental bounded single Agent is available separately; Multi-Agent and historical RAG remain planned.

## Release snapshot

| Release | Capability | Status at this review |
| --- | --- | --- |
| V0 | Baseline architecture and decisions | On main |
| V1 | Saturday application-layer learning cards | On main, PR #2 merged |
| V2 | Bounded Weekly-evidence Agent | On main via PR #3; experimental execution path |
| V2.1 | External source search, query expansion, dated citations, usability cases | On main; one medical live case and excerpt-level review recorded |
| V2.2 | Ask Radar input, shared learning cards, readable evaluation and usage reports | Implementation in this change; validation recorded in docs/V2_2_USABILITY.md |

`learning_agent.py` uses `research_search.py` for fixed source APIs: HF papers, arXiv, GitHub repository metadata, optional Tavily excerpts. Source collection, time windows, deduplication and action/citation checks remain application controlled; the model chooses among three allowed actions and writes structured findings. Alias expansion and lexical filtering are implemented; embeddings, vector search, historical RAG, and an independent semantic verifier are not.

`research_eval.py` separates synthetic replay, actual network retrieval, and live model evaluation. See `docs/V2_1_RESEARCH.md` for evidence and limitations. A replay pass is not a live-model validation result.

`ask_radar.py` accepts a 1–600 character question, saves a readable Markdown answer and source trace, and publishes the answer to the GitHub Actions run summary. `learning_cards.py` supplies the shared teaching contract and renderer for Weekly and research answers. Cards need a definition, application, 2–4 learning points, a 15–30 minute practice and an observable completion criterion. These structural checks do not establish semantic correctness or actual exercise duration.

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
        + application-layer learning cards
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

The production LLM calls do not choose arbitrary tools. The isolated Agent can choose `analyze`, `search_more`, or `finish` inside a 1–10 step budget. External search shares an API-request budget, uses only fixed endpoints, and treats all retrieved content as untrusted.

## State today

| State | Purpose | Lifetime |
| --- | --- | --- |
| `state.json` | Daily seen history | cross-run |
| `state/company_seen.json` | Company URL history | cross-run, TTL based |
| `state/trending_terms.json` | Weekly trend signal consumed by Daily | refreshed weekly |
| `state/agent_runs/TASK_ID.json` | Isolated Agent decisions, query plan, source metadata, errors, findings | one run, ignored by git |

Agent JSON records are inspection artifacts, not resumable checkpoints or long-term memory. Default IDs are unique; explicit output paths remain caller controlled.

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
- isolated Agent step and search-request budgets
- repeated-query suppression and no-progress stopping
- source failures isolated for the current run
- external finding IDs must refer to retrieved dated sources
- normal insufficient-evidence outcome, separate from model failure

Not yet implemented as a coherent platform capability:

- retry budgets and replanning
- typed tool contracts across an Agent runtime
- persistent checkpoints for Agent execution
- model-quality / semantic citation-entailment evaluation
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
