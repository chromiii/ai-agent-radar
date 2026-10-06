"""Compare the V2.2 single-Agent path with the V3 role-separated path."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from learning_agent import AgentState, ROOT, load_config, run_agent
from role_research import RoleResearchState, run_role_research


def _usage_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row, dict)
        and any(key in row for key in ("prompt_tokens", "completion_tokens", "total_tokens", "error_code"))
    ]


def summarize_v2_usage(state: AgentState) -> dict[str, Any]:
    rows = list(state.model_trace) + [
        row
        for row in state.observations
        if row.get("action") == "decision_error"
        and any(key in row for key in ("prompt_tokens", "completion_tokens", "total_tokens"))
    ]
    records = _usage_records(rows)
    return {
        "model_calls": len(records),
        "reported_tokens": {
            key: sum(int(row.get(key, 0) or 0) for row in records)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "repair_or_model_errors": sum(bool(row.get("error_code")) for row in records),
    }


def summarize_v3_usage(state: RoleResearchState) -> dict[str, Any]:
    records = _usage_records(list(state.research_trace) + list(state.verifier_trace))
    by_role: dict[str, dict[str, int]] = {}
    for row in records:
        role = str(row.get("role") or "unknown")
        bucket = by_role.setdefault(
            role,
            {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "errors": 0},
        )
        bucket["model_calls"] += 1
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            bucket[key] += int(row.get(key, 0) or 0)
        bucket["errors"] += int(bool(row.get("error_code")))
    return {
        "model_calls": len(records),
        "reported_tokens": {
            key: sum(int(row.get(key, 0) or 0) for row in records)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "repair_or_model_errors": sum(bool(row.get("error_code")) for row in records),
        "by_role": by_role,
    }


def run_live_comparison(query: str, case_id: str, config: dict[str, Any], today: dt.date) -> dict[str, Any]:
    started = time.monotonic()
    v2_state = AgentState(
        task_id=f"ab-{case_id}-v2",
        user_query=query,
        search_mode="external",
        as_of=today.isoformat(),
    )
    v2_started = time.monotonic()
    v2_state = run_agent(v2_state, "", config)
    v2_latency = round((time.monotonic() - v2_started) * 1000)

    v3_state = RoleResearchState(
        task_id=f"ab-{case_id}-v3",
        user_query=query,
        as_of=today.isoformat(),
    )
    v3_started = time.monotonic()
    v3_state = run_role_research(v3_state, config)
    v3_latency = round((time.monotonic() - v3_started) * 1000)

    v2_usage = summarize_v2_usage(v2_state)
    v3_usage = summarize_v3_usage(v3_state)
    v2_tokens = v2_usage["reported_tokens"]["total_tokens"]
    v3_tokens = v3_usage["reported_tokens"]["total_tokens"]

    return {
        "case_id": case_id,
        "query": query,
        "as_of": today.isoformat(),
        "notice": (
            "This is one live A/B run, not a semantic-quality verdict. Each path performs its own bounded retrieval, "
            "so source sets may differ even with the same question and date window."
        ),
        "total_latency_ms": round((time.monotonic() - started) * 1000),
        "v2_single_agent": {
            "status": v2_state.status,
            "latency_ms": v2_latency,
            "sources": len(v2_state.selected_items),
            "findings": len(v2_state.findings),
            "search_calls": v2_state.search_calls,
            "usage": v2_usage,
            "answer": v2_state.final_answer,
            "state": asdict(v2_state),
        },
        "v3_role_separated": {
            "status": v3_state.status,
            "latency_ms": v3_latency,
            "sources": len(v3_state.selected_items),
            "analyst_findings": len(v3_state.analyst_findings),
            "verified_findings": len(v3_state.verified_findings),
            "search_calls": v3_state.search_calls,
            "usage": v3_usage,
            "answer": v3_state.final_answer,
            "state": asdict(v3_state),
        },
        "ratios": {
            "token_v3_over_v2": round(v3_tokens / v2_tokens, 3) if v2_tokens else None,
            "latency_v3_over_v2": round(v3_latency / v2_latency, 3) if v2_latency else None,
        },
    }


def render_comparison(report: dict[str, Any]) -> str:
    v2, v3 = report["v2_single_agent"], report["v3_role_separated"]
    ratio_t = report["ratios"]["token_v3_over_v2"]
    ratio_l = report["ratios"]["latency_v3_over_v2"]
    lines = [
        "# Research A/B — V2.2 single Agent vs V3 role-separated",
        "",
        f"问题：{report['query']}",
        f"日期基准：{report['as_of']}",
        "",
        "| 指标 | V2.2 Single Agent | V3 Research → Analyst → Verifier |",
        "| --- | ---: | ---: |",
        f"| 状态 | {v2['status']} | {v3['status']} |",
        f"| 来源数 | {v2['sources']} | {v3['sources']} |",
        f"| Search API calls | {v2['search_calls']} | {v3['search_calls']} |",
        f"| 模型调用 | {v2['usage']['model_calls']} | {v3['usage']['model_calls']} |",
        f"| 总 tokens | {v2['usage']['reported_tokens']['total_tokens']} | {v3['usage']['reported_tokens']['total_tokens']} |",
        f"| 延迟 | {v2['latency_ms']/1000:.1f}s | {v3['latency_ms']/1000:.1f}s |",
        f"| 最终 findings | {v2['findings']} | {v3['verified_findings']} |",
        "",
        f"Token 比例 V3/V2：{ratio_t if ratio_t is not None else 'n/a'}；延迟比例 V3/V2：{ratio_l if ratio_l is not None else 'n/a'}。",
        "",
        "注意：这是一次真实运行的成本/结构对比，不自动证明哪条回答语义质量更高；需要人工检查 claim 与引用的蕴含关系。",
        "",
        "## V2.2 Single Agent",
        "",
        v2["answer"],
        "",
        "## V3 Role-separated",
        "",
        v3["answer"],
        "",
        "## V3 role usage",
        "",
        "```json",
        json.dumps(v3["usage"]["by_role"], ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="medical-agent-trends")
    parser.add_argument("--output", type=Path, default=ROOT / "eval_results" / "research_ab.json")
    args = parser.parse_args()

    cases = json.loads((ROOT / "tests" / "eval_cases.json").read_text(encoding="utf-8"))
    case = next((entry for entry in cases if entry["id"] == args.case), None)
    if case is None:
        parser.error("unknown case ID")

    config = load_config()
    today = dt.datetime.now(
        ZoneInfo(config.get("learning_agent", {}).get("timezone", "Asia/Shanghai"))
    ).date()
    report = run_live_comparison(case["query"], case["id"], config, today)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path = args.output.with_suffix(".md")
    markdown_path.write_text(render_comparison(report), encoding="utf-8")
    print(render_comparison(report))
    print(f"output={args.output}")

    valid_statuses = {"finished", "finished_insufficient_evidence"}
    if report["v2_single_agent"]["status"] not in valid_statuses:
        raise SystemExit("V2.2 path failed")
    if report["v3_role_separated"]["status"] not in valid_statuses:
        raise SystemExit("V3 path failed")


if __name__ == "__main__":
    main()
