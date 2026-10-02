import datetime as dt
import json
from pathlib import Path

import pytest

import ask_radar
from learning_agent import AgentState, run_agent, verify_findings
from learning_cards import learning_details, render_learning_card, weekly_cards
from research_eval import ReplaySearch, replay_decider
from weekly_trends import normalize_learning_cards, render_weekly_markdown, validate_curated


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
