import datetime as dt
import json
from pathlib import Path

import yaml


def test_github_reader_embeds_an_image_and_expandable_sources(tmp_path):
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
    assert '![Radar 主题和小词条关系图](assets/radar-graph.png)' in page
    assert '```mermaid' not in page and '界面评测' in page
    assert '<details>' in page and '<summary>' in page
    assert '[A public benchmark](https://www.example.org/benchmark%29#figure)' in page
    assert '2026-11-21' in page and '发布 2026-11-20' in page
    assert '<script>' not in page


def test_no_graph_still_links_to_default_repo_reports(tmp_path):
    from radar_github import render_github_reader

    page = render_github_reader(tmp_path, dt.date(2026, 11, 27))
    assert '暂无可用主题' in page and '[研究日报](inbox/)' in page
    assert '```mermaid' not in page


def test_graph_image_is_a_readable_png(tmp_path):
    from PIL import Image

    from radar_graph_image import render_graph_image

    path = tmp_path / 'assets' / 'radar-graph.png'
    render_graph_image({'generated_at': '2026-11-27', 'topics': [
        {'label': '编码代理', 'children': [{'label': '长词条' * 16}]},
    ]}, path)
    with Image.open(path) as image:
        assert image.format == 'PNG' and image.width >= 800 and image.height >= 200
        assert len(image.getcolors(1 << 20)) > 3


def test_weekly_workflow_commits_native_reader_without_rerunning_the_model():
    path = Path(__file__).resolve().parents[1] / '.github/workflows/weekly-trends.yml'
    workflow = yaml.load(path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    steps = workflow['jobs']['collect']['steps']
    generate, = [step for step in steps if step.get('id') == 'native_graph']
    assert 'python radar_github.py' in generate['run'] and generate['continue-on-error'] == 'true'
    commit, = [step for step in steps if step.get('name') == 'Commit weekly trend radar']
    assert 'steps.native_graph.outcome' in commit['run'] and 'git add -- RADAR.md assets/radar-graph.png' in commit['run']
    assert steps.index(generate) < steps.index(commit)
    assert sum('python weekly_trends.py' in step.get('run', '') for step in steps) == 1
