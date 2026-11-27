import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest


DAY = dt.date(2026, 11, 27)
ROOT = Path(__file__).resolve().parents[1]


def write_report(root, folder, day, body):
    directory = root / folder
    directory.mkdir(exist_ok=True)
    (directory / f'{day}.md').write_text(body, encoding='utf-8')


def write_watchlist(root, *rules):
    path = root / 'watchlist.json'
    path.write_text(json.dumps({'topics': rules}), encoding='utf-8')
    return path


def test_feed_merges_paper_links_and_keeps_separate_dates(tmp_path):
    from radar_feed import collect_events

    write_report(tmp_path, 'inbox', '2026-11-25', '''# Daily
## 必看索引
1. [A reusable coding agent benchmark](https://huggingface.co/papers/2611.12345)
   - 日期：2026-11-23
   - 判断：提供公开评测样例。

2. [A different project](https://example.com/project)
   - 日期：2026-11-24
''')
    write_report(tmp_path, 'inbox', '2026-11-27', '''# Daily
## 值得扫一眼
### A reusable coding agent benchmark
- 日期：2026-11-23T21:12:00Z
- 链接：https://arxiv.org/abs/2611.12345v2?utm_source=test
''')
    events = collect_events(tmp_path, DAY)
    assert len(events) == 2
    paper = next(event for event in events if 'benchmark' in event.title)
    assert paper.published == '2026-11-23'
    assert paper.first_seen == '2026-11-25'
    assert paper.last_seen == '2026-11-27'
    assert paper.urls == ['https://arxiv.org/abs/2611.12345v2?utm_source=test',
                          'https://huggingface.co/papers/2611.12345']
    assert paper.summary == '提供公开评测样例。'


def test_feed_uses_explicit_same_event_and_ignores_future_reports(tmp_path):
    from radar_feed import collect_events

    write_report(tmp_path, 'company', '2026-11-27', '''# Company
### Mistral: Le Chonk for coding agents, October 29, 2026
- 链接：https://mistral.ai/news/example

### Vendor: A reusable tool for coding agents
- 日期：2026-11-26
- 链接：https://vendor.example.org/release

### Vendor: A reusable tool for coding agents
- 日期：2026-11-26
- 链接：https://example.org/release

### Undated company announcement
- 链接：https://example.org/unknown
''')
    write_report(tmp_path, 'company', '2026-11-28', '### Future\n- Link: https://example.org/future\n')
    events = collect_events(tmp_path, DAY)
    assert len(events) == 3
    assert next(event for event in events if 'Chonk' in event.title).published == '2026-10-29'
    assert next(event for event in events if 'reusable' in event.title).urls == [
        'https://example.org/release', 'https://vendor.example.org/release'
    ]
    assert next(event for event in events if 'Undated' in event.title).published is None


def test_watchlist_matches_topic_exclusions_and_source_boundaries(tmp_path):
    from radar_feed import collect_events, load_watchlist, matches_topic

    path = write_watchlist(tmp_path, {
        'name': 'MCP', 'include': ['MCP'], 'exclude': ['教程'], 'sources': ['example.org'],
    })
    write_report(tmp_path, 'inbox', '2026-11-27', '''# Daily
### MCP capability release
- Link: https://docs.example.org/release
### MCP 入门教程
- Link: https://example.org/tutorial
### MCP alternate release
- Link: https://badexample.org/release
### A smcproxy library
- Link: https://example.org/library
''')
    topic, = load_watchlist(path)
    assert [row.title for row in collect_events(tmp_path, DAY) if matches_topic(row, topic)] == [
        'MCP capability release'
    ]
    path.write_text('{"topics":[{"name":"Bad","sources":["https://example.org/path"]}]}')
    with pytest.raises(ValueError, match='sources'):
        load_watchlist(path)


def test_event_id_survives_later_publication_date(tmp_path):
    from radar_feed import collect_events

    body = '''# Daily
### A reproducible coding agent benchmark
- Link: https://example.org/benchmark
'''
    write_report(tmp_path, 'inbox', '2026-11-26', body)
    before, = collect_events(tmp_path, DAY)
    write_report(tmp_path, 'inbox', '2026-11-27', body + '- Date: 2026-11-25\n')
    after, = collect_events(tmp_path, DAY)
    assert after.published == '2026-11-25'
    assert before.id == after.id


def test_feed_keeps_original_link_and_its_full_domain_for_rules(tmp_path):
    from radar_feed import collect_events, load_watchlist, matches_topic

    url = 'http://www.example.org/release/?edition=2#changes'
    write_report(tmp_path, 'company', DAY.isoformat(), f'### MCP update\n- Link: {url}\n')
    event, = collect_events(tmp_path, DAY)
    topic, = load_watchlist(write_watchlist(tmp_path, {'name': 'Vendor', 'sources': ['www.example.org']}))
    assert event.urls == [url]
    assert matches_topic(event, topic)


def test_weekly_groups_watched_updates_with_dates_and_sources(tmp_path):
    from email_render import render_html
    from weekly_briefing import build_briefing

    write_watchlist(tmp_path, {'name': 'Coding agents', 'include': ['coding agent']},
                    {'name': 'Benchmarks', 'include': ['benchmark']})
    write_report(tmp_path, 'inbox', '2026-11-27', '''# Daily
1. [New coding agent benchmark](https://arxiv.org/abs/2611.12345)
   - 日期：2026-11-25
2. [Independent benchmark](https://example.org/benchmark)
3. [Old coding agent release](https://example.org/old)
   - 日期：2026-10-29
4. [Unrelated release](https://example.org/other)
''')
    briefing = build_briefing(tmp_path, DAY)
    assert '## 本周关注的变化' in briefing
    assert '### Coding agents' in briefing and '### Benchmarks' in briefing
    assert briefing.count('New coding agent benchmark') == 1
    assert '发布 2026-11-25' in briefing and '首次收录 2026-11-27' in briefing
    assert '发布日期未标注' in briefing
    assert 'Old coding agent release' not in briefing and 'Unrelated release' not in briefing
    assert '<a href="https://arxiv.org/abs/2611.12345"' in render_html(briefing)


def test_reader_entrypoint_embeds_safe_data_and_local_controls(tmp_path):
    output = tmp_path / 'radar.html'
    write_watchlist(tmp_path, {'name': 'Agent', 'include': ['Agent']})
    write_report(tmp_path, 'inbox', '2026-11-27', '''# Daily
### Agent </script><img src=x onerror=alert(1)>
- Link: https://example.org/release
''')
    result = subprocess.run(
        [sys.executable, '-B', str(ROOT / 'radar_reader.py'), '--root', str(tmp_path),
         '--as-of', DAY.isoformat(), '--output', str(output)],
        check=False, capture_output=True, text=True, encoding='utf-8',
    )
    assert result.returncode == 0, result.stderr
    page = output.read_text(encoding='utf-8')
    assert 'id="topic-graph"' in page and 'id="period"' in page
    assert 'localStorage' in page and '包含词' not in page and '导出关注规则' not in page
    assert r'\u003c/script>' in page
    assert '</script><img' not in page
    assert '<script src=' not in page
