# V4 Historical Radar Memory + Hybrid Retrieval

V4 turns the committed Radar history into a rebuildable knowledge layer. It does **not** replace the Daily / Company / Weekly pipelines and it does not store opaque model-generated “memories” as facts.

## Product goal

Before V4, Ask Radar and Verified Research could answer “what is happening now?” from fresh external search, but they had no durable way to answer:

- Have we seen this topic before?
- Is this signal new or recurring?
- How many Weekly Radars promoted this topic?
- When did a company first/last appear?
- Which old Radar entries are relevant to today’s question?

V4 adds that missing cross-run context.

## Source of truth

The durable sources remain the human-readable committed reports:

```text
inbox/*.md
weekly/*.md
company/*.md
```

Derived files such as `state/history/index.jsonl` are caches. They are ignored by Git and can be deleted and rebuilt at any time.

This avoids a second hidden database becoming more authoritative than the reports that created it.

## Memory layers

V4 keeps different state meanings separate.

### Run State

Still owned by the Agent execution:

- current step;
- observations;
- selected evidence;
- retries;
- terminal status.

Run State is transient and must not become long-term knowledge.

### Seen State

Existing pipeline deduplication remains unchanged:

- `state.json`;
- `state/company_seen.json`.

Seen State answers “did the pipeline already process this URL?”, not “what do we know about this entity?”

### Entity Memory

Derived from Company Radar sections.

For each recognized company/entity:

- number of Radar dates on which it appeared;
- first seen;
- last seen;
- recent items;
- report provenance;
- original external URLs.

Example real-corpus entities include Manus, MiniMax, Mistral News, Anthropic News, Cursor Changelog and others.

### Trend Memory

Derived from the rendered Weekly Tier 1 / Tier 2 sections.

For each term:

- appearance count;
- Tier 1 count;
- Tier 2 count;
- first/last seen;
- recent per-week tier history.

This lets “agent memory 最近有什么变化？” retrieve a compact temporal record rather than a pile of duplicated daily hits.

### Historical Knowledge

Report sections are indexed as searchable documents with:

- report date;
- report kind;
- title;
- text;
- report path;
- report URL;
- original external URLs;
- optional entity.

Repeated observations of the same underlying external URL are collapsed into one retrieval result with:

- `observation_count`;
- `first_seen`;
- `last_seen`;
- `observation_dates`;
- `source_paths`.

## Retrieval

The first implementation intentionally uses deterministic lexical retrieval instead of embeddings.

```text
query
  -> existing query/topic planner
  -> English tokens + Chinese bigrams
  -> BM25-style scoring
  -> hard topic gate when a known domain is recognized
  -> time / report-kind / exact-memory boosts
  -> recurrence aggregation
  -> top historical observations
```

Known domains such as MCP, memory, RAG and healthcare use a hard topical gate. A query recognized as MCP history must actually contain MCP / Model Context Protocol evidence; generic “agent/tool” overlap is not enough.

Exact Trend Memory or Entity Memory matches receive additional priority for “变化 / 趋势 / 历史 / history / trend” style questions.

## Hybrid retrieval

`HybridEvidenceSearch` combines local history with the existing bounded external search.

```text
Historical Radar (local, zero API calls)
              +
HF / arXiv / GitHub / optional Tavily
              |
              v
       bounded evidence set
```

Ask Radar and V3 Verified Research use this hybrid search by default.

Historical lookup does not consume the external API-call budget.

Set:

```yaml
history:
  enabled: false
```

to fall back to the original external-only behavior without building the history index.

## Provenance contract

Historical evidence uses:

```text
date_kind = radar_observed
provider = radar_history
```

A Radar observation means:

> this project/topic/entity appeared in a previous Radar report on this date.

It does **not** mean:

> this is a new independent publication on this date.

Therefore:

- `radar_observed` never satisfies the two-published-source gate for a current trend claim;
- repository `updated` dates remain activity signals, not publication dates;
- a hybrid Ask/Verified Research answer must cite at least one non-historical source;
- history-only exploration remains available through the dedicated Historical Memory CLI/workflow.

This prevents two old Radar reports about the same paper from being mistaken for two independent sources.

## Commands

Build the derived index:

```bash
python historical_memory.py build
```

Search historical Radar:

```bash
python historical_memory.py search "最近 agent memory 有什么变化？"
```

Inspect one trend:

```bash
python historical_memory.py trend "agent memory"
```

Inspect company/entity memory:

```bash
python historical_memory.py entity "Manus"
```

GitHub Actions also exposes **Historical Radar Memory** for a build + search run and preserves the derived index as a seven-day artifact.

## Real-corpus validation

On the V4 PR corpus, the derived build produced:

- **1,834** searchable documents after adding derived memory records;
- **15** company/entity memories;
- **44** Weekly trend memories.

The build completed in well under a second on GitHub Actions after dependencies were installed. The derived artifact was roughly 350 KB.

For:

```text
最近 agent memory 有什么变化？
```

the top result became the derived Trend Memory:

- 11 Weekly Radar appearances;
- 2 Tier 1 appearances;
- 9 Tier 2 appearances;
- first seen 2026-05-14;
- last seen 2026-10-03.

A leaderboard that had appeared on 14 Daily Radar dates was collapsed into one recurrence record rather than occupying 14 result slots.

## Ask Radar integration validation

The first hybrid Ask preview proved that historical and external evidence could coexist in one Agent run.

A later MCP preview exposed overly broad historical matching: generic Agent records were being returned because of shared words such as “agent” and “tool”.

V4 added the hard topic gate and reran the MCP case. The unrelated historical records disappeared; the Agent correctly used only current MCP evidence in that 30-day window.

That behavior is intentional: history should improve an answer only when relevant history exists.

## Why no vector database yet

The current corpus is small enough that rebuilding and scoring the lexical index is cheap. A vector store would add:

- embedding lifecycle/versioning;
- persistence and migration concerns;
- semantic false positives;
- another dependency and failure mode.

V4 therefore treats embeddings as an optimization to justify with retrieval evaluation, not a prerequisite for calling the system “RAG”.

Good reasons to add hybrid vector retrieval later include:

- lexical recall failures on paraphrases;
- entity aliases that cannot be handled cleanly by rules;
- corpus growth large enough to make rebuild/search latency material;
- measured reranking gains on a labeled retrieval set.

## Current limitations

- report parsing is Markdown-structure based; older generic “必看索引” sections can still be coarse-grained;
- Entity Memory currently comes from Company Radar naming conventions;
- Trend Memory reflects the Radar’s own curation history, not objective industry prevalence;
- historical snippets are not full source documents;
- no semantic embeddings or learned reranker yet;
- no user-learning-history memory yet;
- no automatic contradiction resolution beyond the source/date metadata.

These are explicit next-stage problems rather than hidden claims of capability.
