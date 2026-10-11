"""One Saturday briefing: weekly news + learning path + Breaking Desk queue.

Historical reports are citations, not independent proof that a trend is real.
The weekly digest is a reading queue, not an LLM-written factual verdict.
"""
from __future__ import annotations
import argparse
import datetime as dt
import re
from pathlib import Path
from typing import Any
from historical_memory import parse_report
from research_search import canonical_url, clean
from breaking_news import read_queue, normalized_news_url
from learning_path import format_plan
from learning_memory import weekly_recommendations

ROOT = Path(__file__).resolve().parent


GENERIC_HEADINGS = {"必看索引", "tech blog", "blog", "homepage", "最新资讯", "news", "updates", "overview"}
EMBEDDED_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})\b", re.I
)


def stale_headline(title: str, start: dt.date, end: dt.date) -> bool:
    """Reject explicit old publication dates in a headline; unknown dates stay qualified."""
    match = EMBEDDED_DATE.search(title)
    if not match:
        return False
    month, day, year = match.groups()
    if month.casefold() == "sept":
        month = "Sep"
    date = None
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            date = dt.datetime.strptime(f"{month} {day} {year}", fmt).date()
            break
        except ValueError:
            pass
    return date is not None and not start <= date <= end


def generic_heading(title: str) -> bool:
    normalized = clean(title, 180).casefold().split(":")[-1].strip()
    return normalized in GENERIC_HEADINGS


def collect(root: Path, end: dt.date, days: int = 7, limit_each: int = 8) -> dict[str, list[dict[str, Any]]]:
    if not 1 <= days <= 31:
        raise ValueError("days must be 1-31")
    if not 1 <= limit_each <= 30:
        raise ValueError("limit_each must be 1-30")
    groups = {"research": [], "companies": []}
    seen: set[str] = set()
    for folder, key in (("inbox", "research"), ("company", "companies")):
        candidates: list[dict[str, Any]] = []
        for path in sorted((root / folder).glob("????-??-??.md"), reverse=True):
            try:
                date = dt.date.fromisoformat(path.stem)
            except ValueError:
                continue
            if not (end - dt.timedelta(days=days - 1)) <= date <= end:
                continue
            for doc in parse_report(path, root):
                if not doc.external_urls or generic_heading(doc.title):
                    continue
                if stale_headline(doc.title, end - dt.timedelta(days=days - 1), end):
                    continue
                url = next((u for u in doc.external_urls if normalized_news_url(u)), None)
                if not url:
                    continue
                key_url = normalized_news_url(url)
                if key_url in seen or "chromiii/ai-agent-radar" in key_url:
                    continue
                seen.add(key_url)
                candidates.append({"date": doc.report_date, "title": clean(doc.title, 180), "url": key_url,
                                   "report": doc.source_path, "summary": clean(doc.text, 180)})
        groups[key] = candidates[:limit_each]
    return groups


def build_briefing(root: Path = ROOT, as_of: dt.date | None = None,
                   queue_path: Path | None = None, path_progress: Path | None = None) -> str:
    from learning_path import PROGRESS
    as_of = as_of or dt.date.today()
    articles = collect(root, as_of)
    queue = read_queue(queue_path or (root / "state/breaking_queue.json"))
    rows = sorted(queue["items"].values(), key=lambda r: (r["last_seen"], r["severity"]), reverse=True)
    pending = [row for row in rows if row["status"] in {"pending", "approved"} and
               row["last_seen"] >= (as_of - dt.timedelta(days=6)).isoformat()]
    lines = [f"# AI Agent Radar · 周度情报与学习简报 — {as_of.isoformat()}", "",
             f"覆盖区间：{(as_of - dt.timedelta(days=6)).isoformat()} 至 {as_of.isoformat()}。资讯按已收集报告整理，报告日不等于事件发布日期。", "",
             "## 本周值得查看的论文 / 工程项目", ""]
    for index, row in enumerate(articles["research"], 1):
        lines.append(f"{index}. [{row['title']}]({row['url']})（Radar {row['date']}）")
    if not articles["research"]:
        lines.append("本周没有可引用的新研究条目。")
    lines.extend(["", "## 本周公司与产品线索（以 Radar 收录日为准）", ""])
    for index, row in enumerate(articles["companies"], 1):
        lines.append(f"{index}. [{row['title']}]({row['url']})（Radar {row['date']}）")
    if not articles["companies"]:
        lines.append("本周没有可引用的新公司动态。")
    lines.extend(["", "## Breaking Desk · 待核验 / 已确认", ""])
    for row in pending[:6]:
        marker = "人工已确认" if row["status"] == "approved" else "候选待核验"
        lines.append(f"- [{row['title']}]({row['source_url']}) — {marker}，{row['severity']}，ID：\u0060{row['id']}\u0060")
    if not pending:
        lines.append("没有符合本周窗口的 Breaking 候选。")
    learning_report = root / "weekly" / f"{as_of.isoformat()}.md"
    personal_section = (weekly_recommendations(
        learning_report.read_text(encoding="utf-8"), root / "state/learning_progress.json", as_of.isoformat())
        if learning_report.is_file() else "")
    lines.extend(["", "注意：Breaking 候选需要复核真实性、影响范围和是否已经解决；默认不触发独立邮件。", "",
                  format_plan(progress_path=path_progress or (root / "state/learning_path.json"), today=as_of),
                  "", personal_section, "", "## 深入阅读", "",
                  f"- 本周学习周报：weekly/{as_of.isoformat()}.md",
                  "- 历史 Radar：参见 inbox/、company/ 与 state/ 下的 Breaking 状态记录",
                  ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "briefings")
    args = parser.parse_args()
    from radar import today_local
    day = args.as_of or today_local()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / f"{day.isoformat()}.md"
    path.write_text(build_briefing(as_of=day), encoding="utf-8")
    print(f"Weekly briefing: {path}")


if __name__ == "__main__":
    main()
