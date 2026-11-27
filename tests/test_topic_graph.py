import datetime as dt
import json

from radar_feed import collect_events
from radar_reader import render_reader
from weekly_trends import build_classifier_prompt, save_trending_state, validate_curated


DAY = dt.date(2026, 11, 27)
SOURCE = 'https://huggingface.co/papers/2611.12345'
ITEM = {'title': 'Coding Agents and Their Editing Traces', 'url': SOURCE,
        'published': '2026-11-25', 'summary': 'A study of unnecessary edits in patches.'}


def trend_file(root, payload):
    state = root / 'state'
    state.mkdir()
    (state / 'trending_terms.json').write_text(json.dumps(payload), encoding='utf-8')


def test_weekly_model_can_discover_subtopics_without_new_sources(tmp_path, monkeypatch):
    import weekly_trends

    terms = [{'term': 'coding agent'}]
    text = '\n'.join(row['content'] for row in build_classifier_prompt(DAY, DAY, terms, [ITEM]))
    assert 'topic_graph' in text and '"evidence_id": 1' in text
    model = {'tier1': ['coding agent'], 'topic_graph': [
        {'term': 'coding agent', 'label': '编码代理', 'children': [
            {'label': '编辑轨迹分析', 'evidence_ids': [True, 1, 1, 4]},
            {'label': '无证据发现', 'evidence_ids': [99]},
        ]},
        {'term': 'unapproved topic', 'label': '不在主题内', 'children': [
            {'label': '无关内容', 'evidence_ids': [1]},
        ]},
    ]}
    curated = validate_curated(model, terms, [ITEM])
    assert curated['topic_graph'] == [{'term': 'coding agent', 'label': '编码代理', 'children': [
        {'label': '编辑轨迹分析', 'sources': [ITEM]},
    ]}]
    monkeypatch.setattr(weekly_trends, 'ROOT', tmp_path)
    save_trending_state(DAY, DAY, terms, curated, {})
    page = render_reader(tmp_path, DAY)
    assert '编码代理' in page and '编辑轨迹分析' in page and SOURCE in page
    assert '无证据发现' not in page and '不在主题内' not in page


def test_legacy_graph_connects_existing_ai_cards_to_actual_source_and_daily_event(tmp_path):
    from topic_graph import build_reader_graph

    trend_file(tmp_path, {'generated_at': '2026-11-21', 'tier1': ['coding agent'],
                         'curated': {'learning_cards': [
                             {'title': '编辑轨迹分析', 'why_now': '对照代理的编辑轨迹。', 'source_urls': [SOURCE]},
                             {'title': '未收录主题', 'source_urls': ['https://example.org/unseen']},
                         ]}})
    (tmp_path / 'weekly').mkdir()
    (tmp_path / 'weekly/2026-11-21.md').write_text(
        f'## 代表性内容\n\n- [{ITEM["title"]}]({SOURCE})\n  - 来源：hf_daily_papers；命中词：coding agent\n',
        encoding='utf-8',
    )
    (tmp_path / 'inbox').mkdir()
    (tmp_path / 'inbox/2026-11-26.md').write_text(
        '### Latest daily evidence\n- Link: https://arxiv.org/abs/2611.12345v2\n- Date: 2026-11-19\n',
        encoding='utf-8',
    )
    events = collect_events(tmp_path, DAY)
    graph = build_reader_graph(tmp_path, DAY, events)
    assert graph['generated_at'] == '2026-11-21' and graph['method'] == 'legacy'
    [topic] = graph['topics']
    [child] = topic['children']
    assert child['label'] == '编辑轨迹分析'
    [content] = child['content']
    assert content['id'] == events[0].id
    assert content['urls'] == [events[0].urls[0], SOURCE]
    assert content['first_seen'] == '2026-11-21'


def test_graph_from_future_week_is_not_shown_in_historical_snapshot(tmp_path):
    from topic_graph import build_reader_graph

    trend_file(tmp_path, {'generated_at': '2026-11-28', 'tier1': ['coding agent']})
    assert build_reader_graph(tmp_path, DAY, [])['topics'] == []


def test_historical_snapshot_uses_earlier_retained_week_when_state_is_newer(tmp_path):
    from topic_graph import build_reader_graph

    trend_file(tmp_path, {'generated_at': '2026-11-28', 'tier1': ['future term']})
    weekly = tmp_path / 'weekly'
    weekly.mkdir()
    (weekly / '2026-11-21.md').write_text(
        '## Tier 1 · 热词\n- **coding agent**：有新评测\n\n'
        '## Tier 2 · 观察词\n- **benchmark**：继续关注\n\n'
        f'## 代表性内容\n- [{ITEM["title"]}]({SOURCE})\n  - 来源：hf_daily_papers；命中词：coding agent, benchmark\n',
        encoding='utf-8',
    )
    graph = build_reader_graph(tmp_path, DAY, [])
    assert graph['generated_at'] == '2026-11-21'
    assert graph['topics'][0]['children'][0]['label'] == 'benchmark'
