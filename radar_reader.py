"""Generate a self-contained, offline-readable Radar page."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from radar_feed import collect_events
from topic_graph import build_reader_graph

ROOT = Path(__file__).resolve().parent


def render_reader(root: Path, day: dt.date) -> str:
    events = collect_events(root, day)
    data = {
        'asOf': day.isoformat(),
        'events': [dict(asdict(row), date=row.date) for row in events],
        'graph': build_reader_graph(root, day, events),
    }
    # Keep embedded JSON in its script data block even when a title contains HTML.
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    template = (ROOT / 'reader/graph.html').read_text(encoding='utf-8')
    script = (ROOT / 'reader/app.js').read_text(encoding='utf-8')
    return template.replace('/* RADAR_SCRIPT */', script).replace('/* RADAR_DATA */', payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--as-of', type=dt.date.fromisoformat)
    parser.add_argument('--output', type=Path, default=ROOT / 'reader.html')
    args = parser.parse_args()
    day = args.as_of
    if day is None:
        from radar import today_local
        day = today_local()
    page = render_reader(args.root, day)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding='utf-8')
    print(f'Radar reader: {args.output}')


if __name__ == '__main__':
    main()
