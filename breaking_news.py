"""Source-backed Breaking News candidate desk. Never sends auto alerts.

A candidate requires a concrete source in a Daily/Company Radar report
AND explicit high-impact wording. Publication recency alone is not breaking.
Only a human may approve an item for an optional urgent notification.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from historical_memory import REPORT_DIRS, parse_report
from research_search import canonical_url, clean

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "state" / "breaking_queue.json"
STATES = {"pending", "approved", "dismissed", "resolved"}
SEVERE = (
    (re.compile(r"\b(security advisory|critical vulnerability|actively exploited|zero.day|rce|cve-\d{4}|data breach)\b|严重漏洞|重大安全漏洞|数据泄露", re.I), "security"),
    (re.compile(r"\b(deprecat(?:e|ion|ed)|breaking change|api shutdown|service disruption|major outage|sunset)\b|停服|重大故障|接口废弃|兼容性破坏", re.I), "breaking_change"),
    (re.compile(r"\b(general availability|major release|new model release)\b|正式发布|重大版本发布", re.I), "major_release"),
)
OFFICIAL_HOSTS = {
    "docs.langchain.com", "blog.langchain.com", "github.blog",
    "openai.com", "www.openai.com", "anthropic.com", "www.anthropic.com",
    "blog.google", "developers.googleblog.com", "huggingface.co",
}
STATUS_NAMES = {"pending":"待核验", "approved":"已确认/待处理", "dismissed":"已忽略", "resolved":"已处理"}


def is_official(url: str) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host in OFFICIAL_HOSTS:
        return True
    # GitHub release notes and security advisories are useful first-party signals,
    # but repo owner legitimacy still needs reviewer confirmation.
    if host == "github.com" and ("/releases/" in url or "/security/advisories/" in url):
        return True
    return False


def read_queue(path: Path = QUEUE) -> dict[str, Any]:
    if not Path(path).exists():
        return {"schema_version": 1, "items": {}}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("items"), dict):
        raise ValueError("invalid breaking queue schema")
    for k, v in data["items"].items():
        if not isinstance(k, str) or not isinstance(v, dict) or v.get("status") not in STATES:
            raise ValueError("invalid breaking queue entry")
    return data


def write_queue(path: Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".breaking-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def candidate_id(url: str) -> str:
    return "bn-" + hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()[:12]


def identify(doc) -> dict[str, Any] | None:
    urls = [canonical_url(u) for u in doc.external_urls if canonical_url(u)]
    urls = [u for u in urls if "chromiii/ai-agent-radar/" not in u]
    if not urls:
        return None
    # Match impact in the headline/first paragraph, NOT random quoted body/sidebar.
    title = clean(doc.title, 200)
    snippet = clean(doc.text[:300], 300)
    impact = []
    for pattern, category in SEVERE:
        if pattern.search(title + " " + snippet):
            impact.append(category)
    if not impact:
        return None
    official_url = next((u for u in urls if is_official(u)), None)
    url = official_url or urls[0]
    # A non-first-party single report is an unverified candidate, never auto-breaking.
    severity = "high" if official_url and ("security" in impact or "breaking_change" in impact) else "review"
    return {
        "id": candidate_id(url), "title": title, "source_url": url,
        "first_seen": doc.report_date, "last_seen": doc.report_date,
        "report_paths": [doc.source_path],
        "impact_categories": impact, "official_source_candidate": bool(official_url),
        "severity": severity, "status": "pending", "history": [],
    }


def scan_reports(root: Path = ROOT, queue_path: Path = QUEUE, *, as_of: dt.date | None = None,
                 lookback_days: int = 7) -> dict[str, Any]:
    as_of = as_of or dt.date.today()
    if not 1 <= lookback_days <= 60:
        raise ValueError("lookback_days must be 1-60")
    data = read_queue(queue_path)
    for folder in ("inbox", "company"):
        for report in sorted((root / folder).glob("????-??-??.md")):
            try:
                date = dt.date.fromisoformat(report.stem)
            except ValueError:
                continue
            if not (as_of - dt.timedelta(days=lookback_days-1)) <= date <= as_of:
                continue
            for doc in parse_report(report, root):
                candidate = identify(doc)
                if not candidate:
                    continue
                old = data["items"].get(candidate["id"])
                if old:
                    old["last_seen"] = max(old["last_seen"], candidate["last_seen"])
                    old["report_paths"] = list(dict.fromkeys(old["report_paths"] + candidate["report_paths"]))[-20:]
                    # A repeated observation must not undo a human decision.
                    continue
                data["items"][candidate["id"]] = candidate
    write_queue(queue_path, data)
    return data


OFFICIAL_REPOS = (
    "langchain-ai/langchain",
    "langchain-ai/langgraph",
    "langchain-ai/deepagents",
    "crewAIInc/crewAI",
    "run-llama/llama_index",
)


def watch_official_releases(*, queue_path: Path = QUEUE, as_of: dt.datetime | None = None,
                            request=None) -> dict[str, Any]:
    """Review recent first-party release notes. No automatic notices are sent.

    Reads a fixed allowlist of public GitHub release APIs; never executes release text.
    """
    import requests

    as_of = as_of or dt.datetime.now(dt.timezone.utc)
    request = request or requests.get
    data = read_queue(queue_path)
    for repo in OFFICIAL_REPOS:
        url = f"https://api.github.com/repos/{repo}/releases?per_page=5"
        try:
            response = request(url, headers={"Accept": "application/vnd.github+json",
                                             "User-Agent": "ai-agent-radar-breaking/1"},
                               timeout=12)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                continue
        except (requests.RequestException, ValueError, TypeError):
            # A failed provider is not a confirmed absence of breaking news.
            continue
        for release in payload[:5]:
            if not isinstance(release, dict):
                continue
            title = clean(release.get("name") or release.get("tag_name"), 160)
            body = clean(release.get("body"), 1600)
            published = str(release.get("published_at") or "")
            link = canonical_url(release.get("html_url"))
            if not title or not link or not link.startswith(f"https://github.com/{repo}/releases/"):
                continue
            try:
                published_dt = dt.datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                continue
            if published_dt.tzinfo is None:
                continue
            if not dt.timedelta(0) <= as_of - published_dt <= dt.timedelta(hours=72):
                continue
            categories = [category for regex, category in SEVERE if regex.search(title + " " + body[:600])]
            if not categories:
                continue
            cid = candidate_id(link)
            if cid in data["items"]:
                continue
            data["items"][cid] = {
                "id": cid, "title": f"{repo}: {title}", "source_url": link,
                "first_seen": published_dt.date().isoformat(),
                "last_seen": published_dt.date().isoformat(),
                "report_paths": [], "impact_categories": categories,
                "official_source_candidate": True,
                "severity": "high" if any(x in categories for x in ("security", "breaking_change")) else "review",
                "status": "pending", "history": [], "source_kind": "official_github_release",
            }
    write_queue(queue_path, data)
    return data


def mark_item(item_id: str, status: str, *, queue_path: Path = QUEUE, today: dt.date | None = None) -> dict[str, Any]:
    if status not in {"approved", "dismissed", "resolved", "pending"}:
        raise ValueError("unknown decision")
    data = read_queue(queue_path)
    if item_id not in data["items"]:
        raise ValueError("candidate not found; scan sources first")
    row = data["items"][item_id]
    if row["status"] == status:
        return row
    row["status"] = status
    row["history"] = row.get("history", [])[-19:] + [{"date": (today or dt.date.today()).isoformat(), "status": status}]
    write_queue(queue_path, data)
    return row


def render_desk(data: dict[str, Any], *, include_dismissed: bool = False) -> str:
    rows = [v for v in data["items"].values() if include_dismissed or v["status"] != "dismissed"]
    rows.sort(key=lambda v: (v["status"] == "pending", v["severity"] == "high", v["last_seen"]), reverse=True)
    lines = ["# Breaking News Desk", "",
             "以下为规则筛出的候选信号，并非已证实的突发新闻；重大通知必须人工确认。", ""]
    for row in rows[:50]:
        lines.extend([
            f"- **{row['id']}** [{row['title']}]({row['source_url']})",
            f"  - 状态：{STATUS_NAMES[row['status']]}；待核验级别：{row['severity']}；来源日期：{row['first_seen']} → {row['last_seen']}",
            f"  - 原因：{', '.join(row['impact_categories'])}；来源：{', '.join(row['report_paths'][:3])}",
        ])
    if not rows:
        lines.append("暂无规则匹配的重大更新候选。")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=QUEUE)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--lookback-days", type=int, default=7)
    sub.add_parser("watch")
    sub.add_parser("list")
    mark = sub.add_parser("mark")
    mark.add_argument("item_id")
    mark.add_argument("status", choices=["pending", "approved", "dismissed", "resolved"])
    args = parser.parse_args()
    if args.command == "scan":
        data = scan_reports(queue_path=args.queue, lookback_days=args.lookback_days)
    elif args.command == "watch":
        data = watch_official_releases(queue_path=args.queue)
    elif args.command == "mark":
        mark_item(args.item_id, args.status, queue_path=args.queue)
        data = read_queue(args.queue)
    else:
        data = read_queue(args.queue)
    print(render_desk(data))


if __name__ == "__main__":
    main()
