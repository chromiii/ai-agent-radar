# V3 live A/B baseline

Date: 2026-10-07  
Case: `medical-agent-trends`  
Question: `最近医药 Agent 有什么趋势？`

This record compares the V2.2 single-Agent research path with the V3 role-separated path in the same GitHub Actions job and with the same reference date.

It is a **cost / orchestration baseline**, not proof that one answer is semantically better.

## Result

| Metric | V2.2 single Agent | V3 Research → Analyst → Verifier |
| --- | ---: | ---: |
| Status | finished | finished |
| Selected sources | 12 | 12 |
| Search API calls | 6 | 6 |
| Model calls | 3 | 4 |
| Reported total tokens | 15,554 | 18,787 |
| End-to-end path latency | 27.2 s | 39.1 s |
| Published findings | 3 | 3 |

Observed ratios:

- V3 / V2 token ratio: **1.208**
- V3 / V2 latency ratio: **1.436**

The two paths perform their own bounded retrieval, so the source sets can differ even within the same job. These numbers should be treated as one observed run, not a stable benchmark.

## V3 role usage

| Role | Model calls | Tokens | Errors / repair triggers |
| --- | ---: | ---: | ---: |
| Research | 1 | 3,794 | 0 |
| Analyst | 2 | 10,400 | 1 |
| Verifier | 1 | 4,593 | 0 |

The extra Analyst call was a bounded repair after the first response returned invalid JSON.

This exposed a concrete optimization target: role separation itself was not the only overhead. A failed first Analyst response spent 5,933 tokens before the compact repair succeeded with 4,467 tokens total for the second call.

The Analyst prompt was tightened after this run with explicit per-field length budgets and JSON-safe quoting guidance. A future A/B run should check whether this lowers repair frequency and completion-token waste.

## What role separation added

The V3 trace makes three judgments independently inspectable:

1. **Research coverage** — whether the evidence is sufficient and what is missing.
2. **Analyst claims** — what conclusions are proposed from the selected evidence.
3. **Verifier support** — whether each exact claim is supported by its cited evidence.

In this run Research explicitly recorded gaps around industry news, commercial deployment, regulation and real clinical deployment. Verifier returned one accept/reject decision per Analyst finding. The deterministic provenance gate then remained responsible for citation existence, publication-date requirements and the final multi-source rule.

This is a stronger audit boundary than asking one model both to create and approve its own findings. However, one accepted live run does not prove that semantic verification is more accurate overall.

## Product decision from this baseline

Do **not** replace Ask Radar with V3 by default.

Use two modes:

- **Quick learning / Ask Radar — V2.2:** lower orchestration overhead; suitable for ordinary personal learning questions.
- **Verified Research — V3:** use when claim-level evidence review and role traces are worth extra latency and token usage.

This keeps Multi-Agent orchestration tied to a product reason instead of applying it to every request.

## Next evaluation gate

Run the same A/B harness across several existing usability cases, especially:

- `coding-agent-learning`
- `mcp-application-value`
- `agent-memory-changes`
- `medical-agent-engineering`

Track:

- useful-answer rate;
- unsupported-claim rate after human review;
- verifier rejection rate;
- repair rate by role;
- token and latency overhead;
- whether V3 produces clearer failure attribution.

Only after those results should the project decide whether LangGraph checkpointing / branching is justified.


## Follow-up after tightening the Analyst contract

A second live A/B run used the same case after adding explicit Analyst field-length budgets and JSON-safe quoting guidance.

| Metric | V2.2 single Agent | V3 role-separated |
| --- | ---: | ---: |
| Status | finished | finished |
| Selected sources | 12 | 12 |
| Search API calls | 6 | 6 |
| Model calls | 2 | 3 |
| Reported total tokens | 8,548 | 13,875 |
| End-to-end path latency | 16.2 s | 26.9 s |
| Published findings | 3 | 3 |
| Repair / model-format errors | 0 | 0 |

Observed ratios in this run:

- V3 / V2 token ratio: **1.623**
- V3 / V2 latency ratio: **1.653**

Most importantly, the Analyst repair count changed from **1 to 0**. All three V3 findings were accepted by the Verifier and passed the final deterministic provenance gate.

Do not interpret the lower absolute token count relative to the first run as a controlled benchmark improvement: model behavior and the V2 step count varied between runs. The stable conclusion is narrower: the tightened contract removed the observed invalid-JSON repair in this repeat, while preserving a successful verified answer.

The second run also shows that role separation has a real baseline cost even without retries. For this product, that supports keeping V2.2 as the default quick-learning path and V3 as an explicitly selected verified mode.

## Why the learning-card fields were not made fully deterministic

After the second run, the generated Analyst findings were inspected field by field. The visible learning-card content was already compact: topics, claims, applications, concept definitions and completion criteria stayed inside the new budgets.

Replacing domain-specific practice tasks and completion criteria with generic deterministic text would reduce some output tokens, but it would also weaken the main personal-learning value of the Radar. V3 therefore keeps the application-layer teaching fields model-generated for now.

The next optimization should be evidence-quality and verifier evaluation across multiple cases, not shaving tokens by making every learning card mechanically identical.
