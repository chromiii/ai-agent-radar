import datetime as dt
from pathlib import Path

import yaml

from radar_reader import render_reader


WORKFLOWS = Path(__file__).resolve().parents[1] / '.github/workflows'


def test_pages_rebuilds_after_default_branch_radar_runs():
    workflow = yaml.load((WORKFLOWS / 'pages.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    trigger = workflow['on']['workflow_run']
    names = {yaml.load((WORKFLOWS / filename).read_text(encoding='utf-8'), Loader=yaml.BaseLoader)['name']
             for filename in ('daily.yml', 'company-radar.yml', 'weekly-trends.yml')}
    assert set(trigger['workflows']) == names
    assert trigger['types'] == ['completed'] and trigger['branches'] == ['main']
    build = workflow['jobs']['build']
    assert "github.event.workflow_run.conclusion == 'success'" in build['if']
    assert any('radar_reader.py --output _site/index.html' in step.get('run', '') for step in build['steps'])
    upload, = [step for step in build['steps'] if step.get('uses', '').startswith('actions/upload-pages-artifact@')]
    assert upload['with']['path'] == '_site'
    deploy = workflow['jobs']['deploy']
    assert deploy['needs'] == 'build' and deploy['environment']['name'] == 'github-pages'
    assert deploy['permissions'] == {'pages': 'write', 'id-token': 'write'}


def test_pages_reader_uses_public_reports_without_embedding_personal_state(tmp_path):
    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    (inbox / '2026-11-27.md').write_text('### Public Radar item\n- Link: https://example.org/public\n', encoding='utf-8')
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'learning_progress.json').write_text('{"note":"private-radar-learning-marker"}', encoding='utf-8')
    (tmp_path / '.env').write_text('TEST_UNPUBLISHED=private-radar-env-marker', encoding='utf-8')
    html = render_reader(tmp_path, dt.date(2026, 11, 27))
    assert 'Public Radar item' in html
    assert 'private-radar-learning-marker' not in html and 'private-radar-env-marker' not in html
