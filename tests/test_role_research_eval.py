import datetime as dt
import json
from pathlib import Path

import pytest

from research_eval import ReplaySearch
from role_research import RoleResearchState, run_role_research


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests" / "eval_cases.json").read_text())
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "research_sources.json").read_text())
TODAY = dt.date.fromisoformat(FIXTURE["as_of"])


def research_decider(state):
    def decide(*_):
        if len(state.selected_items) < 2:
            return {
                "action": "insufficient_evidence",
                "reason": "replay fixture 中不足两条可用来源。",
                "gaps": ["需要第二条独立来源"],
            }
        return {"action": "ready", "reason": "已有两条来源，可进入 Analyst。"}

    return decide


def analyst_decider(state):
    def decide(*_):
        findings = []
        for item in state.selected_items[:2]:
            findings.append(
                {
                    "topic": item["title"],
                    "claim": item["summary"],
                    "claim_type": "signal",
                    "evidence_ids": [item["id"]],
                    "application": "测试角色分离后是否仍保留来源与工程边界。",
                    "try_next": "为两条合成来源记录一次工具调用和一次失败状态。",
                    "level": "build",
                    "one_liner": "合成 replay 只验证编排结构，不代表真实研究结论。",
                    "learn": ["来源记录", "角色边界"],
                    "practice_minutes": 15,
                    "done_when": "记录包含来源 ID、角色和一次失败状态。",
                }
            )
        return {
            "findings": findings,
            "limitations": "Synthetic fixture and scripted roles; not real findings or model-quality evidence.",
        }

    return decide


def verifier_decider(state):
    def decide(*_):
        return {
            "results": [
                {"index": i, "verdict": "accept", "reason": "replay 中 claim 直接复制自对应合成摘要。"}
                for i in range(1, len(state.analyst_findings) + 1)
            ]
        }

    return decide


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_v3_replay_uses_same_usability_cases(case):
    state = RoleResearchState(
        task_id="roles-" + case["id"],
        user_query=case["query"],
        as_of=TODAY.isoformat(),
    )
    searcher = ReplaySearch([] if case.get("fixture") == "empty" else FIXTURE["items"])

    result = run_role_research(
        state,
        {},
        research_decide=research_decider(state),
        analyst_decide=analyst_decider(state),
        verifier_decide=verifier_decider(state),
        searcher=searcher,
    )

    insufficient = result.status == "finished_insufficient_evidence" and case.get("allow_insufficient", False)
    assert not case.get("must_expand") or len(result.query_plan.get("expanded_queries", [])) > 1
    assert set(case["topics"]).issubset(result.query_plan.get("topics", []))
    assert result.research_trace
    assert len(result.selected_items) >= case["min_sources"] or insufficient
    assert result.status in ("finished", "finished_insufficient_evidence")

    if insufficient:
        assert result.verified_findings == []
    else:
        assert len(result.verified_findings) == 2
        assert all(finding["application"] and finding["try_next"] for finding in result.verified_findings)
        assert all(
            finding["one_liner"]
            and finding["learn"]
            and finding["done_when"]
            and 15 <= finding["practice_minutes"] <= 30
            for finding in result.verified_findings
        )
