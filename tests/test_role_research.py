import datetime as dt

import pytest

from learning_agent import ModelResponseError
from role_research import (
    RoleResearchState,
    run_role_research,
    validate_research_decision,
    validate_verifier_output,
)
from research_search import SearchBatch


TODAY = dt.date(2026, 10, 7)


def evidence():
    return [
        {
            "title": "Clinical Agent Workflow Evaluation",
            "url": "https://clinical.example/workflow",
            "summary": "Medical agents use bounded tools in clinical workflow evaluation with explicit failure reporting.",
            "date": "2026-10-05",
            "date_kind": "published",
            "provider": "tavily",
            "evidence_kind": "search_excerpt",
            "retrieved_query": "healthcare agent",
            "relevance_score": 4.0,
        },
        {
            "title": "Drug Discovery Agent Benchmark",
            "url": "https://pharma.example/benchmark",
            "summary": "A drug discovery agent benchmark evaluates tool use and planning on pharmaceutical research tasks.",
            "date": "2026-10-04",
            "date_kind": "published",
            "provider": "hf",
            "evidence_kind": "abstract",
            "retrieved_query": "drug discovery agent",
            "relevance_score": 3.8,
        },
    ]


class FixedSearch:
    max_calls = 8

    def __init__(self, items=None):
        self.items = list(items if items is not None else evidence())
        self.used_calls = 0
        self.calls = []

    def search(self, plan, queries, selected_urls):
        self.used_calls += 1
        self.calls.append(list(queries))
        fresh = [dict(item) for item in self.items if item["url"] not in selected_urls]
        return SearchBatch(items=fresh, trace=[{"stage": "fixture", "selected": len(fresh)}], warnings=[])


def finding(topic, claim, evidence_id):
    return {
        "topic": topic,
        "claim": claim,
        "claim_type": "signal",
        "evidence_ids": [evidence_id],
        "application": "用于理解 Agent 工具调用的工程边界。",
        "try_next": "做一个带失败分支的两工具小实验。",
        "level": "build",
        "one_liner": "把 Agent 的工具调用限制在可观察、可失败恢复的边界内。",
        "learn": ["工具边界", "失败恢复"],
        "practice_minutes": 20,
        "done_when": "保存一次成功调用和一次失败恢复记录。",
    }


def ready(*_):
    return {"action": "ready", "reason": "已有两条近期独立来源，可交给 Analyst。"}


def analyst(*_):
    return {
        "findings": [
            finding("临床工作流", "近期来源展示了医疗 Agent 在临床工作流中的工具调用评估。", "S1"),
            finding("药物研发", "近期来源展示了 Agent 在药物研发 benchmark 中的规划与工具使用评估。", "S2"),
        ],
        "limitations": "当前证据主要是近期研究与实现信号，不等同于生产部署。",
    }


def accept_all(*_):
    return {
        "results": [
            {"index": 1, "verdict": "accept", "reason": "S1 的摘要直接支持该范围内的表述。"},
            {"index": 2, "verdict": "accept", "reason": "S2 的摘要直接支持该 benchmark 表述。"},
        ]
    }


def state():
    return RoleResearchState(
        task_id="roles-test",
        user_query="最近医药 Agent 有哪些应用层信号？",
        as_of=TODAY.isoformat(),
    )


def test_role_separated_path_finishes_with_two_source_gate():
    result = run_role_research(
        state(),
        {},
        research_decide=ready,
        analyst_decide=analyst,
        verifier_decide=accept_all,
        searcher=FixedSearch(),
    )
    assert result.status == "finished"
    assert len(result.analyst_findings) == 2
    assert len(result.verified_findings) == 2
    assert "Research → Analyst → Verifier" in result.final_answer
    assert result.selected_items[0]["id"] == "S1"
    assert result.selected_items[1]["id"] == "S2"


def test_semantic_rejection_rechecks_final_multi_source_gate():
    def reject_second(*_):
        return {
            "results": [
                {"index": 1, "verdict": "accept", "reason": "支持。"},
                {"index": 2, "verdict": "reject", "reason": "claim 超出了摘要支持范围。"},
            ]
        }

    result = run_role_research(
        state(),
        {},
        research_decide=ready,
        analyst_decide=analyst,
        verifier_decide=reject_second,
        searcher=FixedSearch(),
    )
    assert result.status == "finished_insufficient_evidence"
    assert result.verified_findings == []
    assert "多来源" in result.final_answer


def test_research_can_stop_before_analysis():
    called = {"analyst": False}

    def insufficient(*_):
        return {"action": "insufficient_evidence", "reason": "来源太少", "gaps": ["缺直接证据"]}

    def should_not_run(*_):
        called["analyst"] = True
        raise AssertionError("Analyst should not run")

    result = run_role_research(
        state(),
        {},
        research_decide=insufficient,
        analyst_decide=should_not_run,
        verifier_decide=accept_all,
        searcher=FixedSearch([]),
    )
    assert result.status == "finished_insufficient_evidence"
    assert not called["analyst"]


def test_research_role_cannot_return_analysis_action():
    with pytest.raises(ValueError, match="unsupported research action"):
        validate_research_decision({"action": "analyze", "reason": "越权"})


def test_search_more_requires_grounded_queries():
    with pytest.raises(ValueError, match="requires query_terms"):
        validate_research_decision({"action": "search_more", "reason": "缺证据", "query_terms": []})


def test_verifier_must_cover_every_finding_once():
    with pytest.raises(ValueError, match="one result per finding"):
        validate_verifier_output(
            {"results": [{"index": 1, "verdict": "accept", "reason": "ok"}]},
            2,
        )


def test_verifier_cannot_change_analyst_claim_in_published_state():
    def verifier_with_extra_rewrite(*_):
        return {
            "results": [
                {"index": 1, "verdict": "accept", "reason": "支持。", "replacement_claim": "不要采用这句"},
                {"index": 2, "verdict": "accept", "reason": "支持。", "replacement_claim": "也不要采用"},
            ]
        }

    result = run_role_research(
        state(),
        {},
        research_decide=ready,
        analyst_decide=analyst,
        verifier_decide=verifier_with_extra_rewrite,
        searcher=FixedSearch(),
    )
    assert result.status == "finished"
    assert result.verified_findings[0]["claim"] == analyst()["findings"][0]["claim"]


def test_research_round_limit_is_bounded():
    with pytest.raises(ValueError):
        RoleResearchState(task_id="t", user_query="agent", max_research_rounds=6)


def test_analyst_gets_one_bounded_format_repair():
    calls = {"count": 0}

    def flaky_analyst(*_):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ModelResponseError(
                "invalid_json",
                {"finish_reason": "stop", "prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
            )
        return analyst()

    result = run_role_research(
        state(),
        {},
        research_decide=ready,
        analyst_decide=flaky_analyst,
        verifier_decide=accept_all,
        searcher=FixedSearch(),
    )
    assert result.status == "finished"
    assert calls["count"] == 2
    assert any(
        row.get("role") == "analyst" and row.get("error_code") == "invalid_json"
        for row in result.research_trace
    )
