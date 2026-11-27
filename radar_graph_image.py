"""Render a static topic graph for GitHub's standard image viewer."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = (
    Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
    Path('C:/Windows/Fonts/msyh.ttc'),
    Path('/System/Library/Fonts/PingFang.ttc'),
)


def wrap_label(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines = []
    current = ''
    for character in text:
        if current and font.getlength(current + character) > width:
            cut = current.rfind(' ')
            if cut > len(current) // 2:
                lines.append(current[:cut])
                current = current[cut + 1:]
            else:
                lines.append(current.rstrip())
                current = ''
        current += character if current or character != ' ' else ''
    return [*lines, current]


def render_graph_image(graph: dict, path: Path) -> None:
    font_file = next((candidate for candidate in FONTS if candidate.is_file()), None)
    if not font_file:
        raise FileNotFoundError('Install Noto Sans CJK to render the Radar graph image.')
    label_font = ImageFont.truetype(str(font_file), 24)
    meta_font = ImageFont.truetype(str(font_file), 19)
    heading_font = ImageFont.truetype(str(font_file), 32)
    left, right = (30, 298), (390, 890)
    groups = []
    cursor = 142
    for topic in graph['topics']:
        children = [wrap_label(child['label'], label_font, right[1] - right[0] - 34)
                    for child in topic['children']]
        parent = wrap_label(topic['label'], label_font, left[1] - left[0] - 34)
        parent_height = 30 * len(parent) + 18
        children_height = sum(30 * len(child) + 14 for child in children) + 8 * (len(children) - 1)
        group_height = max(parent_height, children_height)
        parent_y = cursor + (group_height - parent_height) // 2
        child_y = cursor + (group_height - children_height) // 2
        child_boxes = []
        for child in children:
            height = 30 * len(child) + 14
            child_boxes.append((child, child_y, height))
            child_y += height + 8
        groups.append((parent, parent_y, parent_height, child_boxes))
        cursor += group_height + 24

    image = Image.new('RGB', (920, max(235, cursor + 6)), '#eff4ee')
    draw = ImageDraw.Draw(image)
    draw.text((30, 24), 'Radar 主题图谱', font=heading_font, fill='#17382d')
    date = graph['generated_at'] or '暂无数据'
    draw.text((30, 70), f'图谱数据日期  {date}', font=meta_font, fill='#426254')
    draw.text((left[0], 110), '主题', font=meta_font, fill='#426254')
    draw.text((right[0], 110), '小词条', font=meta_font, fill='#426254')
    if not groups:
        draw.text((30, 155), '暂无可用主题', font=label_font, fill='#17382d')

    def draw_box(edges: tuple[int, int], top: int, height: int, lines: list[str], fill: str) -> None:
        draw.rounded_rectangle((edges[0], top, edges[1], top + height), radius=10,
                               fill=fill, outline='#b7ccc0', width=2)
        for index, line in enumerate(lines):
            draw.text((edges[0] + 16, top + (height - 30 * len(lines)) // 2 + 15 + 30 * index),
                      line, font=label_font, fill='#17382d', anchor='lm')

    trunk_x = (left[1] + right[0]) // 2
    for parent, parent_y, parent_height, child_boxes in groups:
        center = parent_y + parent_height // 2
        child_centers = [top + height // 2 for _, top, height in child_boxes]
        draw.line((left[1], center, trunk_x, center), fill='#5a8b76', width=2)
        draw.line((trunk_x, min(center, *child_centers), trunk_x, max(center, *child_centers)),
                  fill='#5a8b76', width=2)
        for child_center in child_centers:
            draw.line((trunk_x, child_center, right[0], child_center), fill='#5a8b76', width=2)
        draw_box(left, parent_y, parent_height, parent, '#dcece2')
        for lines, top, height in child_boxes:
            draw_box(right, top, height, lines, '#ffffff')

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format='PNG', optimize=True)
