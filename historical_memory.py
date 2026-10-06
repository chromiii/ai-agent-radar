"""Deterministic historical Radar index, entity memory and trend memory."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from research_search import QueryPlan, TOPICS, canonical_url, clean

ROOT = Path(__file__).resolve().parent
REPORT_DIRS = {"inbox": "daily", "weekly": "weekly", "company": "company"}
SKIP_HEADINGS = ("发给 ChatGPT", "后续行动", "你需要知道的基础知识", "今日结论", "本周趋势信号", "代表性内容", "噪音词")
STOPWORDS = {"最近", "这周", "本周", "过去", "什么", "哪些", "值得", "关注", "怎么", "如何", "变化",
             "the", "a", "an", "of", "to", "and", "or", "what", "how", "recent", "latest"}
MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
RAW_URL = re.compile(r"https?://[^\s)>]+")
HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
DATE_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


@dataclass
class HistoryDocument:
    id: str
    report_date: str
    report_kind: str
    title: str
    text: str
    source_path: str
    url: str
    external_urls: list[str]
    entity: str | None = None


@dataclass
class HistorySnapshot:
    documents: list[HistoryDocument]
    entities: dict[str, dict[str, Any]]
    trends: dict[str, dict[str, Any]]


def _report_url(source_path: str, config: dict[str, Any] | None = None) -> str:
    cfg = (config or {}).get("history", {})
    repo = clean(cfg.get("repository_url"), 300) or "https://github.com/chromiii/ai-agent-radar"
    branch = clean(cfg.get("repository_branch"), 80) or "main"
    return f"{repo.rstrip('/')}/blob/{branch}/{source_path}"


def _extract_urls(text: str) -> list[str]:
    values = [m.group(2) for m in MD_LINK.finditer(text)] + RAW_URL.findall(text)
    result = []
    for value in values:
        url = canonical_url(value.rstrip(".,;，。；"))
        if url and url not in result:
            result.append(url)
    return result[:8]


def _company_entity(title: str) -> str | None:
    if ":" not in title:
        return None
    entity = clean(title.split(":", 1)[0], 120)
    return entity or None


def _doc_id(source_path: str, title: str, text: str) -> str:
    return hashlib.sha1(f"{source_path}|{title}|{text[:200]}".encode()).hexdigest()[:16]


def parse_report(path: Path, root: Path = ROOT, config: dict[str, Any] | None = None) -> list[HistoryDocument]:
    match = DATE_NAME.fullmatch(path.name)
    if not match or path.parent.name not in REPORT_DIRS:
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    sections, title, body = [], path.stem, []
    for line in lines:
        heading = HEADING.match(line)
        if heading:
            if body:
                sections.append((title, body))
            title, body = clean(re.sub(r"^\d+\.\s*", "", heading.group(2)), 240), []
        else:
            body.append(line)
    if body:
        sections.append((title, body))

    source_path = path.relative_to(root).as_posix()
    fallback = _report_url(source_path, config)
    docs = []
    for title, body_lines in sections:
        if any(skip.casefold() in title.casefold() for skip in SKIP_HEADINGS):
            continue
        text = clean("\n".join(body_lines), 6000)
        if len(text) < 40:
            continue
        urls = _extract_urls(text)
        kind = REPORT_DIRS[path.parent.name]
        docs.append(HistoryDocument(
            id=_doc_id(source_path, title, text),
            report_date=match.group(1),
            report_kind=kind,
            title=title,
            text=text,
            source_path=source_path,
            url=urls[0] if urls else fallback,
            external_urls=urls,
            entity=_company_entity(title) if kind == "company" else None,
        ))
    return docs


def _weekly_trends(path: Path) -> list[tuple[str, str]]:
    tier, result = None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("## Tier 1"):
            tier = "tier1"
        elif stripped.startswith("## Tier 2"):
            tier = "tier2"
        elif stripped.startswith("## "):
            tier = None
        elif tier and stripped.startswith("- "):
            term = clean(stripped[2:].strip("*\` "), 120).casefold()
            if term:
                result.append((term, tier))
    return result


def build_snapshot(root: Path = ROOT, config: dict[str, Any] | None = None) -> HistorySnapshot:
    documents, entity_rows, trend_rows = [], defaultdict(list), defaultdict(list)
    for directory in REPORT_DIRS:
        base = root / directory
        if not base.exists():
            continue
        for path in sorted(base.glob("*.md")):
            docs = parse_report(path, root, config)
            documents.extend(docs)
            for doc in docs:
                if doc.entity:
                    entity_rows[doc.entity].append(doc)
            if directory == "weekly" and DATE_NAME.fullmatch(path.name):
                for term, tier in _weekly_trends(path):
                    trend_rows[term].append({"date": path.stem, "tier": tier, "source_path": path.relative_to(root).as_posix()})

    entities = {}
    for entity, rows in sorted(entity_rows.items()):
        rows.sort(key=lambda d: (d.report_date, d.title))
        entities[entity] = {
            "entity": entity,
            "appearances": len({row.report_date for row in rows}),
            "first_seen": rows[0].report_date,
            "last_seen": rows[-1].report_date,
            "recent_items": [{"date": r.report_date, "title": r.title, "source_path": r.source_path, "url": r.url} for r in rows[-5:]],
        }

    trends = {}
    for term, history in sorted(trend_rows.items()):
        history.sort(key=lambda row: row["date"])
        counts = Counter(row["tier"] for row in history)
        trends[term] = {
            "term": term, "appearances": len(history),
            "tier1_count": counts["tier1"], "tier2_count": counts["tier2"],
            "first_seen": history[0]["date"], "last_seen": history[-1]["date"],
            "history": history[-12:],
        }

    documents.sort(key=lambda d: (d.report_date, d.report_kind, d.title))
    return HistorySnapshot(documents, entities, trends)


def write_snapshot(snapshot: HistorySnapshot, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "index": output_dir / "index.jsonl",
        "entities": output_dir / "entity_memory.json",
        "trends": output_dir / "trend_memory.json",
        "meta": output_dir / "meta.json",
    }
    paths["index"].write_text("".join(json.dumps(asdict(d), ensure_ascii=False) + "\n" for d in snapshot.documents), encoding="utf-8")
    paths["entities"].write_text(json.dumps(snapshot.entities, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["trends"].write_text(json.dumps(snapshot.trends, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = {"schema_version": 1, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "documents": len(snapshot.documents), "entities": len(snapshot.entities), "trends": len(snapshot.trends),
            "source_of_truth": ["inbox/*.md", "weekly/*.md", "company/*.md"]}
    paths["meta"].write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return paths


def tokenize(text: str) -> list[str]:
    text = clean(text, 12000).casefold()
    tokens = re.findall(r"[a-z0-9][a-z0-9._+-]*", text)
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        tokens.extend([segment] if len(segment) <= 4 else [segment[i:i + 2] for i in range(len(segment) - 1)])
    return [token for token in tokens if token not in STOPWORDS and len(token) > 1]


def _query_tokens(plan: QueryPlan, queries: list[str]) -> list[str]:
    parts = [plan.original_query, *queries]
    for topic in plan.topics:
        spec = TOPICS.get(topic, {})
        parts.extend(spec.get("aliases", []))
        parts.extend(spec.get("terms", []))
    return list(dict.fromkeys(tokenize(" ".join(parts))))[:80]


class HistoryIndex:
    def __init__(self, documents: list[HistoryDocument]):
        self.documents = documents
        self.doc_tokens = [Counter(tokenize(d.title + " " + d.text)) for d in documents]
        self.df = Counter()
        for tokens in self.doc_tokens:
            self.df.update(tokens.keys())
        self.avg_len = sum(sum(t.values()) for t in self.doc_tokens) / max(len(self.doc_tokens), 1)

    @classmethod
    def from_repo(cls, root: Path = ROOT, config: dict[str, Any] | None = None) -> "HistoryIndex":
        return cls(build_snapshot(root, config).documents)

    def search(self, plan: QueryPlan, queries: list[str], selected_urls: set[str] | None = None, limit: int = 4) -> list[dict[str, Any]]:
        if limit <= 0 or not self.documents:
            return []
        selected = {canonical_url(u) for u in (selected_urls or set()) if canonical_url(u)}
        q_counts = Counter(_query_tokens(plan, queries))
        if not q_counts:
            return []
        start, end = dt.date.fromisoformat(plan.start_date), dt.date.fromisoformat(plan.end_date)
        n_docs, k1, b = len(self.documents), 1.2, 0.75
        scored = []
        for doc, freqs in zip(self.documents, self.doc_tokens):
            date = dt.date.fromisoformat(doc.report_date)
            if not start <= date <= end or canonical_url(doc.url) in selected:
                continue
            length, score = max(sum(freqs.values()), 1), 0.0
            for token, qf in q_counts.items():
                tf = freqs.get(token, 0)
                if not tf:
                    continue
                df = self.df.get(token, 0)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                score += idf * (tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / max(self.avg_len, 1)))) * min(qf, 2)
            lower = (doc.title + " " + doc.text).casefold()
            score += sum(1.5 for phrase in [plan.original_query, *queries] if len(clean(phrase, 160)) >= 4 and clean(phrase, 160).casefold() in lower)
            if score <= 0:
                continue
            score += {"weekly": 0.35, "daily": 0.2, "company": 0.15}.get(doc.report_kind, 0)
            score += 0.25 * ((date - start).days / max((end - start).days, 1))
            scored.append((score, doc))
        scored.sort(key=lambda pair: (pair[0], pair[1].report_date), reverse=True)
        return [{
            "title": f"[Radar {doc.report_date}] {doc.title}",
            "url": doc.url,
            "summary": clean(doc.text, 1400),
            "date": doc.report_date,
            "date_kind": "radar_observed",
            "provider": "radar_history",
            "evidence_kind": "radar_section",
            "retrieved_query": clean(plan.original_query, 160),
            "relevance_score": round(score, 3),
            "source_path": doc.source_path,
            "entity": doc.entity,
        } for score, doc in scored[:limit]]


def main() -> None:
    from learning_agent import load_config
    from research_search import build_query_plan

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--output-dir", type=Path, default=ROOT / "state" / "history")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--as-of", type=dt.date.fromisoformat, default=None)
    search.add_argument("--limit", type=int, default=5)
    entity = sub.add_parser("entity")
    entity.add_argument("name")
    trend = sub.add_parser("trend")
    trend.add_argument("term")
    args = parser.parse_args()

    config, snapshot = load_config(), build_snapshot(ROOT, load_config())
    if args.command == "build":
        write_snapshot(snapshot, args.output_dir)
        print(f"history build: documents={len(snapshot.documents)} entities={len(snapshot.entities)} trends={len(snapshot.trends)}")
        return
    if args.command == "entity":
        rows = [r for name, r in snapshot.entities.items() if args.name.casefold() in name.casefold()]
    elif args.command == "trend":
        rows = [r for name, r in snapshot.trends.items() if args.term.casefold() in name]
    else:
        today = args.as_of or dt.datetime.now(dt.timezone.utc).date()
        plan = build_query_plan(args.query, today, int(config.get("history", {}).get("lookback_days", 180)))
        rows = HistoryIndex(snapshot.documents).search(plan, plan.expanded_queries, limit=max(1, min(args.limit, 10)))
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
