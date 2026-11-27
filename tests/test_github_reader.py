import datetime as dt
import json
from pathlib import Path

import yaml


def test_github_reader_renders_native_graph_and_expandable_sources(tmp_path):
    from radar_github import render_github_reader

    day = dt.date(2026, 11, 27)
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'trending_terms.json').write_text(json.dumps({
        'generated_at': '2026-11-21', 'curated': {'topic_graph': [
            {'label': '工具 "案例" [主题] <script>', 'children': [
                {'label': '界面评测', 'sources': [
                    {'title': 'A public benchmark', 'url': 'https://www.example.org/benchmark)#figure',
                     'published': '2026-11-20'},
                ]},
            ]},
        ]},
    }), encoding='utf-8')
    page = render_github_reader(tmp_path, day)
    assert '```mermaid\nflowchart LR' in page
    assert 't1 --> t1_s1' in page and '界面评测' in page
    assert '<details>' in page and '<summary>' in page
    assert '[A public benchmark](https://www.example.org/benchmark%29#figure)' in page
    assert '2026-11-21' in page and '发布 2026-11-20' in page
    assert '<script>' not in page and '"案例"' not in page.split('```mermaid', 1)[1].split('```', 1)[0]


def test_no_graph_still_links_to_default_repo_reports(tmp_path):
    from radar_github import render_github_reader

    page = render_github_reader(tmp_path, dt.date(2026, 11, 27))
    assert '暂无可用主题' in page and '[研究日报](inbox/)' in page
    assert '```mermaid' not in page


def test_weekly_workflow_commits_native_reader_without_rerunning_the_model():
    path = Path(__file__).resolve().parents[1] / '.github/workflows/weekly-trends.yml'
    workflow = yaml.load(path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    steps = workflow['jobs']['collect']['steps']
    generate, = [step for step in steps if step.get('id') == 'native_graph']
    assert generate['run'] == 'python radar_github.py' and generate['continue-on-error'] == 'true'
    commit, = [step for step in steps if step.get('name') == 'Commit weekly trend radar']
    assert 'steps.native_graph.outcome' in commit['run'] and 'git add -- RADAR.md' in commit['run']
    assert steps.index(generate) < steps.index(commit)
    assert sum('python weekly_trends.py' in step.get('run', '') for step in steps) == 1
