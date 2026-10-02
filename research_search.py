"""Bounded source discovery. Search results are data, never tool instructions."""
from __future__ import annotations

import datetime as dt
import ipaddress
import os
import re
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests


TOPICS = {
    "healthcare": {
        "aliases": ["医药", "医疗", "医学", "制药", "药物", "medical", "healthcare", "clinical", "biomedical", "drug discovery"],
        "queries": ["healthcare agent", "drug discovery agent", "clinical workflow agent", "biomedical agent"],
        "terms": ["medical", "medicine", "healthcare", "health care", "clinical", "ehr", "patient", "biomedical", "drug", "pharma", "pharmaceutical", "pharmacology", "医药", "医疗"],
    },
    "coding": {
        "aliases": ["coding", "编程", "代码", "软件开发"],
        "queries": ["coding agent", "software engineering agent", "coding agent sandbox"],
        "terms": ["coding", "code", "software", "swe", "sandbox", "编程"],
    },
    "mcp": {
        "aliases": ["mcp", "model context protocol"],
        "queries": ["MCP agent tools", "model context protocol security", "MCP server integration"],
        "terms": ["mcp", "model context protocol"],
    },
    "multi_agent": {
        "aliases": ["multi-agent", "multiagent", "multi agent", "多智能体"],
        "queries": ["multi agent workflow", "multi agent orchestration", "multi agent evaluation"],
        "terms": ["multi-agent", "multiagent", "multi agent", "orchestration", "多智能体"],
    },
    "memory": {
        "aliases": ["memory", "记忆", "persistence", "checkpoint"],
        "queries": ["agent memory", "agent persistence checkpoint", "agent long term memory"],
        "terms": ["memory", "persistence", "checkpoint", "记忆"],
    },
    "rag": {
        "aliases": ["rag", "检索增强", "retrieval augmented"],
        "queries": ["agentic RAG", "agent retrieval reranking", "RAG evaluation agent"],
        "terms": ["rag", "retrieval", "rerank", "检索增强"],
    },
}
AGENT_TERMS = ["agent", "agents", "agentic", "mcp", "model context protocol", "智能体"]


def clean(value: Any, limit: int = 1600) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) else ""


def contains(text: str, term: str) -> bool:
    # Word boundaries avoid matches such as MCP in an unrelated identifier.
    if term.isascii():
        return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I))
    return term.lower() in text.lower()


@dataclass
class QueryPlan:
    original_query: str
    expanded_queries: list[str]
    topics: list[str]
    relevance_groups: list[list[str]]
    intent: str
    start_date: str
    end_date: str


def build_query_plan(query: str, today: dt.date, lookback_days: int = 30) -> QueryPlan:
    query = clean(query, 600)
    if not query:
        raise ValueError("query must not be empty")
    days = lookback_days
    if any(x in query for x in ("这周", "本周", "this week")):
        days = 7
    match = re.search(r"(?:过去|最近|近|past|last)\s*(\d+)\s*(天|周|个月|days?|weeks?|months?)", query, re.I)
    if match:
        count, unit = int(match[1]), match[2].lower()
        days = count * (30 if unit in ("个月", "month", "months") else 7 if unit in ("周", "week", "weeks") else 1)
    if not 1 <= days <= 365:
        raise ValueError("lookback must be between 1 and 365 days")
    topics = [name for name, spec in TOPICS.items() if any(contains(query, a) for a in spec["aliases"])]
    # Interleave topics so mixed-domain requests do not spend all slots on one topic.
    expanded = list(dict.fromkeys(TOPICS[name]["queries"][i] for i in range(4) for name in topics if i < len(TOPICS[name]["queries"])))
    if not expanded:
        expanded = [query]
    # Topic groups are OR alternatives for mixed-domain comparisons, plus an Agent anchor.
    domain_terms = list(dict.fromkeys(t for name in topics for t in TOPICS[name]["terms"]))
    groups = [AGENT_TERMS, domain_terms] if domain_terms else [AGENT_TERMS]
    intent = "comparison" if any(x in query for x in ("区别", "比较", "difference", "compare")) else "research"
    return QueryPlan(query, expanded, topics, groups, intent,
                     (today - dt.timedelta(days=days - 1)).isoformat(), today.isoformat())


def canonical_url(value: Any) -> str | None:
    """Public citation URLs only; canonicalize the same paper across HF/arXiv."""
    if not isinstance(value, str):
        return None
    try:
        p = urlsplit(value.strip())
        host = (p.hostname or "").lower().removeprefix("www.")
        if p.scheme not in ("http", "https") or not host or p.username or p.password or p.port not in (None, 80, 443):
            return None
        if host == "localhost" or host.endswith((".local", ".internal")) or "." not in host:
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        if host in ("arxiv.org", "export.arxiv.org", "huggingface.co"):
            m = re.fullmatch(r"/(?:abs|pdf|papers)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?", p.path)
            if m:
                return "https://arxiv.org/abs/" + m[1]
        query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")))
        return urlunsplit(("https", host, p.path.rstrip("/"), query, ""))
    except ValueError:
        return None


def parse_date(value: Any) -> dt.date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return parsedate_to_datetime(value).date()
        except (ValueError, TypeError, OverflowError):
            return None


@dataclass
class SearchBatch:
    items: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def rank_evidence(raw_items: list[dict[str, Any]], plan: QueryPlan, selected_urls: set[str], limit: int = 12) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rejected = {"invalid": 0, "duplicate": 0, "undated": 0, "out_of_window": 0, "irrelevant": 0}
    unique: dict[str, dict[str, Any]] = {}
    selected = {canonical_url(u) for u in selected_urls}
    start, end = dt.date.fromisoformat(plan.start_date), dt.date.fromisoformat(plan.end_date)
    for raw in raw_items:
        if not isinstance(raw, dict):
            rejected["invalid"] += 1
            continue
        url, title, summary = canonical_url(raw.get("url")), clean(raw.get("title"), 240), clean(raw.get("summary"), 1400)
        if not url or not title or not summary:
            rejected["invalid"] += 1
            continue
        date_kind = raw.get("date_kind", "published")
        date = parse_date(raw.get("date"))
        if date_kind not in ("published", "updated") or date is None:
            rejected["undated"] += 1
            continue
        if not start <= date <= end:
            rejected["out_of_window"] += 1
            continue
        text = title + " " + summary
        if not all(any(contains(text, t) for t in group) for group in plan.relevance_groups):
            rejected["irrelevant"] += 1
            continue
        if url in selected or url in unique:
            rejected["duplicate"] += 1
            continue
        score = sum(contains(text, term) for group in plan.relevance_groups for term in group)
        score += sum(contains(text, t) for t in ("workflow", "tool", "evaluation", "benchmark", "memory", "sandbox", "implementation")) * 0.25
        score += (date - start).days / max((end - start).days + 1, 1)
        unique[url] = {"title": title, "url": url, "summary": summary, "date": date.isoformat(),
                       "date_kind": date_kind, "provider": clean(raw.get("provider"), 40),
                       "evidence_kind": clean(raw.get("evidence_kind"), 40), "retrieved_query": clean(raw.get("retrieved_query"), 160),
                       "relevance_score": round(score, 3)}
    rejected["over_limit"] = max(0, len(unique) - limit)
    return sorted(unique.values(), key=lambda x: x["relevance_score"], reverse=True)[:limit], rejected


class EvidenceSearch:
    """Fixed API endpoints; shared run budget, timeouts and repeated-call suppression."""

    def __init__(self, config: dict[str, Any], session: Any = None):
        cfg = config.get("learning_agent", {}).get("search", {})
        self.providers = cfg.get("providers", ["hf", "github", "arxiv", "tavily"])
        if not isinstance(self.providers, list) or not self.providers or any(p not in ("hf", "arxiv", "github", "tavily") for p in self.providers):
            raise ValueError("providers must contain hf, arxiv, github or tavily")
        self.providers = list(dict.fromkeys(self.providers))
        self.max_calls = self._bound(cfg.get("max_calls", 8), 1, 12)
        self.max_queries = self._bound(cfg.get("max_queries", 4), 1, 5)
        self.results_per_query = self._bound(cfg.get("results_per_query", 6), 1, 10)
        self.hf_candidates = self._bound(cfg.get("hf_candidates", 40), 1, 60)
        self.timeout = self._bound(cfg.get("timeout_seconds", 12), 1, 30)
        self.session = session or requests.Session()
        self.used_calls = 0
        self.executed: set[tuple[str, str]] = set()
        self.disabled: set[str] = set()
        self.last_arxiv_call = 0.0

    @staticmethod
    def _bound(value: Any, low: int, high: int) -> int:
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"search limit must be an integer between {low} and {high}")
        return value

    def search(self, plan: QueryPlan, queries: list[str], selected_urls: set[str]) -> SearchBatch:
        batch, raw_items = SearchBatch(), []
        queries = list(dict.fromkeys(clean(q, 160) for q in queries if clean(q, 160)))[:self.max_queries]
        for query in queries:
            for provider in self.providers:
                record = {"provider": provider, "query": query, "start_date": plan.start_date, "end_date": plan.end_date}
                if provider == "tavily" and not os.environ.get("TAVILY_API_KEY"):
                    record["status"] = "unconfigured"
                    batch.trace.append(record)
                    batch.warnings.append("Tavily 未配置；本轮仅覆盖可用的论文/开源项目源。")
                    continue
                if provider in self.disabled:
                    record["status"] = "isolated_after_error"
                    batch.trace.append(record)
                    continue
                if (provider, query.casefold()) in self.executed:
                    record["status"] = "repeated_query_skipped"
                    batch.trace.append(record)
                    continue
                if self.used_calls >= self.max_calls:
                    record["status"] = "budget_exhausted"
                    batch.trace.append(record)
                    continue
                self.used_calls += 1
                self.executed.add((provider, query.casefold()))
                started = time.monotonic()
                try:
                    items = getattr(self, "_search_" + provider)(query, plan)
                    for item in items:
                        item["retrieved_query"] = query
                    raw_items.extend(items)
                    record.update(status="ok", retrieved=len(items))
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    # Exception messages may contain request headers or credentials.
                    record.update(status="error", error_type=type(exc).__name__)
                    batch.warnings.append(f"{provider} 检索失败；本轮来源覆盖不完整。")
                    # A failing provider is isolated for this run; no hidden retries.
                    self.disabled.add(provider)
                record["latency_ms"] = round((time.monotonic() - started) * 1000)
                batch.trace.append(record)
        batch.items, rejected = rank_evidence(raw_items, plan, selected_urls, limit=max(0, 12 - len(selected_urls)))
        batch.trace.append({"stage": "filter", "retrieved": len(raw_items), "selected": len(batch.items), "rejected": rejected, "used_calls": self.used_calls})
        if batch.items and sum(i["date_kind"] == "published" for i in batch.items) < 2:
            batch.warnings.append("本轮发布日期证据少于两条；仓库更新只能作为活跃信号，无法据此确认行业趋势。")
        batch.warnings = list(dict.fromkeys(batch.warnings))
        return batch

    def _search_hf(self, query: str, plan: QueryPlan) -> list[dict[str, Any]]:
        response = self.session.get("https://huggingface.co/api/papers/search", params={
            "q": query, "limit": self.hf_candidates,
        }, headers={"User-Agent": "ai-agent-radar/2.1"}, timeout=self.timeout)
        response.raise_for_status()
        result = []
        for row in response.json():
            paper = row.get("paper", row)
            paper_id = str(paper.get("id", ""))
            if not re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", paper_id):
                continue
            # Wrapper dates can be HF submission dates; use paper publication date.
            result.append({"title": paper.get("title"), "url": f"https://arxiv.org/abs/{paper_id}",
                           "summary": paper.get("summary"), "date": paper.get("publishedAt"),
                           "date_kind": "published", "provider": "hf", "evidence_kind": "abstract"})
        return result

    def _search_arxiv(self, query: str, plan: QueryPlan) -> list[dict[str, Any]]:
        # arXiv asks clients to leave at least three seconds between calls.
        gap = 3 - (time.monotonic() - self.last_arxiv_call)
        if gap > 0:
            time.sleep(gap)
        tokens = re.findall(r"[\w-]+", query)[:12]
        terms = " AND ".join('all:"' + t + '"' for t in tokens)
        start, end = plan.start_date.replace("-", ""), plan.end_date.replace("-", "")
        self.last_arxiv_call = time.monotonic()
        response = self.session.get("https://export.arxiv.org/api/query", params={
            "search_query": f"({terms}) AND submittedDate:[{start}0000 TO {end}2359]",
            "start": 0, "max_results": self.results_per_query, "sortBy": "submittedDate", "sortOrder": "descending",
        }, headers={"User-Agent": "ai-agent-radar/2.1"}, timeout=self.timeout)
        response.raise_for_status()
        feed = feedparser.parse(response.text)
        if feed.bozo or any("/api/errors" in e.get("id", "") for e in feed.entries):
            raise ValueError("invalid arXiv response")
        return [{"title": e.get("title"), "url": e.get("id"), "summary": e.get("summary"),
                 "date": e.get("published"), "date_kind": "published", "provider": "arxiv", "evidence_kind": "abstract"} for e in feed.entries]

    def _search_github(self, query: str, plan: QueryPlan) -> list[dict[str, Any]]:
        terms = " ".join('"' + t + '"' for t in re.findall(r"[\w-]+", query)[:12])
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ai-agent-radar/2.1", "X-GitHub-Api-Version": "2022-11-28"}
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
        response = self.session.get("https://api.github.com/search/repositories", params={
            "q": f"{terms} in:name,description pushed:{plan.start_date}..{plan.end_date} fork:false archived:false",
            "sort": "stars", "order": "desc", "per_page": self.results_per_query,
        }, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if data.get("incomplete_results"):
            raise ValueError("incomplete GitHub search")
        return [{"title": r.get("full_name"), "url": r.get("html_url"), "summary": r.get("description"),
                 "date": r.get("pushed_at"), "date_kind": "updated", "provider": "github", "evidence_kind": "repository_metadata"}
                for r in data["items"] if not r.get("fork") and not r.get("archived")
                and len(str(r.get("full_name", "")).split("/")) == 2
                and r["full_name"].split("/")[0].casefold() != r["full_name"].split("/")[1].casefold()]

    def _search_tavily(self, query: str, plan: QueryPlan) -> list[dict[str, Any]]:
        response = self.session.post("https://api.tavily.com/search", headers={
            "Authorization": "Bearer " + os.environ["TAVILY_API_KEY"], "Content-Type": "application/json",
        }, json={"query": query, "search_depth": "basic", "topic": "general",
                 "start_date": plan.start_date, "end_date": plan.end_date,
                 "include_published_date": True, "filter_by_published_date": True,
                 "max_results": self.results_per_query, "include_answer": False,
                 "include_raw_content": False}, timeout=self.timeout)
        response.raise_for_status()
        return [{"title": r.get("title"), "url": r.get("url"), "summary": r.get("content"),
                 "date": r.get("published_date"), "date_kind": "published", "provider": "tavily", "evidence_kind": "search_excerpt"}
                for r in response.json()["results"]]
