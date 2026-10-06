from learning_agent import AgentState
from research_ab import render_comparison, summarize_v2_usage, summarize_v3_usage
from role_research import RoleResearchState


def test_usage_summary_counts_actual_model_records():
    v2 = AgentState(task_id="ab-v2", user_query="agent", search_mode="external")
    v2.model_trace = [
        {"step": 1, "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        {"step": 2, "prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230},
    ]
    assert summarize_v2_usage(v2) == {
        "model_calls": 2,
        "reported_tokens": {"prompt_tokens": 300, "completion_tokens": 50, "total_tokens": 350},
        "repair_or_model_errors": 0,
    }

    v3 = RoleResearchState(task_id="ab-v3", user_query="agent")
    v3.research_trace = [
        {"role": "research", "prompt_tokens": 80, "completion_tokens": 10, "total_tokens": 90},
        {"role": "analyst", "attempt": 1, "error_code": "invalid_json",
         "prompt_tokens": 150, "completion_tokens": 50, "total_tokens": 200},
        {"role": "analyst", "prompt_tokens": 160, "completion_tokens": 40, "total_tokens": 200},
    ]
    v3.verifier_trace = [
        {"role": "verifier", "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    ]
    usage = summarize_v3_usage(v3)
    assert usage["model_calls"] == 4
    assert usage["reported_tokens"]["total_tokens"] == 610
    assert usage["repair_or_model_errors"] == 1
    assert usage["by_role"]["analyst"]["model_calls"] == 2
    assert usage["by_role"]["analyst"]["errors"] == 1


def test_comparison_renderer_labels_result_as_non_semantic_verdict():
    report = {
        "query": "最近医药 Agent 有什么趋势？",
        "as_of": "2026-10-07",
        "v2_single_agent": {
            "status": "finished", "sources": 12, "search_calls": 6, "findings": 3,
            "latency_ms": 10000,
            "usage": {"model_calls": 2, "reported_tokens": {"total_tokens": 7000}},
            "answer": "v2 answer",
        },
        "v3_role_separated": {
            "status": "finished", "sources": 12, "search_calls": 6, "verified_findings": 3,
            "latency_ms": 18000,
            "usage": {
                "model_calls": 3,
                "reported_tokens": {"total_tokens": 12000},
                "by_role": {"research": {"model_calls": 1}},
            },
            "answer": "v3 answer",
        },
        "ratios": {"token_v3_over_v2": 1.714, "latency_v3_over_v2": 1.8},
    }
    rendered = render_comparison(report)
    assert "不自动证明" in rendered
    assert "1.714" in rendered
    assert "Research → Analyst → Verifier" in rendered
