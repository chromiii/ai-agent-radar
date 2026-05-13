from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
from pathlib import Path
from typing import Any

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
STATE_PATH = ROOT / "state.json"
TRENDING_TERMS_PATH = ROOT / "state" / "trending_terms.json"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"seen": []}
    with STATE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict[str, Any]) -> None:
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_trending_terms() -> dict[str, Any]:
    if not TRENDING_TERMS_PATH.exists():
        return {"tier1": [], "tier2": [], "terms": []}
    try:
        with TRENDING_TERMS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"Failed to load weekly trending terms; continuing without trend boost. Error: {exc}")
        return {"tier1": [], "tier2": [], "terms": []}


def today_local() -> dt.date:
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(load_config().get("timezone", "UTC"))
        return dt.datetime.now(tz).date()
    except Exception:
        return dt.date.today()


def get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    headers = {"User-Agent": "ai-agent-radar/0.3"}
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_text(url: str, params: dict[str, Any] | None = None) -> str:
    headers = {"User-Agent": "ai-agent-radar/0.3"}
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def normalize(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def canonical_paper_id(item: dict[str, Any]) -> str | None:
    # HF Papers and arXiv often expose the same paper through different URLs.
    # Normalize by arXiv id so one paper does not consume multiple AI slots.
    candidates = [
        str(item.get("paper_id") or ""),
        str(item.get("arxiv_id") or ""),
        str(item.get("url") or ""),
        str(item.get("summary") or ""),
        str(item.get("title") or ""),
    ]
    text = " ".join(candidates)
    match = re.search(r"(?<!\d)(\d{4}\.\d{4,5})(?:v\d+)?(?!\d)", text)
    if match:
        return f"paper::{match.group(1)}"
    return None


def item_id(item: dict[str, Any]) -> str:
    paper_id = canonical_paper_id(item)
    if paper_id:
        return paper_id
    return f"{item.get('source')}::{item.get('url') or item.get('title')}"


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for item in items:
        key = item_id(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def apply_weekly_trend_boost(text: str, config: dict[str, Any], trends: dict[str, Any], reasons: list[str]) -> float:
    trend_config = config.get("ranking", {}).get("weekly_trend_boost", {})
    if not trend_config.get("enabled", True):
        return 0.0

    max_total = float(trend_config.get("max_total", 4.0))
    generic_terms = {"agent", "agents", "ai", "model", "models", "benchmark", "framework"}
    boost = 0.0

    for tier_name, default_weight in (("tier1", 2.0), ("tier2", 1.0)):
        weight = float(trend_config.get(tier_name, default_weight))
        for term in trends.get(tier_name, []):
            term_l = str(term).lower()
            if term_l in generic_terms:
                continue
            if term_l in text and boost < max_total:
                add = min(weight, max_total - boost)
                boost += add
                reasons.append(f"weekly-trend {tier_name}: {term}")
    return boost


def apply_weekly_trend_penalty(text: str, trends: dict[str, Any], reasons: list[str]) -> float:
    # Weekly trend curation may flag noisy phrases. Keep protected domain terms
    # from being accidentally penalized just because they appeared in downrank.
    protected_terms = {
        "agentic search",
        "computer use",
        "computer use agent",
        "coding agent",
        "browser automation",
        "mobile agent",
        "research agent",
        "agent memory",
        "agentic workflow",
        "gui agent",
        "swe-bench",
        "osworld",
        "gaia",
        "manus",
        "deepseek",
        "qwen",
        "kimi",
        "glm",
        "doubao",
        "hunyuan",
    }
    penalty = 0.0
    for term in trends.get("downrank", []):
        term_l = str(term).lower().strip()
        if not term_l or term_l in protected_terms:
            continue
        if term_l in text:
            penalty += 1.0
            reasons.append(f"weekly-downrank: {term}")
    return min(penalty, 3.0)


def score_item(item: dict[str, Any], config: dict[str, Any], trends: dict[str, Any] | None = None) -> tuple[float, list[str]]:
    text = f"{normalize(item.get('title')).lower()} {normalize(item.get('summary')).lower()}"
    score = 0.0
    reasons: list[str] = []

    for kw in config.get("keywords", []):
        if kw.lower() in text:
            score += 1.2
            reasons.append(f"keyword: {kw}")

    for term in config.get("high_value_terms", []):
        if term.lower() in text:
            score += 1.8
            reasons.append(f"high-value: {term}")

    for term in config.get("ranking", {}).get("downrank_terms", []):
        if term.lower() in text:
            score -= 1.5
            reasons.append(f"downrank: {term}")

    score += apply_weekly_trend_boost(text, config, trends or {}, reasons)
    score -= apply_weekly_trend_penalty(text, trends or {}, reasons)

    source_bonus = {
        "hf_daily_papers": (2.5, "appeared on HF Daily Papers"),
        "hf_space": (1.8, "Hugging Face Space"),
        "hf_competition": (2.0, "Hugging Face competition"),
        "arxiv": (1.0, "new arXiv paper"),
    }
    bonus = source_bonus.get(item.get("source", ""))
    if bonus:
        score += bonus[0]
        reasons.append(bonus[1])

    likes = item.get("likes") or 0
    downloads = item.get("downloads") or 0
    cited_by = item.get("cited_by_count") or 0
    if likes:
        score += min(float(likes) / 50.0, 2.0)
        reasons.append(f"HF likes: {likes}")
    if downloads:
        score += min(float(downloads) / 10000.0, 2.0)
        reasons.append(f"HF downloads: {downloads}")
    if cited_by:
        score += min(float(cited_by) / 25.0, 2.0)
        reasons.append(f"OpenAlex citations: {cited_by}")

    # Preserve raw_score for sorting, but compress the displayed score so the
    # report does not become a wall of 10/10 items.
    item["raw_score"] = round(max(0.0, score), 2)
    display_score = max(0.0, min(item["raw_score"] * 0.72, 10.0))
    return round(display_score, 1), reasons[:6]


def compact_for_ai(item: dict[str, Any], max_summary_chars: int) -> dict[str, Any]:
    summary = normalize(item.get("summary"))
    if len(summary) > max_summary_chars:
        summary = summary[:max_summary_chars].rsplit(" ", 1)[0] + "..."
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "source": item.get("source"),
        "url": item.get("url"),
        "score": item.get("score"),
        "raw_score": item.get("raw_score"),
        "reasons": item.get("reasons", []),
        "authors": item.get("authors"),
        "published": item.get("published"),
        "summary": summary,
    }


def parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def build_daily_classifier_prompt(day: dt.date, items: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, str]]:
    ai_config = config.get("ai", {})
    compact_items = [
        compact_for_ai(item, int(ai_config.get("max_summary_chars_per_item", 1200)))
        for item in items[: int(ai_config.get("max_items", 15))]
    ]
    system = (
        "You are a strict classifier for daily AI agent and multi-agent research radar items. "
        "Return valid JSON only. Use only supplied item ids. "
        "Do not invent papers, links, authors, dates, metrics, claims, or ids."
    )
    user = f"""
Classify today's candidate items for an AI agent / AI application research radar.

Date: {day.isoformat()}

Class definitions:
- must_read: High-value item worth reading today. It should be clearly related to AI agents, AI applications, benchmarks, coding agents, computer-use agents, tool use, memory, evaluation, or multi-agent systems.
- scan: Relevant item worth a quick look, but not urgent or evidence is narrower.
- skip: Low-value, weakly related, generic, marketing-like, duplicated, or evidence-insufficient item.
- HF Spaces, leaderboards, demos, and project pages should usually be scan unless they include strong evidence of a new capability, benchmark, or release.

Few-shot examples:
- ToolCUA / computer-use agent benchmark -> must_read
- New agentic search paper with retrieval + tool use -> must_read
- Generic planning paper without clear agent evaluation -> scan
- Prompt collection or generic tutorial -> skip
- Space/demo with no description or weak evidence -> scan or skip

Output valid JSON only. Do not output Markdown.

JSON schema:
{{
  "must_read": ["item_1", "item_3"],
  "scan": ["item_4"],
  "skip": ["item_7"],
  "notes": {{
    "item_1": "40字内中文理由",
    "item_3": "40字内中文理由"
  }},
  "background": "80字内中文基础知识"
}}

Rules:
- must_read max 5 ids.
- scan max 8 ids.
- skip max 10 ids.
- notes values must be Simplified Chinese, max 40 Chinese characters.
- background must be Simplified Chinese, max 80 Chinese characters.
- Every id must exactly match an input item id.
- If evidence is weak, use scan or skip; do not put weak items in must_read.
- Do not put items with little or no summary into must_read.

Candidate items JSON:
{json.dumps(compact_items, ensure_ascii=False, indent=2)}
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def normalize_id_list(value: Any, allowed_ids: set[str], limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for entry in value:
        item_id_value = entry.get("id") if isinstance(entry, dict) else entry
        if not isinstance(item_id_value, str):
            continue
        if item_id_value in allowed_ids and item_id_value not in result:
            result.append(item_id_value)
        if len(result) >= limit:
            break
    return result


def eligible_for_must_read(item: dict[str, Any]) -> bool:
    source = item.get("source")
    summary = normalize(item.get("summary"))
    if source == "hf_space":
        return False
    if source in {"hf_daily_papers", "arxiv"}:
        return len(summary) >= 120
    return len(summary) >= 80


def validate_daily_classification(curated: dict[str, Any] | None, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(curated, dict):
        return None
    allowed_ids = {item["id"] for item in items if item.get("id")}
    by_id = {item["id"]: item for item in items if item.get("id")}
    # The model can nominate weak HF Spaces as must-read; enforce evidence
    # gates in code before rendering or sending anything onward.
    requested_must_read = normalize_id_list(curated.get("must_read"), allowed_ids, 5)
    must_read = [item_id for item_id in requested_must_read if eligible_for_must_read(by_id[item_id])]
    demoted_to_scan = [item_id for item_id in requested_must_read if item_id not in must_read]
    scan = [
        item_id
        for item_id in demoted_to_scan + normalize_id_list(curated.get("scan"), allowed_ids, 8)
        if item_id not in must_read
    ][:8]
    skip = [
        item_id
        for item_id in normalize_id_list(curated.get("skip"), allowed_ids, 10)
        if item_id not in must_read and item_id not in scan
    ]
    notes = {}
    raw_notes = curated.get("notes", {})
    if isinstance(raw_notes, dict):
        for key, value in raw_notes.items():
            if key in allowed_ids and isinstance(value, str):
                notes[key] = value[:100]
    background = curated.get("background", "")
    if not isinstance(background, str):
        background = ""
    if not must_read and not scan:
        return None
    return {"must_read": must_read, "scan": scan, "skip": skip, "notes": notes, "background": background[:160]}


def call_deepseek(day: dt.date, items: list[dict[str, Any]], config: dict[str, Any]) -> str | None:
    ai_config = config.get("ai", {})
    if not ai_config.get("enabled", False) or ai_config.get("provider") != "deepseek" or not items:
        return None

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY is not set; using rule-based Markdown.")
        return None

    base_url = str(ai_config.get("base_url", "https://api.deepseek.com")).rstrip("/")
    payload = {
        "model": ai_config.get("model", "deepseek-v4-flash"),
        "messages": build_daily_classifier_prompt(day, items, config),
        "temperature": 0.1,
        "max_tokens": int(ai_config.get("max_tokens_daily", 3500)),
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "ai-agent-radar/0.3",
    }

    try:
        response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        parsed = parse_json_object(content)
        if parsed is None:
            print("DeepSeek daily JSON parse failed. Response head:")
            print(content[:1200])
            return None
        curated = validate_daily_classification(parsed, items)
        if curated is None:
            print("DeepSeek daily JSON validation failed.")
            return None
        return render_ai_daily_markdown(day, items, curated)
    except Exception as exc:
        print(f"DeepSeek call failed; using rule-based Markdown. Error: {exc}")
        return None


def fetch_hf_daily_papers_for_day(config: dict[str, Any], day: dt.date) -> list[dict[str, Any]]:
    data = get_json("https://huggingface.co/api/daily_papers", {"date": day.isoformat()})
    papers = data if isinstance(data, list) else data.get("papers", [])
    items = []
    for p in papers[: config["max_items_per_source"]]:
        paper = p.get("paper") if isinstance(p, dict) and "paper" in p else p
        title = normalize(paper.get("title") or paper.get("paperTitle"))
        paper_id = paper.get("id") or paper.get("arxivId") or paper.get("paperId")
        summary = normalize(paper.get("summary") or paper.get("abstract"))
        if not title:
            continue
        url = f"https://huggingface.co/papers/{paper_id}" if paper_id else "https://huggingface.co/papers"
        items.append(
            {
                "source": "hf_daily_papers",
                "title": title,
                "summary": summary,
                "url": url,
                "paper_id": paper_id,
                "published": day.isoformat(),
            }
        )
    return items


def fetch_hf_daily_papers(config: dict[str, Any], day: dt.date) -> list[dict[str, Any]]:
    # HF daily papers can lag behind Sydney midnight. Fall back a few days
    # instead of producing an empty report.
    fallback_days = int(config.get("hf_daily_fallback_days", 3))
    last_error: Exception | None = None
    for offset in range(fallback_days + 1):
        target_day = day - dt.timedelta(days=offset)
        try:
            items = fetch_hf_daily_papers_for_day(config, target_day)
            if items:
                if offset:
                    print(f"HF daily papers used fallback date {target_day.isoformat()} because {day.isoformat()} was unavailable or empty.")
                    for item in items:
                        item["fallback_from"] = day.isoformat()
                return items
            print(f"HF daily papers returned no items for {target_day.isoformat()}; trying previous day.")
        except Exception as exc:
            last_error = exc
            print(f"HF daily papers failed for {target_day.isoformat()}: {exc}")
    if last_error:
        print(f"HF daily papers unavailable after {fallback_days + 1} attempts; continuing without it.")
    return []


def is_quality_hf_space(space: dict[str, Any], sid: str, summary: str, config: dict[str, Any]) -> bool:
    sid_l = sid.lower()
    summary_l = summary.lower()
    likes = int(space.get("likes") or 0)
    downloads = int(space.get("downloads") or 0)
    min_likes = int(config.get("hf_space_min_likes", 2))
    min_downloads = int(config.get("hf_space_min_downloads", 50))

    always_keep_terms = ("leaderboard", "benchmark", "gaia", "swe-bench", "osworld", "webarena")
    if any(term in sid_l or term in summary_l for term in always_keep_terms):
        return True

    if not summary or len(summary) < 12:
        return False

    owner = sid.split("/", 1)[0].lower()
    if re.search(r"\d{3,}", owner) or re.search(r"(.)\1{3,}", owner):
        return False

    if likes >= min_likes or downloads >= min_downloads:
        return True

    strong_terms = ("computer-use", "computer use", "coding-agent", "coding agent", "agentic", "multi-agent")
    return any(term in sid_l or term in summary_l for term in strong_terms)


def fetch_hf_spaces(config: dict[str, Any]) -> list[dict[str, Any]]:
    queries = config.get("search", {}).get(
        "hf_space_queries",
        ["agent leaderboard", "multi-agent benchmark", "web agent", "agent challenge"],
    )
    items: list[dict[str, Any]] = []
    for query in queries:
        try:
            data = get_json(
                "https://huggingface.co/api/spaces",
                {"search": query, "sort": "lastModified", "direction": "-1", "limit": 8, "full": "true"},
            )
        except Exception:
            continue
        for space in data if isinstance(data, list) else []:
            sid = space.get("id")
            if not sid:
                continue
            card_data = space.get("cardData") if isinstance(space.get("cardData"), dict) else {}
            summary = normalize(
                card_data.get("title")
                or card_data.get("short_description")
                or card_data.get("description")
                or space.get("description")
            )
            if not is_quality_hf_space(space, sid, summary, config):
                continue
            items.append(
                {
                    "source": "hf_space",
                    "title": sid,
                    "summary": summary,
                    "url": f"https://huggingface.co/spaces/{sid}",
                    "likes": space.get("likes"),
                    "downloads": space.get("downloads"),
                }
            )
    return dedupe(items)


def fetch_hf_competitions(config: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        text = get_text("https://huggingface.co/competitions")
    except Exception:
        return []
    soup = BeautifulSoup(text, "html.parser")
    items: list[dict[str, Any]] = []
    for row in soup.find_all("tr")[1 : config["max_items_per_source"] + 1]:
        cells = [normalize(c.get_text(" ")) for c in row.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        title = cells[0]
        summary = " | ".join(cells[1:])
        if any(kw.lower() in f"{title} {summary}".lower() for kw in config.get("keywords", [])):
            items.append({"source": "hf_competition", "title": title, "summary": summary, "url": "https://huggingface.co/competitions"})
    return items


def fetch_arxiv(config: dict[str, Any]) -> list[dict[str, Any]]:
    keywords = config.get("keywords", [])
    categories = config.get("arxiv_categories", [])
    kw = " OR ".join([f'all:"{k}"' if " " in k else f"all:{k}" for k in keywords])
    cats = " OR ".join([f"cat:{c}" for c in categories])
    params = {
        "search_query": f"({kw}) AND ({cats})",
        "start": 0,
        "max_results": config["max_items_per_source"],
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    feed = feedparser.parse(get_text("https://export.arxiv.org/api/query", params))
    return [
        {
            "source": "arxiv",
            "title": normalize(entry.get("title")),
            "summary": normalize(entry.get("summary")),
            "url": entry.get("link"),
            "paper_id": canonical_paper_id({"url": entry.get("link"), "title": entry.get("title")}),
            "published": entry.get("published"),
            "authors": ", ".join(author.get("name", "") for author in entry.get("authors", [])),
        }
        for entry in feed.entries
    ]


def enrich_with_openalex(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in items:
        if item.get("source") != "arxiv" or not item.get("title"):
            continue
        try:
            data = get_json("https://api.openalex.org/works", {"search": item["title"], "per-page": 1})
            results = data.get("results", [])
            if results:
                item["cited_by_count"] = results[0].get("cited_by_count", 0)
                item["openalex_url"] = results[0].get("id")
        except Exception:
            pass
    return items


def render_markdown(day: dt.date, items: list[dict[str, Any]]) -> str:
    lines = [f"# AI Agent Radar - {day.isoformat()}", "", "## Today worth checking", ""]
    if not items:
        return "\n".join(lines + ["No matching items found today.", ""])

    for idx, item in enumerate(items, 1):
        lines.extend(
            [
                f"### {idx}. {item['title']}",
                f"- Score: {item['score']}/10",
                f"- Source: {item['source']}",
                f"- Link: {item['url']}",
            ]
        )
        if item.get("authors"):
            lines.insert(-1, f"- Authors: {item['authors']}")
        if item.get("reasons"):
            lines.append(f"- Why: {', '.join(item['reasons'])}")
        if item.get("summary"):
            summary = item["summary"]
            if len(summary) > 700:
                summary = summary[:700].rsplit(" ", 1)[0] + "..."
            lines.extend(["", summary])
        lines.append("")

    lines.extend(
        [
            "## Follow-up",
            "",
            "- [ ] Open the top 3 links",
            "- [ ] Save any strong benchmark or leaderboard to the long-term watch list",
            "- [ ] Mark papers worth reading deeply",
            "",
        ]
    )
    lines.extend(
        [
            "## 发给 ChatGPT 的精读请求",
            "",
            "请基于上面的 AI Agent Radar 帮我做二次精读：",
            "1. 选出今天最值得关注的 3 条，并说明原因。",
            "2. 对每条解释它解决的问题、核心创新和实际价值。",
            "3. 标出证据不足、可能 hype 或只是关键词相关的内容。",
            "4. 告诉我每条应该深读、收藏、扫一眼还是跳过。",
            "5. 补充我理解这些内容需要知道的背景知识。",
            "",
        ]
    )
    return "\n".join(lines)


def render_item_block(item: dict[str, Any], note: str | None = None) -> list[str]:
    lines = [f"### {item['title']}"]
    lines.append(f"- 来源：{item.get('source')}")
    if item.get("authors"):
        lines.append(f"- 作者：{item.get('authors')}")
    if item.get("published"):
        lines.append(f"- 日期：{item.get('published')}")
    lines.append(f"- 链接：{item.get('url')}")
    lines.append(f"- 规则分：{item.get('score')}/10")
    if item.get("raw_score") is not None:
        lines.append(f"- 原始分：{item.get('raw_score')}")
    if item.get("reasons"):
        lines.append(f"- 规则命中：{', '.join(item.get('reasons', []))}")
    if note:
        lines.append(f"- AI 判断：{note}")
    return lines


def render_index_item(idx: int, item: dict[str, Any], note: str | None = None) -> list[str]:
    title = item.get("title") or "Untitled"
    url = item.get("url") or ""
    if url:
        lines = [f"{idx}. [{title}]({url})"]
    else:
        lines = [f"{idx}. {title}"]
    lines.append(f"   - 来源：{item.get('source')}")
    if item.get("published"):
        lines.append(f"   - 日期：{item.get('published')}")
    if note:
        lines.append(f"   - 判断：{note}")
    else:
        lines.append("   - 判断：值得优先查看")
    return lines


def render_ai_daily_markdown(
    day: dt.date,
    items: list[dict[str, Any]],
    curated: dict[str, Any],
) -> str:
    by_id = {item["id"]: item for item in items}
    notes = curated.get("notes", {})
    must_read = [by_id[item_id] for item_id in curated.get("must_read", []) if item_id in by_id]
    scan = [by_id[item_id] for item_id in curated.get("scan", []) if item_id in by_id]
    skip = [by_id[item_id] for item_id in curated.get("skip", []) if item_id in by_id]

    lines = [
        f"# AI Agent Radar - {day.isoformat()}",
        "",
        "## 今日结论",
        "",
    ]
    if must_read:
        lines.append(f"今日有 {len(must_read)} 个高价值 agent / AI 应用相关条目，优先查看必看索引。")
    else:
        lines.append("今天高价值新增内容较少，可以快速扫一眼相关条目。")
    lines.append("")

    lines.extend(["## 必看索引", ""])
    if must_read:
        for idx, item in enumerate(must_read, 1):
            lines.extend(render_index_item(idx, item, notes.get(item["id"])))
            lines.append("")
    else:
        lines.append("暂无明确必看条目。")
        lines.append("")

    lines.extend(["## 值得扫一眼", ""])
    if scan:
        for item in scan:
            lines.extend(render_item_block(item, notes.get(item["id"])))
            lines.append("")
    else:
        lines.append("暂无。")
        lines.append("")

    lines.extend(["## 低优先级或可跳过", ""])
    if skip:
        for item in skip:
            lines.append(f"- {item['title']}：{notes.get(item['id'], '相关性或证据不足')}")
    else:
        lines.append("暂无。")
    lines.append("")

    lines.extend(
        [
            "## 你需要知道的基础知识",
            "",
            curated.get("background") or "暂无需要额外补充的基础知识。",
            "",
            "## 后续行动",
            "",
            "- [ ] 打开必看条目的原文链接",
            "- [ ] 判断是否加入长期关注 benchmark / leaderboard 列表",
            "- [ ] 将有复现价值的代码或 Space 单独收藏",
            "",
        ]
    )
    return "\n".join(lines)


def append_chatgpt_request(markdown: str) -> str:
    if "## 发给 ChatGPT 的精读请求" in markdown:
        return markdown
    prompt = """

## 发给 ChatGPT 的精读请求

请基于上面的简报帮我做二次精读：
1. 选出今天最值得关注的 3 条，并说明原因。
2. 对每条解释它解决的问题、核心创新和实际价值。
3. 标出证据不足、可能 hype 或只是关键词相关的内容。
4. 告诉我每条应该深读、收藏、扫一眼还是跳过。
5. 补充我理解这些内容需要知道的背景知识。
""".rstrip()
    return markdown.rstrip() + prompt + "\n"


def collect_items(config: dict[str, Any], day: dt.date) -> list[dict[str, Any]]:
    items = []
    for fetcher in [fetch_hf_daily_papers, fetch_hf_spaces, fetch_hf_competitions, fetch_arxiv]:
        try:
            if fetcher is fetch_hf_daily_papers:
                items.extend(fetcher(config, day))
            else:
                items.extend(fetcher(config))
        except Exception as exc:
            print(f"{fetcher.__name__} failed: {exc}")
    return enrich_with_openalex(dedupe(items))


def main() -> None:
    config = load_config()
    day = today_local()
    state = load_state()
    trends = load_trending_terms()
    seen = set(state.get("seen", []))

    fresh = [item for item in collect_items(config, day) if item_id(item) not in seen]
    for item in fresh:
        item["score"], item["reasons"] = score_item(item, config, trends)

    fresh.sort(key=lambda x: x.get("raw_score", x.get("score", 0)), reverse=True)
    digest_items = fresh[: config["max_digest_items"]]
    for idx, item in enumerate(digest_items, 1):
        item["id"] = f"item_{idx}"

    output_dir = ROOT / config["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{day.isoformat()}.md"

    if not digest_items:
        if output_path.exists():
            print(f"No new items; keeping existing {output_path}")
        else:
            print(f"No new items; not writing empty report for {day.isoformat()}")
        save_state(state)
        return

    ai_markdown = call_deepseek(day, digest_items, config)
    output_path.write_text(append_chatgpt_request(ai_markdown or render_markdown(day, digest_items)), encoding="utf-8")

    # Only mark items as seen after a report was actually written. Failed or
    # empty runs should not burn future reruns.
    state["seen"] = sorted(seen | {item_id(item) for item in digest_items if item.get("url")})[-2000:]
    save_state(state)
    print(f"Wrote {output_path} with {len(digest_items)} items")


if __name__ == "__main__":
    main()



