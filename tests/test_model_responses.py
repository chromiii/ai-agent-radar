import json
from dataclasses import asdict

import pytest
import requests

from learning_agent import AgentState, build_agent_prompt, run_agent
from research_eval import ReplaySearch


class ModelResponse:
    def __init__(self, content, finish_reason="stop"):
        self.content, self.finish_reason = content, finish_reason

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"finish_reason": self.finish_reason, "message": {"content": self.content}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 3600,
                          "request_headers": "secret-must-stay-private"}}


def mock_model(monkeypatch, response):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret-must-stay-private")
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)


@pytest.mark.parametrize("content,finish_reason,error_code", [
    ('{"action":"finish"}', "length", "truncated_response"),
    ('{"action":"finish",', "stop", "invalid_json"),
    (None, "stop", "empty_or_invalid_content"),
    ('{"action":"finish"}', "content_filter", "incomplete_response"),
])
def test_model_failure_diagnostics_do_not_salvage_partial_answers(monkeypatch, content, finish_reason, error_code):
    mock_model(monkeypatch, ModelResponse(content, finish_reason))
    state = AgentState(task_id="model-failure", user_query="medical agent", search_mode="external")
    result = run_agent(state, "", {}, searcher=ReplaySearch([]))
    error = result.observations[0]
    assert result.status == "failed_decision" and not result.findings
    assert error["error_code"] == error_code
    assert error["completion_tokens"] == 3600
    assert "secret-must-stay-private" not in json.dumps(asdict(result))


def test_successful_model_call_records_only_usage_metadata(monkeypatch):
    mock_model(monkeypatch, ModelResponse('{"action":"finish","final_answer":"回答"}'))
    result = run_agent(AgentState(task_id="model-ok", user_query="agent memory"), "", {})
    assert result.status == "finished"
    assert result.model_trace == [{"step": 1, "finish_reason": "stop", "prompt_tokens": 100, "completion_tokens": 3600}]
    assert "secret-must-stay-private" not in json.dumps(asdict(result))


def test_http_error_preserves_status_without_response_or_credentials(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret-must-stay-private")

    def fail(*args, **kwargs):
        response = requests.Response()
        response.status_code = 401
        raise requests.HTTPError("test-secret-must-stay-private", response=response)

    monkeypatch.setattr(requests, "post", fail)
    result = run_agent(AgentState(task_id="auth-failure", user_query="agent memory"), "", {})
    assert result.status == "failed_decision"
    assert result.observations[0]["http_status"] == 401
    assert "secret-must-stay-private" not in json.dumps(asdict(result))


def test_prompt_keeps_internal_aliases_out_of_task_and_sources_once():
    state = AgentState(task_id="compact", user_query="医药 agent", search_mode="external",
                       search_call_limit=12, search_calls=6)
    state.query_plan = {"original_query": state.user_query, "topics": ["healthcare"],
                        "relevance_groups": [["internal-filter-not-a-subtask"]]}
    item = {"id": "S1", "title": "clinical paper", "summary": "unique-evidence-excerpt"}
    state.selected_items = [item]
    state.observations = [{"step": 1, "action": "search_more", "new_evidence": [item]}]
    prompt = build_agent_prompt(state, "")[1]["content"]
    assert prompt.count("unique-evidence-excerpt") == 1
    assert "internal-filter-not-a-subtask" not in prompt
    assert "Remaining search API calls: 6" in prompt
    assert state.observations[0]["new_evidence"] == [item]
