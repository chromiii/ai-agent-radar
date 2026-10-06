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
            url=fallback,
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
            term = clean(stripped[2:].strip("*` "), 120).casefold()
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
            "recent_items": [{"date": r.report_date, "title": r.title, "source_path": r.source_path,
                              "url": r.url, "external_urls": r.external_urls} for r in rows[-5:]],
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

    # Derived memory documents make recurrence searchable without turning memory into a publication.
    for entity, row in entities.items():
        latest = row["recent_items"][-1]
        history_text = "; ".join(f"{item['date']} {item['title']}" for item in row["recent_items"])
        documents.append(HistoryDocument(
            id=_doc_id(latest["source_path"], f"Entity memory: {entity}", history_text),
            report_date=row["last_seen"],
            report_kind="entity_memory",
            title=f"Entity memory: {entity}",
            text=(
                f"{entity} appeared on {row['appearances']} Radar dates from {row['first_seen']} to {row['last_seen']}. "
                f"Recent observations: {history_text}"
            ),
            source_path=latest["source_path"],
            url=_report_url(latest["source_path"], config),
            external_urls=list(dict.fromkeys(
                url for item in row["recent_items"] for url in item.get("external_urls", [])
            ))[:8],
            entity=entity,
        ))

    for term, row in trends.items():
        latest = row["history"][-1]
        history_text = "; ".join(f"{item['date']} {item['tier']}" for item in row["history"])
        documents.append(HistoryDocument(
            id=_doc_id(latest["source_path"], f"Trend memory: {term}", history_text),
            report_date=row["last_seen"],
            report_kind="trend_memory",
            title=f"Trend memory: {term}",
            text=(
                f"{term} appeared in {row['appearances']} Weekly Radar reports from {row['first_seen']} to {row['last_seen']}; "
                f"tier1={row['tier1_count']}, tier2={row['tier2_count']}. History: {history_text}"
            ),
            source_path=latest["source_path"],
            url=_report_url(latest["source_path"], config),
            external_urls=[],
        ))

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

            # Once the query planner recognizes a domain, historical retrieval must
            # actually mention that domain. This prevents generic "agent/tool" overlap
            # from polluting MCP, memory, RAG, healthcare, etc. history results.
            topic_groups = [TOPICS[name]["terms"] for name in plan.topics if name in TOPICS]
            if topic_groups and not all(any(contains(lower, term) for term in group) for group in topic_groups):
                continue

            score += sum(
                1.5
                for phrase in [plan.original_query, *queries]
                if len(clean(phrase, 160)) >= 4 and clean(phrase, 160).casefold() in lower
            )
            if score <= 0:
                continue

            if doc.report_kind == "trend_memory":
                memory_term = clean(doc.title.split(":", 1)[-1], 120)
                if memory_term and (
                    contains(plan.original_query, memory_term)
                    or any(contains(query, memory_term) for query in queries)
                ):
                    score += 6.0
                if any(word in plan.original_query.casefold() for word in ("变化", "趋势", "历史", "反复", "过去", "change", "trend", "history")):
                    score += 2.0
            elif doc.report_kind == "entity_memory":
                entity_term = clean(doc.title.split(":", 1)[-1], 120)
                if entity_term and contains(plan.original_query, entity_term):
                    score += 5.0

            score += {"trend_memory": 0.9, "entity_memory": 0.8, "weekly": 0.35, "daily": 0.2, "company": 0.15}.get(doc.report_kind, 0)
            score += 0.25 * ((date - start).days / max((end - start).days, 1))
            scored.append((score, doc))
        scored.sort(key=lambda pair: (pair[0], pair[1].report_date), reverse=True)

        # Collapse repeated observations of the same underlying external item. Recurrence
        # stays visible as metadata instead of consuming every retrieval slot.
        groups: dict[str, list[tuple[float, HistoryDocument]]] = {}
        order: list[str] = []
        for score, doc in scored:
            if doc.report_kind in ("trend_memory", "entity_memory"):
                key = f"{doc.report_kind}:{doc.title.casefold()}"
            elif doc.external_urls:
                key = "external:" + doc.external_urls[0]
            else:
                key = "report:" + doc.source_path
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((score, doc))

        result = []
        for key in order:
            rows = groups[key]
            if any(canonical_url(doc.url) in selected for _, doc in rows):
                continue
            score, doc = rows[0]
            dates = sorted({item.report_date for _, item in rows})
            paths = list(dict.fromkeys(item.source_path for _, item in rows))
            external_urls = list(dict.fromkeys(url for _, item in rows for url in item.external_urls))[:8]
            recurrence = ""
            if len(dates) > 1:
                recurrence = (
                    f"Historical recurrence: observed on {len(dates)} Radar dates from {dates[0]} to {dates[-1]}. "
                )
            result.append({
                "title": (f"[Radar Memory] {doc.title}" if doc.report_kind.endswith("_memory")
                          else f"[Radar {doc.report_date}] {doc.title}"),
                "url": doc.url,
                "summary": clean(recurrence + doc.text, 1400),
                "date": doc.report_date,
                "date_kind": "radar_observed",
                "provider": "radar_history",
                "evidence_kind": "radar_memory" if doc.report_kind.endswith("_memory") else "radar_section",
                "retrieved_query": clean(plan.original_query, 160),
                "relevance_score": round(score, 3),
                "source_path": doc.source_path,
                "source_paths": paths[:12],
                "external_urls": external_urls,
                "entity": doc.entity,
                "observation_count": len(dates),
                "first_seen": dates[0],
                "last_seen": dates[-1],
                "observation_dates": dates[-12:],
            })
            if len(result) >= limit:
                break
        return result


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
