"""Responsive, untrusted-source-safe HTML newsletter renderer."""
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path
from urllib.parse import urlsplit

MAX_BODY = 180_000
INLINE = re.compile(r"\[([^\]\n]{1,350})\]\((https?://[^\s)]+)\)|\*\*([^*\n]{1,350})\*\*|\x60([^\x60\n]{1,250})\x60")
HEAD = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
ORDERED = re.compile(r"^\s*(\d{1,2})\.\s+(.+)$")
UNORDERED = re.compile(r"^\s*-\s+(.+)$")


def safe_url(url: str) -> str:
    value = url.strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        return ""
    if parts.scheme not in {"https", "http"} or not parts.netloc or "@" in parts.netloc:
        return ""
    return value if len(value) <= 2000 else ""


def inline_markup(text: str) -> str:
    """Escape all text except recognized, explicitly constructed safe markup."""
    out: list[str] = []
    cursor = 0
    for match in INLINE.finditer(text):
        out.append(html.escape(text[cursor:match.start()], quote=True))
        label, url, strong, code = match.groups()
        if label is not None:
            verified = safe_url(url)
            if verified:
                out.append(
                    '<a href="' + html.escape(verified, quote=True) +
                    '" style="color:#2563eb;text-decoration:underline;font-weight:600"'
                    ' target="_blank" rel="noopener noreferrer">' + html.escape(label) + "</a>"
                )
            else:
                out.append(html.escape(label))
        elif strong is not None:
            out.append("<strong>" + html.escape(strong) + "</strong>")
        elif code is not None:
            out.append('<code style="font-family:Consolas,monospace;background:#eef2f7;'
                       'padding:2px 5px;border-radius:4px">' + html.escape(code) + "</code>")
        cursor = match.end()
    out.append(html.escape(text[cursor:], quote=True))
    return "".join(out)


def render_html(markdown: str, subject: str = "AI Agent Radar · 每周精选") -> str:
    if not isinstance(markdown, str) or len(markdown) > MAX_BODY:
        raise ValueError("Invalid or oversized newsletter")
    subject_escaped = html.escape(subject[:180])
    sections: list[str] = []
    current: list[str] = []
    list_type: str | None = None
    heading_count = 0

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            current.append("</" + list_type + ">")
            list_type = None

    def close_card() -> None:
        close_list()
        if current:
            sections.append(
                '<tr><td style="padding:0 26px 18px"><table role="presentation" cellpadding="0"'
                ' cellspacing="0" width="100%" style="border:1px solid #e2e8f0;'
                'border-radius:14px;background:#ffffff"><tr><td style="padding:22px 24px">'
                + "\n".join(current) + "</td></tr></table></td></tr>"
            )
            current.clear()

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            close_list()
            continue
        heading = HEAD.match(line)
        if heading:
            depth = len(heading.group(1))
            label = heading.group(2)
            if depth <= 2:
                close_card()
                if depth == 1 and heading_count == 0:
                    heading_count += 1
                    continue
                heading_count += 1
                current.append(
                    '<h2 style="color:#0f172a;margin:0 0 16px;font-size:19px;'
                    'line-height:1.4;font-weight:750">' + inline_markup(label) + "</h2>"
                )
            else:
                close_list()
                current.append(
                    '<h3 style="color:#334155;margin:16px 0 8px;font-size:16px;'
                    'line-height:1.45">' + inline_markup(label) + "</h3>"
                )
            continue
        ordered = ORDERED.match(line)
        bullet = UNORDERED.match(line)
        if ordered or bullet:
            target = "ol" if ordered else "ul"
            if list_type != target:
                close_list()
                current.append(
                    '<' + target + ' style="padding-left:23px;margin:8px 0 12px;'
                    'color:#334155;font-size:14px;line-height:1.75">'
                )
                list_type = target
            body = ordered.group(2) if ordered else bullet.group(1)
            current.append('<li style="padding:5px 0">' + inline_markup(body) + "</li>")
        else:
            close_list()
            current.append(
                '<p style="margin:8px 0 14px;color:#475569;font-size:14px;'
                'line-height:1.75">' + inline_markup(line) + "</p>"
            )
    close_card()
    content = "\n".join(sections)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{subject_escaped}</title></head>
<body style="padding:0;margin:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,'PingFang SC','Microsoft YaHei',sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9">
<tr><td align="center" style="padding:24px 12px 34px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"
style="max-width:680px;background:#f8fafc;border-radius:20px;overflow:hidden">
<tr><td style="background:#0f172a;padding:32px 28px 30px">
<p style="color:#93c5fd;font-size:11px;letter-spacing:2px;font-weight:700;margin:0 0 14px">AI AGENT RADAR · WEEKLY EDITION</p>
<h1 style="color:#ffffff;font-size:27px;line-height:1.35;margin:0 0 9px">你的每周 AI Agent 情报</h1>
<p style="color:#cbd5e1;font-size:14px;line-height:1.65;margin:0">重要进展 · 公司动态 · Breaking Desk · 本周 LangChain 学习任务</p>
</td></tr>
<tr><td style="padding:22px 26px 14px">
<p style="font-size:12px;line-height:1.6;color:#64748b;margin:0">
一封邮件看完本周变化。每条消息可点开原始来源；Breaking 候选仍需人工确认。</p>
</td></tr>
{content}
<tr><td style="padding:10px 30px 25px">
<p style="color:#94a3b8;font-size:11px;line-height:1.7;margin:0">
此邮件由 AI Agent Radar 整理。Radar 收录日期不一定等于正式发布日期；
新闻摘要仅供筛选阅读，不代表已完成独立事实核验。</p>
</td></tr>
</table>
</td></tr></table></body></html>
"""


def render_text(markdown: str) -> str:
    """Readable non-Markdown email fallback for clients without HTML support."""
    lines = []
    for line in markdown.splitlines():
        line = re.sub(r"^\s*#{1,3}\s*", "", line)
        line = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 — \2", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"\x60([^\x60]+)\x60", r"\1", line)
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--subject", default="AI Agent Radar · 每周精选")
    args = parser.parse_args()
    text = args.report.read_text(encoding="utf-8")
    output = args.output or args.report.with_suffix(".html")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(text, args.subject), encoding="utf-8")
    print(f"Rendered HTML newsletter: {output}")


if __name__ == "__main__":
    main()
