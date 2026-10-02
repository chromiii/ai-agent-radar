import datetime as dt
import json
from pathlib import Path

import pytest

import ask_radar
import requests
from learning_agent import AgentState, run_agent, verify_findings
from learning_cards import learning_details, render_learning_card, weekly_cards
from research_eval import ReplaySearch, replay_decider
from weekly_trends import normalize_learning_cards, render_weekly_markdown, validate_curated
from weekly_trends import build_classifier_prompt, call_deepseek_json


ROOT = Path(__file__).resolve().parents[1]
ITEMS = json.loads((ROOT / 'tests/fixtures/research_sources.json').read_text())['items']
DETAILS = {'level': 'build', 'one_liner': '工具调用日志记录 Agent 的动作与结果。',
           'learn': ['调用边界', '失败观察'], 'practice_minutes': 20,
           'done_when': '输出两个成功日志和一个失败日志。'}


def card(**changes):
    return {'title': '工具调用日志', 'why_now': '合成测试中的来源支持此学习卡。',
            'application': '用于检查工具调用失败。', 'hands_on': '为两个假工具生成调用日志。',
            'source_urls': ['https://clinical.example/workflow'], **DETAILS, **changes}


@pytest.mark.parametrize('changes', [
    {'level': []}, {'learn': ['只有一个点']}, {'done_when': ''},
    {'practice_minutes': True}, {'practice_minutes': 90},
    {'one_liner': '[假引用](https://made-up.example)'},
])
def test_incomplete_or_unbounded_learning_task_is_rejected(changes):
    with pytest.raises(ValueError):
        learning_details({**DETAILS, **changes})


def test_weekly_drops_card_with_invented_source_but_preserves_trend_fallback():
    representative = [{'url': 'https://clinical.example/workflow'}]
    invalid = card(source_urls=['https://made-up.example/tool'])
    curated = validate_curated({'tier1': ['agent'], 'learning_cards': [invalid]}, [{'term': 'agent'}], representative)
    assert curated['tier1'] == ['agent'] and curated['learning_cards'] == []
    assert normalize_learning_cards([card()], representative) == weekly_cards([card()], representative)


def test_weekly_and_research_cards_have_same_teaching_fields():
    representative = [{'url': 'https://clinical.example/workflow'}]
    cards = normalize_learning_cards([card()], representative)
    markdown = render_weekly_markdown(dt.date(2026, 10, 2), dt.date(2026, 9, 26), [], [], {'learning_cards': cards})
    for label in ('学习深度', '30 秒概念', '用在哪里', '应用层学到这里', '完成标准', '建议 20 分钟'):
        assert label in markdown
    assert '[来源 1](https://clinical.example/workflow)' in markdown


def test_markdown_escapes_user_content_and_unsafe_source_delimiters():
    rendered = '\n'.join(render_learning_card(card(title='<script>alert(1)</script> [bad]',
                                                  source_urls=['https://example.org/paper)evil']), 1))
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered
    assert '\\[bad\\]' in rendered and 'paper%29evil' in rendered


def test_verified_citations_do_not_allow_missing_teaching_fields():
    state = AgentState(task_id='card-check', user_query='医药 agent', search_mode='external', as_of='2026-10-02')
    run_agent(state, '', {}, decide=replay_decider(state), searcher=ReplaySearch(ITEMS))
    findings = [dict(f) for f in state.findings]
    del findings[0]['done_when']
    with pytest.raises(ValueError, match='completion criterion'):
        verify_findings(findings, state.selected_items)


def test_free_question_produces_readable_answer_and_trace_without_shell_execution(tmp_path, monkeypatch):
    original_run = ask_radar.run_agent

    def dated_run(state, report, config, **kwargs):
        state.as_of = '2026-10-02'
        return original_run(state, report, config, **kwargs)

    monkeypatch.setattr(ask_radar, 'run_agent', dated_run)
    decisions = iter([
        {'action': 'search_more', 'query_terms': ['healthcare agent']},
        {'action': 'finish', 'verdict': 'answer', 'findings': [
            {'topic': '工具调用日志', 'claim': '合成来源记录工具与人工检查边界。', 'claim_type': 'trend',
             'evidence_ids': ['S1', 'S2'], 'application': '用于记录调用失败。',
             'try_next': '用两个假工具记录成功与失败。', **DETAILS}]}])
    sentinel = tmp_path / 'should-not-exist'
    question = f'healthcare agent $(touch {sentinel}) <script>alert(1)</script>'
    state, answer = ask_radar.run_request(question, {}, tmp_path / 'answer', decide=lambda *_: next(decisions), searcher=ReplaySearch(ITEMS))
    assert state.status == 'finished' and not sentinel.exists()
    assert '<script>' not in answer and '完成标准' in answer
    record = json.loads((tmp_path / 'answer/run.json').read_text())
    assert record['state']['user_query'] == question
    assert (tmp_path / 'answer/answer.md').read_text() == answer


def test_free_question_failure_keeps_record_and_has_no_learning_cards(tmp_path):
    state, answer = ask_radar.run_request('agent memory', {}, tmp_path, decide=lambda *_: {'action': 'unsupported'})
    assert state.status == 'failed_decision'
    assert json.loads((tmp_path / 'run.json').read_text())['state']['findings'] == []
    assert '失败' in answer and '### 1.' not in answer


def test_overlong_free_question_fails_before_model_call(tmp_path):
    with pytest.raises(ValueError, match='600'):
        ask_radar.run_request('a' * 601, {}, tmp_path, decide=lambda *_: pytest.fail('model must not be called'))
    assert not (tmp_path / 'run.json').exists()


def test_task_specific_rewrite_keeps_python_and_rejects_unrelated_first_query():
    class RecordingSearch(ReplaySearch):
        def search(self, plan, queries, selected_urls):
            self.queries = queries
            return super().search(plan, queries, selected_urls)

    searcher = RecordingSearch([])
    state = AgentState(task_id='python-mcp', user_query='MCP 给 Python 工具加接口', max_steps=1,
                       search_mode='external', as_of='2026-10-02')
    result = run_agent(state, '', {}, decide=lambda *_: {'action': 'search_more',
                       'query_terms': ['unrelated weather forecast', 'MCP Python SDK tools']}, searcher=searcher)
    assert searcher.queries == ['mcp python sdk tools', 'MCP agent tools']
    assert result.query_plan['original_query'] == state.user_query
    assert result.observations[0]['query_terms'] == searcher.queries


def test_weekly_truncated_response_is_rejected_without_logging_content(monkeypatch, capsys):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'weekly-test-secret')

    class Truncated:
        def raise_for_status(self):
            pass

        def json(self):
            return {'choices': [{'finish_reason': 'length', 'message': {'content': 'private-model-content'}}]}

    monkeypatch.setattr(requests, 'post', lambda *args, **kwargs: Truncated())
    config = {'ai': {'enabled': True, 'provider': 'deepseek'}}
    result = call_deepseek_json(dt.date(2026, 10, 2), dt.date(2026, 9, 26), [], [], config)
    output = capsys.readouterr().out
    assert result is None and 'length' in output
    assert 'private-model-content' not in output and 'weekly-test-secret' not in output


def test_two_narrow_queries_leave_room_for_a_broad_topic_search():
    class RecordingSearch(ReplaySearch):
        def search(self, plan, queries, selected_urls):
            self.queries = queries
            return super().search(plan, queries, selected_urls)

    searcher = RecordingSearch([])
    state = AgentState(task_id='medical-comparison', user_query='医疗 Agent 和普通 Agent 工程区别是什么？',
                       max_steps=1, search_mode='external', as_of='2026-10-02')
    run_agent(state, '', {}, decide=lambda *_: {'action': 'search_more', 'query_terms': [
        'healthcare llm agent clinical workflow engineering challenges',
        'medical agent safety evaluation benchmark guardrails']}, searcher=searcher)
    assert searcher.queries == ['healthcare llm agent clinical workflow engineering challenges', 'healthcare agent']


def test_weekly_request_failure_does_not_log_credentials_or_raw_exception(monkeypatch, capsys):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'weekly-test-secret')

    def fail(*args, **kwargs):
        raise requests.RequestException('Authorization: Bearer weekly-test-secret')

    monkeypatch.setattr(requests, 'post', fail)
    result = call_deepseek_json(dt.date(2026, 10, 2), dt.date(2026, 9, 26), [], [],
                                {'ai': {'enabled': True, 'provider': 'deepseek'}})
    output = capsys.readouterr().out
    assert result is None and 'RequestException' in output
    assert 'weekly-test-secret' not in output and 'Authorization' not in output


def test_weekly_candidate_examples_cannot_supply_uncitable_claims():
    candidates = [{'term': 'gui agent', 'score': 8, 'count': 2, 'sources': ['arxiv'],
                   'examples': ['Uncitable GUI Study'], 'seed': True}]
    evidence = [{'title': 'Citable Tool Study', 'url': 'https://arxiv.org/abs/2609.10000',
                 'summary': 'A study about task state in tool agents.'}]
    prompt = build_classifier_prompt(dt.date(2026, 10, 2), dt.date(2026, 9, 26), candidates, evidence)
    content = '\n'.join(message['content'] for message in prompt)
    assert 'Uncitable GUI Study' not in content
    assert 'Citable Tool Study' in content and evidence[0]['url'] in content
    assert '"term": "gui agent"' in content
