from learning_agent import AgentState, run_agent, select_more_evidence, validate_decision


REPORT = """
# Weekly
- [LangGraph checkpoint guide](https://example.com/langgraph)
- [Agent memory benchmark](https://example.com/memory)
- [Computer use agent](https://example.com/computer-use)
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


def test_search_more_only_selects_grounded_urls():
    items = select_more_evidence(REPORT, ["memory"], set())
    assert items == [{"title": "Agent memory benchmark", "url": "https://example.com/memory"}]


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


def test_agent_stops_after_two_no_progress_searches():
    state = AgentState(task_id="t2", user_query="unknown topic", max_steps=5)
    decide = scripted_decider(
        [
            {"action": "search_more", "reason": "找证据", "query_terms": ["nonexistent"]},
            {"action": "search_more", "reason": "再找一次", "query_terms": ["still-missing"]},
        ]
    )
    result = run_agent(state, REPORT, {}, decide=decide)
    assert result.status == "stopped_no_progress"
    assert result.current_step == 2


def test_agent_stops_at_max_steps():
    state = AgentState(task_id="t3", user_query="keep analyzing", max_steps=2)
    decide = scripted_decider(
        [
            {"action": "analyze", "reason": "分析一次"},
            {"action": "analyze", "reason": "分析两次"},
        ]
    )
    result = run_agent(state, REPORT, {}, decide=decide)
    assert result.status == "stopped_max_steps"
    assert result.current_step == 2
