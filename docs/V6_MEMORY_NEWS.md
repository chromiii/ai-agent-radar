# V6 — LangChain-first Learning, Long-term Memory and News Desk

## What changed

The product has two separate clocks:

1. **Daily silent ingestion** from Daily/Company pipelines. They continue to collect and commit evidence but send no routine email.
2. **One Saturday weekly briefing** containing curated source-linked news, selected Company updates, Breaking Desk statuses, and your next LangChain lesson.

Breaking News is an exception: a **manually approved and manually initiated** email can be sent between weekly briefings. A scheduled six-hour official-release scan only proposes candidates; it never sends email.

This change is layered on V5 and is not live on the default branch until the stacked PRs are merged.

## Long-term memory architecture

Never put all "memory" into one unversioned conversation transcript. Use five distinct responsibilities:

| Layer | Source of truth | Update trigger | Retention and guardrail |
| --- | --- | --- | --- |
| External observations | Daily, Company, Weekly Markdown / official release URLs | Source ingestion | Preserve report date, source and external URL. Observations do not prove publication or trend |
| Historical knowledge | Rebuildable V4 index and Trend/Entity memory | Reindex committed reports | Date filters, dedup and provenance. Delete the index safely and rebuild |
| Learning progress | Public, explicit \`state/learning_progress.json\` | Manual \`saved/studied/practiced/skipped\` choice | Never infer from opening or receiving a report. Keep bounded event history and allow re-mark |
| Lesson progression | Public \`state/learning_path.json\` | Manual \`studying/practiced/reviewed/skipped/reset\` choice | Stable **concept IDs**, prerequisites and recommended review at 1, 7, 30 days; this is not validated mastery |
| Single-run Agent state | V2/V3 run JSON; eventual LangGraph checkpointer | Agent steps/retries | Ephemeral, bounded, not a substitute for long-term cross-run knowledge |

Breaking News has a **separate lifecycle queue** \`state/breaking_queue.json\`: pending → approved / dismissed → resolved. Observations do not silently overwrite a human decision.

### Memory governance

- **Write authority:** only explicit user actions change learning state; new source content changes observations, not competence.
- **Provenance:** source URL, report day, stable key, manual status and timestamps are persisted.
- **Conflict resolution:** newer human marks supersede older active status; past transitions remain in bounded event history. The \`reset\` action undoes assumed lesson progression without claiming forgetting.
- **Expiry and refresh:** 7-day news windows; historical observations are dated and reindexed; lesson reviews are suggestions after 1/7/30 days. Old concepts are not assumed wrong or forgotten based on time alone.
- **Compaction:** derive short summaries or recommended next lessons from canonical state. Never promote generated narrative summaries into a new source of truth.
- **Retrieval:** first apply task/domain filter, then date/provenance checks, then rank; include only a small relevant slice in an Agent prompt. Do not dump every previous week's report into context.
- **Safety:** public learning state was explicitly approved; do not commit access tokens, passwords, raw personal notes, resumes or arbitrary secrets. Keep \`.env\` and API keys in GitHub Secrets. Note that public learning activity is visible to repository readers.

Future semantic facts need an explicit \`fact_id\`, primary source, valid-from/valid-to, confidence, and \`superseded_by\`/retraction semantics. This **verified fact memory is not implemented** in V6; neither are background autobiographical memory extraction or full LangGraph Store.

## LangChain-first learning path

\`curriculum.yaml\` provides stable lesson IDs separate from the source-specific \`lc-...\` news card IDs.

1. \`lc01-runnables\`: LangChain Runnables / deterministic composition
2. \`lc02-prompts-messages\`: Prompt and messages
3. \`lc03-model-tools\`: tool schema, validation, execution boundaries
4. \`lc04-create-agent\`: modern \`create_agent\` and bounded tool calls
5. \`lc05-retrieval\`: document/chunk/retriever basics
6. \`lc06-rag-citations\`: cite sources and verify claims
7. \`lc07-thread-checkpoints\`: LangGraph run state, \`thread_id\` and checkpoint
8. \`lc08-long-term-store\`: cross-thread Store, namespaces and memory governance
9. \`lc09-routing-evaluation\`: multi-Agent routing and evaluation, only after simpler building blocks

Use modern LangChain docs instead of old \`initialize_agent\`, \`LLMChain\` or \`ConversationBufferMemory\` tutorials. Runnables can be introduced before API keys or agent orchestration.

Start lesson 1:

\`\`\`bash
pip install -r requirements-learning.txt
python examples/learning/langchain_01_runnables.py
python learning_path.py next
\`\`\`

After actually doing the exercise:

\`\`\`bash
python learning_path.py mark lc01-runnables practiced
python learning_path.py next
\`\`\`

Review later:

\`\`\`bash
python learning_path.py mark lc01-runnables reviewed
\`\`\`

The same progress actions are available using **Actions → Update Public Learning Progress** after merge. The action only accepts a known lesson or an actual Weekly learning card and commits the explicit status. No email reading or inactivity changes it automatically.

## News architecture

\`\`\`text
Daily / Company scheduled collectors (silent)
         |                     |
         v                     v
    committed reports      deduplicated observations
         |                     |
         +-----------+---------+
                     |
                     v
                Saturday
             weekly_briefing.py
       news + company + breaking queue
             + LangChain next lesson
                     |
                     v
            ONE normal email
\`\`\`

\`weekly_briefing.py\` writes \`briefings/YYYY-MM-DD.md\`. It never claims an observed Radar date was the actual original publication date.

### Breaking Desk workflow

\`\`\`text
Daily/Company reports ──┐
                        ├─> significance rules -> pending
official GitHub releases┘                |
                                         +-> dismiss
                                         +-> approve -> optional manual notify -> resolve
\`\`\`

The watch inspects a small fixed allowlist of official GitHub release feeds every six hours:
LangChain, LangGraph, Deep Agents, CrewAI, and LlamaIndex.

Only explicit high-impact signals are candidates (security advisory, breaking API change/outage or a major release). Negated phrases such as "not an outage" are suppressed. No model is allowed to automatically approve an item or invent an impact claim.

Useful commands:

\`\`\`bash
python breaking_news.py scan --lookback-days 7
python breaking_news.py watch
python breaking_news.py list
python breaking_news.py mark bn-xxxxxxxxxxxx approved
python breaking_news.py notify bn-xxxxxxxxxxxx
python breaking_news.py mark bn-xxxxxxxxxxxx resolved
\`\`\`

\`notify\` requires an already approved item and configured QQ SMTP secrets. It records \`notified_at\` after successful delivery, and retries on the same completed item will not resend. SMTP is an external side effect; a crash between successful transmission and state commit is a narrow at-least-once delivery risk.

The action **Breaking News Desk** exposes watch, scan, mark and notify separately; scheduled watch never invokes notify.

### Important non-claims

- The six-hour watcher is not a guaranteed real-time alert service; GitHub Actions scheduling is best-effort.
- Official GitHub release notes are a limited, first-party subset of AI news. Broader coverage remains the Daily/Company reporters.
- A single matching source is only a candidate, not a verified breaking story.
- No automatic urgent email is emitted on a raw candidate.
- Regular mail goes once per week, but a *user-approved manual Breaking Alert* can be sent between weekly emails.
- Current news compilation is deterministic extraction and deduplication, not deep LLM fact checking.

## PR rollout

PR chain: \`main <- V3 PR #5 <- V4 PR #6 <- V5 PR #7 <- V6 PR #8\`.

Do not assume any of these workflows operate on default-branch schedules before merge. Merge the stack in dependency order; then check the first week's GitHub Actions run and verify email configuration.
