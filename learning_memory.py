"""Opt-in learning progress for Weekly and Ask Radar.

Only an explicit \`mark\` changes progress. Reading, generating or emailing
learning cards is never interpreted as the user having learned something.
Local progress is private and is deliberately not committed to the public repo.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from research_search import TOPICS, canonical_url, clean, contains

ROOT = Path(__file__).resolve().parent
DEFAULT_PATH = ROOT / "state" / "learning_progress.json"
STATUSES = {"saved", "studied", "practiced", "skipped"}
STATUS_NAMES = {"saved": "已收藏，尚未学习", "studied": "已阅读/理解", "practiced": "已完成动手练习", "skipped": "暂时跳过"}
CARD_HEADING = re.compile(r"^###\s+\d+\.\s+(.+?)\s*$")
DATE_REPORT = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
MD_URL = re.compile(r"\]\((https?://[^)]+)\)")
TOPIC_HINTS = {
    "evaluation": ("evaluation", "benchmark", "评测", "评估", "leaderboard", "swe-bench", "gaia", "osworld"),
    "computer_use": ("computer use", "computer-use", "gui agent", "browser agent", "桌面", "浏览器操作", "移动端操作"),
    "observability": ("observability", "tracing", "auditability", "日志", "可观测", "追踪"),
}
TOPIC_LABELS = {"healthcare": "医疗 Agent", "coding": "Coding Agent", "mcp": "MCP",
                "multi_agent": "多智能体编排", "memory": "Agent Memory", "rag": "RAG",
                "evaluation": "Agent 评测", "computer_use": "Computer Use",
                "observability": "可观测性", "other": "其他应用层"}


@dataclass(frozen=True)
class LearningItem:
    card_id: str
    title: str
    source_url: str
    topic: str
    level: str
    report_date: str


def topic_for(text: str) -> str:
    """Conservative, deterministic topic labeling; not a semantic mastery claim."""
    lower = clean(text, 600).casefold()
    # The exact term is more useful than generic "tool" overlap.
    for name in ("memory", "mcp", "rag", "multi_agent", "healthcare", "coding"):
        if any(contains(lower, alias) for alias in TOPICS[name]["aliases"]):
            return name
    for name, words in TOPIC_HINTS.items():
        if any(contains(lower, word) for word in words):
            return name
    return "other"


def card_id_for(source_url: str, title: str = "") -> str:
    """Stable across reports even when the model rewrites a card title."""
    url = canonical_url(source_url)
    if not url:
        raise ValueError("learning card requires a safe public source URL")
    return "lc-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def _unescape_markdown(text: str) -> str:
    return re.sub(r"\\([\\*_~\[\]#|])", r"\1", clean(text, 260))


def cards_from_weekly(markdown: str, report_date: str = "") -> list[LearningItem]:
    """Read only the '这周先学什么' section; trend lists are not learning cards."""
    if not isinstance(markdown, str):
        raise ValueError("weekly report must be text")
    section = markdown.split("## 这周先学什么", 1)
    if len(section) != 2:
        return []
    body = section[1].split("\n## ", 1)[0]
    found: list[LearningItem] = []
    seen: set[str] = set()
    title = ""
    content: list[str] = []

    def commit() -> None:
        if not title:
            return
        block = "\n".join(content)
        source_line = next((line for line in content if line.startswith("- **来源**")), "")
        urls = MD_URL.findall(source_line)
        if not urls:
            return
        url = canonical_url(urls[0])
        if not url:
            return
        card_id = card_id_for(url, title)
        if card_id in seen:
            return
        seen.add(card_id)
        level = next((line.split("：", 1)[1].strip() for line in content
                      if line.startswith("- **学习深度**：")), "")
        found.append(LearningItem(card_id, _unescape_markdown(title), url,
                                  topic_for(title + " " + block[:450]), level, report_date))

    for line in body.splitlines():
        heading = CARD_HEADING.match(line)
        if heading:
            commit()
            title, content = heading.group(1), []
        elif title:
            content.append(line)
    commit()
    return found


def items_from_file(path: Path) -> list[LearningItem]:
    path = Path(path)
    return cards_from_weekly(
        path.read_text(encoding="utf-8-sig"),
        path.stem if DATE_REPORT.fullmatch(path.name) else "",
    )


def latest_weekly(root: Path = ROOT) -> Path:
    paths = sorted((root / "weekly").glob("????-??-??.md"))
    if not paths:
        raise FileNotFoundError("no weekly Radar report available")
    return paths[-1]


def memory_path(config: dict[str, Any] | None = None) -> Path:
    from_config = (config or {}).get("learning_memory", {}).get("path")
    value = os.environ.get("RADAR_LEARNING_MEMORY_PATH") or from_config
    if not value:
        return DEFAULT_PATH
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def read_memory(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    """No implicit creation: an absent file means no recorded progress."""
    if not Path(path).exists():
        return {"schema_version": 1, "entries": {}}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("learning progress JSON is unreadable") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("entries"), dict):
        raise ValueError("unsupported learning progress schema")
    if len(data["entries"]) > 10000:
        raise ValueError("learning progress exceeds the maximum entry count")
    for card_id, row in data["entries"].items():
        if not isinstance(card_id, str) or not re.fullmatch(r"lc-[0-9a-f]{12}", card_id):
            raise ValueError("learning progress contains an invalid card ID")
        if not isinstance(row, dict) or row.get("status") not in STATUSES:
            raise ValueError("learning progress contains an invalid status")
    return data


def _write_memory(path: Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement prevents a failed write from destroying prior progress.
    fd, tmp = tempfile.mkstemp(prefix=".learning-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def mark_progress(
    item: LearningItem,
    status: str,
    path: Path = DEFAULT_PATH,
    *,
    at: dt.datetime | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError("status must be saved, studied, practiced or skipped")
    if not re.fullmatch(r"lc-[0-9a-f]{12}", item.card_id):
        raise ValueError("invalid card ID")
    if card_id_for(item.source_url) != item.card_id:
        raise ValueError("card ID does not match its source URL")
    timestamp = (at or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat()
    data = read_memory(path)
    previous = data["entries"].get(item.card_id, {})
    if previous.get("status") == status:
        return previous
    history = previous.get("history", [])
    if not isinstance(history, list):
        history = []
    history = [h for h in history if isinstance(h, dict) and h.get("status") in STATUSES][-19:]
    history.append({"status": status, "at": timestamp})
    row = {
        "title": clean(item.title, 240),
        "source_url": canonical_url(item.source_url),
        "topic": item.topic if item.topic in TOPIC_LABELS else "other",
        "status": status,
        "updated_at": timestamp,
        "history": history,
    }
    data["entries"][item.card_id] = row
    _write_memory(path, data)
    return row


def topic_progress(entries: dict[str, Any]) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    for row in entries.values():
        topic = row.get("topic", "other")
        totals.setdefault(topic, {s: 0 for s in STATUSES})
        totals[topic][row["status"]] += 1
    return totals


def prioritize(items: list[LearningItem], memory: dict[str, Any]) -> list[dict[str, Any]]:
    """Rank for next action; no inference that a user has mastered a topic."""
    entries = memory["entries"]
    totals = topic_progress(entries)
    ranked = []
    for index, item in enumerate(items):
        row = entries.get(item.card_id)
        status = row["status"] if row else None
        practiced_in_topic = totals.get(item.topic, {}).get("practiced", 0)
        if status == "skipped":
            score, advice = 0, "你主动跳过了这张卡；除非重新标记，否则不优先推荐。"
        elif status == "practiced":
            score, advice = 10, "这张来源的练习已完成；新内容有变化时再复习。"
        elif status == "studied":
            score, advice = 48, "已读过这张来源；优先补做卡片中的小练习。"
        elif status == "saved":
            score, advice = 90, "已收藏未学习；适合安排本周 15–30 分钟练习。"
        elif practiced_in_topic:
            score, advice = 83, "同主题已有练习记录；先看本条的新实现，再比较边界和失败恢复，避免重复基础。"
        else:
            score, advice = 100, "新学习条目；先理解概念，再决定是否做小练习。"
        ranked.append({"item": item, "score": score, "status": status, "advice": advice, "original_order": index})
    ranked.sort(key=lambda row: (-row["score"], row["original_order"]))
    return ranked


def recommendation_markdown(items: list[LearningItem], memory: dict[str, Any], limit: int = 3) -> str:
    if not items:
        return ""
    entries = memory["entries"]
    if not entries:
        return ""
    ranked = prioritize(items, memory)
    picks = [row for row in ranked if row["score"] >= 48][:limit]
    lines = ["## 结合你的学习记录", "",
             "仅依据你主动标记的进度调整阅读顺序；收到周报或生成回答不算已学习。", ""]
    if not picks:
        lines.append("本期条目都已练习或暂时跳过；没有自动重复安排基础任务。")
    for index, row in enumerate(picks, 1):
        item = row["item"]
        lines.extend([
            f"{index}. **{_safe_markdown(item.title)}**（{TOPIC_LABELS[item.topic]}）",
            f"   - {row['advice']}",
            f"   - 来源：{item.source_url}；卡片 ID：\`{item.card_id}\`",
        ])
    completed = sum(r["status"] == "practiced" for r in entries.values())
    reviewed = sum(r["status"] == "studied" for r in entries.values())
    lines.extend(["", f"已明确记录：阅读 {reviewed} 张、完成练习 {completed} 张（不是能力认证）。"])
    return "\n".join(lines)


def _safe_markdown(value: str) -> str:
    return re.sub(r"([\\\`*_\\[\\]#|])", r"\\\1", clean(value, 240))


def weekly_recommendations(markdown: str, path: Path = DEFAULT_PATH, report_date: str = "") -> str:
    if not Path(path).is_file():
        return ""
    return recommendation_markdown(cards_from_weekly(markdown, report_date), read_memory(path))


def research_recommendations(findings: list[dict[str, Any]], selected: list[dict[str, Any]], path: Path = DEFAULT_PATH) -> str:
    if not Path(path).is_file():
        return ""
    sources = {source.get("id"): source.get("url") for source in selected}
    items = []
    for finding in findings:
        urls = [canonical_url(sources.get(i)) for i in finding.get("evidence_ids", [])]
        url = next((url for url in urls if url), None)
        if not url:
            continue
        title = clean(finding.get("topic"), 240)
        items.append(LearningItem(card_id_for(url), title, url, topic_for(title), str(finding.get("level", "")), ""))
    return recommendation_markdown(items, read_memory(path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", type=Path, default=None, help="Local private progress JSON path")
    sub = parser.add_subparsers(dest="command", required=True)
    catalog = sub.add_parser("catalog", help="List IDs from a Weekly Radar report")
    catalog.add_argument("--weekly", type=Path, default=None)
    mark = sub.add_parser("mark", help="Explicitly record progress for a known Weekly card")
    mark.add_argument("card_id")
    mark.add_argument("status", choices=sorted(STATUSES))
    mark.add_argument("--weekly", type=Path, default=None)
    recommend = sub.add_parser("recommend", help="Rank Weekly cards against your private progress")
    recommend.add_argument("--weekly", type=Path, default=None)
    sub.add_parser("status", help="Show explicitly marked learning progress")
    args = parser.parse_args()
    path = args.memory or memory_path()

    if args.command == "status":
        data = read_memory(path)
        for cid, row in sorted(data["entries"].items(), key=lambda r: r[1].get("updated_at", ""), reverse=True):
            print(f"{cid} [{STATUS_NAMES[row['status']]}] {row.get('title', '')}")
        print(f"Total manually marked: {len(data['entries'])}")
        return

    weekly = args.weekly or latest_weekly()
    items = items_from_file(weekly)
    if args.command == "catalog":
        for item in items:
            print(f"{item.card_id} | {item.title} | {TOPIC_LABELS[item.topic]} | {item.source_url}")
        return
    if args.command == "mark":
        item = next((c for c in items if c.card_id == args.card_id), None)
        if item is None:
            raise SystemExit("card ID not found in selected Weekly report; inspect 'catalog' or choose --weekly")
        row = mark_progress(item, args.status, path)
        print(f"{item.card_id}: {STATUS_NAMES[row['status']]} ({path})")
        return

    print(recommendation_markdown(items, read_memory(path)) or "No explicit learning progress yet. Use 'mark' first.")


if __name__ == "__main__":
    main()
