> **V6 update:** The user opted into publicly committed non-sensitive learning progress. V6 adds a public Actions workflow for explicit updates, so the private-only limitations below describe V5's original design rather than the V6 configuration. See [V6 architecture](V6_MEMORY_NEWS.md).

# V5 Learning Memory (opt-in)

Learning Memory is separate from V4 Historical Radar Memory.

- **Historical Radar Memory:** what the Radar observed in the world.
- **Learning Memory:** what the user *explicitly* marked as saved, studied, practiced or skipped.

Generating a card, receiving email, opening a report or viewing an Ask answer **never** creates or advances learning progress.

## Status model

| Status | Meaning | Next recommendation |
| --- | --- | --- |
| saved | bookmarked, not studied | return to it for a 15–30 minute session |
| studied | read/understood at a self-reported level | prioritize the original hands-on task |
| practiced | user says they completed the exercise | deprioritize the same source; when a new source in the same topic arrives, focus on novel implementation/edge cases |
| skipped | user explicitly postponed this source | do not recommend automatically until it is re-marked |

"Practiced" is **not a skill certificate** and does not imply mastery of the entire topic. A completed Agent Memory exercise does not automatically complete a different Agent Memory card.

## Stable card identity

The identifier is derived from a canonical *primary source URL*:

\`lc-<first 12 chars of sha256(canonical-url)>\`

The same arXiv item reached through HF, arXiv v1, or arXiv v2 retains its card ID. If an item has multiple primary sources or its primary source changes, its identity may change; the next phase can introduce a more explicit concept ID.

The CLI parses only the **这周先学什么** section and never treats trend lists or generic Radar links as learning cards.

## Local usage

The **first-ever** listing does not create state.

\`\`\`bash
python learning_memory.py catalog
\`\`\`

Copy a card ID from the current weekly report, then explicitly mark progress:

\`\`\`bash
python learning_memory.py mark lc-xxxxxxxxxxxx saved
python learning_memory.py mark lc-xxxxxxxxxxxx studied
python learning_memory.py mark lc-xxxxxxxxxxxx practiced
python learning_memory.py mark lc-xxxxxxxxxxxx skipped
\`\`\`

The same ID can be re-marked; the latest status becomes active, with up to 20 status-change records kept for a bounded audit trail. Repeating the same status does not add a new record.

To use an older Weekly file:

\`\`\`bash
python learning_memory.py catalog --weekly weekly/2026-10-03.md
python learning_memory.py mark lc-xxxxxxxxxxxx practiced --weekly weekly/2026-10-03.md
\`\`\`

You can also record progress from an Ask Radar artifact (only completed, verified answers qualify):

```bash
python learning_memory.py catalog --ask ask_results/run.json
python learning_memory.py mark lc-xxxxxxxxxxxx practiced --ask ask_results/run.json
python learning_memory.py recommend --ask ask_results/run.json
```

The ID printed inside a learning card corresponds to its preferred source, so you can copy it instead of calculating a hash. For mixed historical/current evidence, Ask uses a non-historical source as its primary ID whenever available.

Inspect your private state and see prioritized next cards:

\`\`\`bash
python learning_memory.py status
python learning_memory.py recommend
\`\`\`

If you want to isolate the memory for a second person/device, choose a separate file:

\`\`\`bash
python learning_memory.py --memory /path/to/private.json catalog
python learning_memory.py --memory /path/to/private.json mark lc-xxxxxxxxxxxx studied
\`\`\`

You can also set \`RADAR_LEARNING_MEMORY_PATH\`, or configure \`learning_memory.path\` in \`config.yaml\`.

## Product integration

- **Weekly:** builds the public Weekly Markdown exactly as before. If private progress exists, also generates \`state/private_recommendations/YYYY-MM-DD.md\`. This *separate* recommendation report contains your progress-aware next actions; it is not committed or emailed.
- **Ask Radar:** when a local private memory file exists, appends a tailored next-action section to its already-ignored \`ask_results/answer.md\`. The model's source/evidence validity rules are unchanged. On hosted/public GitHub Actions, the optional personal advice is suppressed to prevent leaking progress through a public workflow artifact.
- **Daily and Company:** unchanged.
- **Trend Memory:** unchanged; no personal preference data enters global Weekly trend ranking/state.

Personalization is deliberately deterministic, not another unconstrained LLM judgment:
1. **New source:** prioritize it.
2. **Saved:** make it an actionable pending task.
3. **Studied:** recommend completing the hands-on exercise.
4. **Practiced same source:** no basic repetition.
5. **New source in a previously practiced topic:** recommend comparisons, new implementation details and error recovery instead of the same basic explanation.
6. **Skipped:** hide from top recommendations.

The process never makes an inference such as "you mastered RAG" merely from a completed exercise.

## Storage and privacy

The repository is public. Learning records are **not** committed to the repo and should not be pasted into Issues/PR descriptions.

\`\`\`text
state/learning_progress.json            # private, gitignored
state/private_recommendations/*.md      # private, gitignored
\`\`\`

Writes are atomic, and the default file is set to owner-only permissions on Unix-like systems. They contain a card title, source URL, topic, manual status and update history, but no free-form private notes.

GitHub Actions jobs do not currently share a durable private progress store. Therefore **hosted Weekly and Ask runs do not magically remember your progress across runs**. This is an intentionally honest boundary: do not start publishing private progress into the public Git repository just to make cloud synchronization appear to work.

Future options for **opt-in** cloud persistence should include a user-controlled private repository or properly encrypted storage with explicit secret management. Until one is added, local progress is the functional persistence path.

## Verification

Unit tests cover:

- source-canonical card IDs and Weekly extraction;
- no implicit learning from generated or read reports;
- explicit manual status updates and idempotence;
- topic-aware next-action ranking;
- skipped items and existing exercises;
- invalid ID/status/schema checks;
- Ask Radar optional memory section;
- Weekly report privacy isolation to gitignored sidecar.

## Deferred

- encrypted GitHub Actions cross-run persistence;
- per-concept prerequisite graph;
- spaced repetition scheduler;
- editable private notes;
- user assessment/quiz-based verified mastery;
- confidence-weighted topic profiles.

These should not be represented as implemented in V5.
