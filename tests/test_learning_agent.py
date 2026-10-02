from learning_agent import AgentState, run_agent, select_more_evidence, validate_decision


REPORT = """
# Weekly
- [LangGraph checkpoint guide](https://example.com/langgraph)
- [Agent memory benchmark](https://example.com/memory)
- [Computer use agent](https://example.com/computer-use)
- [Multi-agent orchestration survey](https://example.com/multi-agent-survey)
- [MCP tool integration tutorial](https://example.com/mcp-tools)
"""


def scripted_decider(decisions):
    iterator = iter(decisions)

    def decide(messages, config):
        return next(iterator)

    return decide


def test_validate_rejects_unbounded_action():
    try:
        validate_decision({"action": "browse_forever", "reason": "x"})
    except ValueError as exc:
        assert "Unsupported action" in str(exc)
    else:
        raise AssertionError("invalid action should fail")


def test_search_more_requires_query_terms():
    try:
        validate_decision({"action": "search_more", "reason": "need evidence", "query_terms": []})
    except ValueError as exc:
        assert "requires query_terms" in str(exc)
    else:
        raise AssertionError("search_more without query terms should fail")


def test_finish_requires_answer():
    try:
        validate_decision({"action": "finish", "reason": "done", "final_answer": ""})
    except ValueError as exc:
        assert "requires final_answer" in str(exc)
    else:
        raise AssertionError("finish without answer should fail")


def test_search_more_only_selects_grounded_urls():
    items = select_more_evidence(REPORT, ["memory"], set())
    assert items == [{"title": "Agent memory benchmark", "url": "https://example.com/memory"}]


def test_search_more_does_not_repeat_selected_url():
    items = select_more_evidence(
        REPORT,
        ["memory"],
        {"https://example.com/memory"},
    )
    assert items == []


def test_search_more_prefers_application_layer_match():
    items = select_more_evidence(REPORT, ["mcp", "tool"], set())
    assert items[0]["url"] == "https://example.com/mcp-tools"


def test_agent_finishes_before_budget():
    state = AgentState(task_id="t1", user_query="agent memory", max_steps=4)
    decide = scripted_decider(
        [
            {"action": "search_more", "reason": "缺少 memory 证据", "query_terms": ["memory"]},
            {"action": "finish", "reason": "证据足够", "final_answer": "区分 run state 和 long-term memory。"},
        ]
    )
    result = run_agent(state, REPORT, {}, decide=decide)
    assert result.status == "finished"
    assert result.current_step == 2
    assert len(result.selected_items) == 1
    assert result.final_answer == "区分 run state 和 long-term memory。"


def test_agent_can_analyze_then_finish_without_search():
    state = AgentState(task_id="t2", user_query="LangGraph checkpoint 有什么用", max_steps=3)
    decide = scripted_decider(
        [
            {"action": "analyze", "reason": "现有证据足够先形成判断"},
            {"action": "finish", "reason": "无需继续搜索", "final_answer": "checkpoint 主要用于保存和恢复运行状态。"},
        ]
    )
    result = run_agent(state, REPORT, {}, decide=decide)
    assert result.status == "finished"
    assert result.current_step == 2
    assert result.selected_items == []


def test_agent_stops_after_two_no_progress_searches():
    state = AgentState(task_id="t3", user_query="unknown topic", max_steps=5)
    decide = scripted_decider(
        [
            {"action": "search_more", "reason": "找证据", "query_terms": ["nonexistent"]},
            {"action": "search_more", "reason": "再找一次", "query_terms": ["still-missing"]},
        ]
    )
    result = run_agent(state, REPORT, {}, decide=decide)
    assert result.status == "stopped_no_progress"
    assert result.current_step == 2
    assert "连续两次" in result.final_answer


def test_no_progress_counter_resets_when_new_evidence_arrives():
    state = AgentState(task_id="t4", user_query="先找不到，再找到 memory", max_steps=4)
    decide = scripted_decider(
        [
            {"action": "search_more", "reason": "第一次没找到", "query_terms": ["missing"]},
            {"action": "search_more", "reason": "换关键词", "query_terms": ["memory"]},
            {"action": "finish", "reason": "现在够了", "final_answer": "memory 需要区分运行态和长期态。"},
        ]
    )
    result = run_agent(state, REPORT, {}, decide=decide)
    assert result.status == "finished"
    assert result.no_progress_count == 0
    assert len(result.selected_items) == 1


def test_agent_stops_at_max_steps():
    state = AgentState(task_id="t5", user_query="keep analyzing", max_steps=2)
    decide = scripted_decider(
        [
            {"action": "analyze", "reason": "分析一次"},
            {"action": "analyze", "reason": "分析两次"},
        ]
    )
    result = run_agent(state, REPORT, {}, decide=decide)
    assert result.status == "stopped_max_steps"
    assert result.current_step == 2
    assert "达到 max_steps" in result.final_answer


def test_agent_never_selects_non_report_source():
    state = AgentState(task_id="t6", user_query="memory", max_steps=2)
    decide = scripted_decider(
        [
            {"action": "search_more", "reason": "补证据", "query_terms": ["memory"]},
            {"action": "finish", "reason": "完成", "final_answer": "done"},
        ]
    )
    result = run_agent(state, REPORT, {}, decide=decide)
    allowed = {
        "https://example.com/langgraph",
        "https://example.com/memory",
        "https://example.com/computer-use",
        "https://example.com/multi-agent-survey",
        "https://example.com/mcp-tools",
    }
    assert {item["url"] for item in result.selected_items}.issubset(allowed)
