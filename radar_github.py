"""Render the Radar graph as a Markdown page GitHub can display natively."""
from __future__ import annotations

import argparse
import datetime as dt
import html
from pathlib import Path

from learning_cards import markdown_text, source_link
from radar_feed import collect_events
from topic_graph import build_reader_graph

ROOT = Path(__file__).resolve().parent
GRAPH_IMAGE = Path('assets/radar-graph.png')


def render_github_reader(root: Path, day: dt.date, *, image_path: Path | None = None) -> str:
    graph = build_reader_graph(root, day, collect_events(root, day))
    if image_path is not None:
        from radar_graph_image import render_graph_image
        render_graph_image(graph, image_path)
    lines = [
        '# Radar 主题图谱', '',
        '[研究日报](inbox/) · [公司日报](company/) · [学习周报](weekly/)', '',
    ]
    if not graph['topics']:
        return '\n'.join([*lines, '暂无可用主题。可以继续浏览上方的报告归档。', ''])

    lines.extend([
        f"图谱数据日期 **{graph['generated_at']}**。每周整理完成后更新。展开主题即可查看小词条和原文。", '',
        f'![Radar 主题和小词条关系图]({GRAPH_IMAGE.as_posix()})', '', '## 主题与原文', '',
    ])

    for topic in graph['topics']:
        label = html.escape(topic['label'])
        lines.extend(['<details>', f'<summary>{label}（{len(topic["children"])} 个小词条）</summary>', ''])
        for child in topic['children']:
            lines.extend([f"### {markdown_text(child['label'])}", ''])
            for item in child['content']:
                title = source_link(item['title'], item['urls'][0], preserve_original=True)
                published = f"发布 {item['published']}" if item['published'] else '发布日期未标注'
                other = [source_link(f'其他来源 {index}', url, preserve_original=True)
                         for index, url in enumerate(item['urls'][1:], 2)]
                line = f"- {title} · {published} · 收录 {item['first_seen']}"
                if other:
                    line += ' · ' + ' · '.join(other)
                lines.append(line)
            lines.append('')
        lines.extend(['</details>', ''])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', type=dt.date.fromisoformat)
    parser.add_argument('--output', type=Path, default=ROOT / 'RADAR.md')
    args = parser.parse_args()
    day = args.as_of
    if day is None:
        from radar import today_local
        day = today_local()
    text = render_github_reader(ROOT, day, image_path=args.output.parent / GRAPH_IMAGE)
    args.output.write_text(text, encoding='utf-8')
    print(f'GitHub reader: {args.output}')


if __name__ == '__main__':
    main()
