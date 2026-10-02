"""Separate offline replay, real retrieval acceptance, and live model evaluation."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from dataclasses import asdict
from pathlib import Path
from zoneinfo import ZoneInfo

from learning_agent import AgentState, ROOT, load_config, run_agent
from research_search import EvidenceSearch, SearchBatch, build_query_plan, rank_evidence


class ReplaySearch:
    def __init__(self, items):
        self.items, self.used_calls = items, 0

    def search(self, plan, queries, selected_urls):
        self.used_calls += 1
        items, rejected = rank_evidence(self.items, plan, selected_urls)
        return SearchBatch(items, [{"provider": "synthetic_fixture", "status": "ok", "queries": queries,
                                   "retrieved": len(self.items), "rejected": rejected}], [])


def replay_decider(state):
    """Scripted acceptance harness; never presented as a live model answer."""
    def decide(messages, config):
        if not state.observations:
            return {"action": "search_more", "query_terms": [state.user_query], "reason": "replay retrieval path"}
        if len(state.selected_items) < 2:
            return {"action": "finish", "verdict": "insufficient_evidence", "findings": []}
        findings = [{"topic": item["title"], "claim": item["summary"], "claim_type": "signal",
                     "evidence_ids": [item["id"]], "application": "测试记录来源、日期和失败边界。",
                     "try_next": "编写一个带工具调用日志的最小复现。"} for item in state.selected_items[:2]]
        return {"action": "finish", "verdict": "answer", "findings": findings,
                "limitations": "Synthetic fixture plus scripted decisions; not real findings or model-quality evidence."}
    return decide


def evaluate_case(case, mode, config, today, fixture_items=None):
    started = time.monotonic()
    state = AgentState(task_id=case["id"], user_query=case["query"], search_mode="external", as_of=today.isoformat())
    if mode == "retrieval":
        plan = build_query_plan(case["query"], today, config.get("learning_agent", {}).get("lookback_days", 30))
        searcher = EvidenceSearch(config)
        batch = searcher.search(plan, plan.expanded_queries, set())
        state.query_plan, state.selected_items, state.search_trace = asdict(plan), batch.items, batch.trace
        state.warnings, state.search_calls, state.status = batch.warnings, searcher.used_calls, "retrieval_complete"
    elif mode == "replay":
        searcher = ReplaySearch([] if case.get("fixture") == "empty" else fixture_items)
        state = run_agent(state, "", config, decide=replay_decider(state), searcher=searcher)
    else:
        state = run_agent(state, "", config)
    insufficient = state.status == "finished_insufficient_evidence" and case.get("allow_insufficient", False)
    checks = {
        "query_expansion": not case.get("must_expand") or len(state.query_plan.get("expanded_queries", [])) > 1,
        "topic_understanding": set(case["topics"]).issubset(state.query_plan.get("topics", [])),
        "search_path_executed": bool(state.search_trace),
        "sources": len(state.selected_items) >= case["min_sources"] or insufficient,
    }
    if mode != "retrieval":
        checks.update(completed=state.status in ("finished", "finished_insufficient_evidence"),
                      findings=bool(state.findings) or insufficient,
                      application_view=all(f.get("application") and f.get("try_next") for f in state.findings) and (bool(state.findings) or insufficient))
    publications = sum(i.get("date_kind") == "published" for i in state.selected_items)
    activity = sum(i.get("date_kind") == "updated" for i in state.selected_items)
    return {"id": case["id"], "query": case["query"], "mode": mode,
            "verification_level": {"replay": "offline_replay", "retrieval": "live_retrieval_only", "live": "live_model_run"}[mode],
            "evidence_levels": {"publication_sources": publications, "activity_sources": activity,
                                "trend_evidence_ready": publications >= 2},
            "semantic_quality": "not_automatically_evaluated",
            "passed": all(checks.values()), "checks": checks, "latency_ms": round((time.monotonic() - started) * 1000),
            "state": asdict(state), "requires_human_review": mode != "replay"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("replay", "retrieval", "live"), default="replay")
    parser.add_argument("--case", default=None, help="Case ID; defaults to all eight")
    parser.add_argument("--output", type=Path, default=ROOT / "eval_results" / "research_eval.json")
    args = parser.parse_args()
    cases = json.loads((ROOT / "tests" / "eval_cases.json").read_text())
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            parser.error("unknown case ID")
    config = load_config()
    fixture = json.loads((ROOT / "tests" / "fixtures" / "research_sources.json").read_text())
    today = dt.date.fromisoformat(fixture["as_of"]) if args.mode == "replay" else dt.datetime.now(ZoneInfo(config.get("learning_agent", {}).get("timezone", "Asia/Shanghai"))).date()
    results = [evaluate_case(c, args.mode, config, today, fixture["items"]) for c in cases]
    report = {"mode": args.mode, "as_of": today.isoformat(), "passed": sum(r["passed"] for r in results), "total": len(results),
              "notice": "Structural checks do not establish semantic quality, citation entailment, clinical efficacy, or live model quality. Replay uses synthetic evidence and scripted decisions.", "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    for r in results:
        print(f"{r['id']}: {'PASS' if r['passed'] else 'FAIL'} [{r['verification_level']}] sources={len(r['state']['selected_items'])} publications={r['evidence_levels']['publication_sources']} activity={r['evidence_levels']['activity_sources']} status={r['state']['status']}")
    print(f"{report['passed']}/{report['total']} passed; output={args.output}")
    if not all(r["passed"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
