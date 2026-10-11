"""One learning-card contract and renderer for Weekly and Ask Radar."""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote

from research_search import canonical_url, clean


LEVEL_NAMES = {"know": "先知道", "build": "值得动手", "understand_why": "理解原因"}
CARD_PROMPT = (
    "Learning cards must explain what the concept is, where it is useful, how deeply to learn it, "
    "and one small practice task. level is know, build or understand_why. "
    "one_liner is a concise concept definition, not just a news headline. "
    "learn has 2–4 specific engineering concepts. practice_minutes is an integer from 15 to 30. "
    "done_when is an observable completion criterion for the practice. "
    "Use toy inputs or mocks so the exercise fits the timebox; do not ask for a full paper reproduction, "
    "production deployment or entire benchmark run. Do not invent package commands or APIs. "
    "done_when must check only steps named in the exercise; it must not add an agent client, "
    "server setup, login or other new prerequisites. Prefer a self-contained mock or local toy exercise. "
    "Assume only basic local Python and toy/mock inputs are ready. The timeboxed exercise must not require "
    "API keys, real model calls, model downloads, a vector database or a new framework/SDK installation. "
    "For retrieval use small documents and supplied toy rankings/scores; for tool interfaces use local "
    "schema dictionaries and a mock dispatcher. Clearly call these simulations, not real protocol integrations. "
    "Keep one_liner and application under 120 Chinese characters, each learn point under 60, "
    "the practice under 160 and done_when under 100. Use Simplified Chinese."
)


def markdown_text(value: Any) -> str:
    text = html.escape(clean(value, 6000), quote=False)
    return re.sub(r"([\\`*_\[\]#|])", r"\\\1", text)


def source_link(label: str, url: str) -> str:
    safe_url = canonical_url(url)
    if not safe_url:
        return ""
    return f"[{markdown_text(label)}]({quote(safe_url, safe='/:?&=%+@-._~')})"


def learning_details(entry: dict[str, Any]) -> dict[str, Any]:
    """Validate teaching fields; source support is checked separately."""
    if not isinstance(entry.get("level"), str) or entry["level"] not in LEVEL_NAMES:
        raise ValueError("learning card level must be know, build or understand_why")
    one_liner, done_when = clean(entry.get("one_liner"), 220), clean(entry.get("done_when"), 180)
    raw_learn = entry.get("learn")
    if not isinstance(raw_learn, list) or not 2 <= len(raw_learn) <= 4:
        raise ValueError("learning card learn needs 2–4 points")
    learn = [clean(point, 100) for point in raw_learn]
    minutes = entry.get("practice_minutes")
    if not one_liner or not done_when or not all(learn):
        raise ValueError("learning card needs definition, learning points and completion criterion")
    if type(minutes) is not int or not 15 <= minutes <= 30:
        raise ValueError("practice_minutes must be an integer from 15 to 30")
    if any(re.search(r"https?://|\[[^\]]*\]\([^)]*\)|\[S\d+\]", t, re.I) for t in [one_liner, done_when, *learn]):
        raise ValueError("learning card text must use structured source references instead of links")
    return {"level": entry["level"], "one_liner": one_liner, "learn": learn,
            "practice_minutes": minutes, "done_when": done_when}


def weekly_cards(value: Any, representative_items: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    allowed = {item.get("url") for item in representative_items if canonical_url(item.get("url"))}
    cards = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        try:
            details = learning_details(entry)
        except ValueError:
            continue
        card = {key: clean(entry.get(key), 260) for key in ("title", "why_now", "application", "hands_on")}
        if not all(card.values()):
            continue
        raw_urls = entry.get("source_urls", [])
        urls = list(dict.fromkeys(url for url in raw_urls if isinstance(url, str) and url in allowed)) if isinstance(raw_urls, list) else []
        if not urls:
            continue
        card.update(details, source_urls=urls[:3])
        cards.append(card)
        if len(cards) >= limit:
            break
    return cards


def research_card(finding: dict[str, Any], sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"title": finding["topic"], "why_now": finding["claim"], "application": finding["application"],
            "hands_on": finding["try_next"], **{key: finding[key] for key in
                ("level", "one_liner", "learn", "practice_minutes", "done_when")},
            "evidence_label": "近期研究方向" if finding["claim_type"] == "trend" else "实现 / 活动信号",
            "sources": [sources[source_id] for source_id in finding["evidence_ids"]]}


def render_learning_card(card: dict[str, Any], number: int) -> list[str]:
    lines = [f"### {number}. {markdown_text(card.get('title'))}", "",
             f"- **学习深度**：{LEVEL_NAMES.get(card.get('level'), '先知道')}",
             f"- **30 秒概念**：{markdown_text(card.get('one_liner'))}",
             f"- **为什么值得了解**：{markdown_text(card.get('why_now'))}",
             f"- **用在哪里**：{markdown_text(card.get('application'))}",
             f"- **应用层学到这里**：{'；'.join(markdown_text(point) for point in card.get('learn', []))}",
             f"- **动手建议（建议 {card.get('practice_minutes')} 分钟）**：{markdown_text(card.get('hands_on'))}",
             f"- **完成标准**：{markdown_text(card.get('done_when'))}"]
    if card.get("evidence_label"):
        lines.append(f"- **证据类型**：{card['evidence_label']}")
    links = []
    for source in card.get("sources", []):
        link = source_link(source["id"], source["url"])
        if source.get("date"):
            date_kind = source.get("date_kind")
            kind = "发布" if date_kind == "published" else "Radar 记录" if date_kind == "radar_observed" else "仓库活动"
            link += f"（{kind} {source['date']}）"
        links.append(link)
    if not links:
        links = [source_link(f"来源 {i}", url) for i, url in enumerate(card.get("source_urls", []), 1)]
    lines.extend(["- **来源**：" + " / ".join(link for link in links if link), ""])
    return lines
