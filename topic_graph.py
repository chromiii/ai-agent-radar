"""Ground the weekly topic graph in Radar's existing evidence and reports."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from breaking_news import normalized_news_url
from historical_memory import DATE_NAME, MD_LINK
from radar_feed import Event
from research_search import clean, parse_date

MAX_TOPICS = 6
MAX_SUBTOPICS = 4
MAX_SOURCES = 4


def rows(value: Any) -> list:
    return value if isinstance(value, list) else []


def source_record(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    url = value.get('url')
    title = clean(value.get('title'), 220)
    if not isinstance(url, str) or not title or not normalized_news_url(url):
        return None
    result = {'title': title, 'url': url}
    for field in ('published', 'observed_at'):
        date = parse_date(value.get(field))
        if date:
            result[field] = date.isoformat()
    summary = clean(value.get('summary'), 260)
    if summary:
        result['summary'] = summary
    return result


def validate_topic_graph(value: Any, allowed_terms: set[str], evidence: list[dict]) -> list[dict]:
    """Resolve evidence IDs against the exact items supplied to the model."""
    topics = []
    seen_terms: set[str] = set()
    for topic in rows(value):
        if not isinstance(topic, dict):
            continue
        term = clean(topic.get('term'), 80).lower()
        label = clean(topic.get('label'), 44)
        if term not in allowed_terms or term in seen_terms or not label:
            continue
        children = []
        seen_labels: set[str] = set()
        for child in rows(topic.get('children')):
            if not isinstance(child, dict):
                continue
            name = clean(child.get('label'), 44)
            if not name or name.lower() in (label.lower(), term, *seen_labels):
                continue
            sources = {}
            for index in rows(child.get('evidence_ids')):
                if type(index) is not int or not 1 <= index <= len(evidence):
                    continue
                source = source_record(evidence[index - 1])
                if source:
                    sources.setdefault(normalized_news_url(source['url']), source)
                if len(sources) >= MAX_SOURCES:
                    break
            if sources:
                children.append({'label': name, 'sources': list(sources.values())})
                seen_labels.add(name.lower())
            if len(children) >= MAX_SUBTOPICS:
                break
        if children:
            topics.append({'term': term, 'label': label, 'children': children})
            seen_terms.add(term)
        if len(topics) >= MAX_TOPICS:
            break
    return topics


def legacy_graph(root: Path, generated_at: str, state: dict, curated: dict, events: list[Event]) -> list[dict]:
    """Reuse AI-selected terms/cards with evidence from old weekly snapshots."""
    matches: dict[str, dict[str, dict]] = {}
    report = root / 'weekly' / f'{generated_at}.md'
    if report.exists():
        _, _, section = report.read_text(encoding='utf-8').partition('## 代表性内容\n')
        source = None
        for raw in section.splitlines():
            line = raw.strip()
            if line.startswith('## '):
                break
            link = MD_LINK.match(line[2:]) if line.startswith('- [') else None
            if link:
                source = source_record({'title': link[1], 'url': link[2], 'observed_at': generated_at})
            elif source and '命中词：' in line:
                for term in line.split('命中词：', 1)[1].lower().split(','):
                    matches.setdefault(term.strip(), {})[normalized_news_url(source['url'])] = source
    topics = []
    tier1 = [term for term in rows(state.get('tier1')) if isinstance(term, str)]
    tier2 = [term for term in rows(state.get('tier2')) if isinstance(term, str)]
    cards = [card for card in rows(curated.get('learning_cards')) if isinstance(card, dict)]
    for term in (tier1 or tier2)[:MAX_TOPICS]:
        matched = dict(matches.get(term.lower(), {}))
        needle = re.escape(re.sub(r'[-\s]+', ' ', term.lower().strip()))
        for event in events:
            text = re.sub(r'[-\s]+', ' ', f'{event.title} {event.summary}'.lower())
            if needle and re.search(r'(?<![a-z0-9])' + needle + r'(?:s(?![a-z0-9])|(?![a-z0-9]))', text):
                url = event.urls[0]
                matched.setdefault(normalized_news_url(url), {
                    'title': event.title, 'url': url, 'observed_at': event.first_seen,
                })
        if not matched:
            continue
        children = []
        covered: set[str] = set()
        for card in cards:
            name = clean(card.get('title'), 44)
            keys = list(dict.fromkeys(normalized_news_url(url) for url in rows(card.get('source_urls'))
                                      if isinstance(url, str)))
            sources = [matched[key] for key in keys[:MAX_SOURCES] if key in matched]
            if name and sources:
                children.append({'label': name, 'sources': sources})
                covered.update(normalized_news_url(source['url']) for source in sources)
        for child_term in (entry for entry in tier2 if entry != term):
            sources = [source for key, source in matches.get(child_term.lower(), {}).items() if key in matched]
            if sources:
                children.append({'label': child_term, 'sources': sources[:MAX_SOURCES]})
                covered.update(normalized_news_url(source['url']) for source in sources[:MAX_SOURCES])
        other = [source for key, source in matched.items() if key not in covered]
        if other:
            children.append({'label': '其他相关资料' if children else '相关资料', 'sources': other[:MAX_SOURCES]})
        topics.append({'label': term, 'children': children[:MAX_SUBTOPICS]})
    return topics


def retained_week(root: Path, day: dt.date) -> dict:
    for report in sorted((root / 'weekly').glob('*.md'), reverse=True):
        name = DATE_NAME.fullmatch(report.name)
        date = parse_date(name[1]) if name else None
        if not date or date > day:
            continue
        tiers: dict[str, list[str]] = {'tier1': [], 'tier2': []}
        section = None
        for line in report.read_text(encoding='utf-8').splitlines():
            if line.startswith('## '):
                match = re.match(r'## Tier ([12])\b', line)
                section = f'tier{match[1]}' if match else None
            elif section:
                match = re.match(r'- \*\*(.+?)\*\*', line)
                if match:
                    tiers[section].append(match[1])
        if tiers['tier1'] or tiers['tier2']:
            return {'generated_at': date.isoformat(), **tiers}
    return {}


def build_reader_graph(root: Path, day: dt.date, events: list[Event]) -> dict:
    path = root / 'state/trending_terms.json'
    empty = {'generated_at': None, 'method': None, 'topics': []}
    try:
        state = json.loads(path.read_text(encoding='utf-8-sig'))
    except (FileNotFoundError, UnicodeError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    curated = state.get('curated') if isinstance(state.get('curated'), dict) else {}
    generated = parse_date(state.get('generated_at'))
    if not generated or generated > day or not any(
        (rows(curated.get('topic_graph')), rows(state.get('tier1')), rows(state.get('tier2')))
    ):
        state = retained_week(root, day)
        if not state:
            return empty
        curated = {}
        generated_at = state['generated_at']
    else:
        generated_at = generated.isoformat()
    raw_topics = rows(curated.get('topic_graph'))
    method = 'ai' if raw_topics else 'legacy'
    topics = raw_topics or legacy_graph(root, generated_at, state, curated, events)
    by_source = {normalized_news_url(url): event for event in events for url in event.urls}
    output = []
    for topic in topics[:MAX_TOPICS]:
        if not isinstance(topic, dict) or not (label := clean(topic.get('label'), 44)):
            continue
        children = []
        for child in rows(topic.get('children'))[:MAX_SUBTOPICS]:
            if not isinstance(child, dict) or not (name := clean(child.get('label'), 44)):
                continue
            content = {}
            for item in rows(child.get('sources'))[:MAX_SOURCES]:
                source = source_record(item)
                if not source:
                    continue
                key = normalized_news_url(source['url'])
                observed = source.get('observed_at', generated_at)
                event = by_source.get(key) or Event(
                    id=hashlib.sha256(key.encode()).hexdigest()[:20], title=source['title'],
                    summary=source.get('summary', ''), urls=[], kinds=['weekly'],
                    published=source.get('published'), first_seen=observed, last_seen=observed,
                )
                row = content.setdefault(event.id, dict(asdict(event), date=event.date))
                row['first_seen'] = min(row['first_seen'], observed)
                row['last_seen'] = max(row['last_seen'], observed)
                row['published'] = row['published'] or source.get('published')
                row['date'] = row['published'] or row['first_seen']
                row['summary'] = row['summary'] or source.get('summary', '')
                if source['url'] not in row['urls']:
                    row['urls'].append(source['url'])
            if content:
                children.append({'label': name, 'content': list(content.values())})
        if children:
            output.append({'label': label, 'children': children})
    return {'generated_at': generated_at, 'method': method, 'topics': output}
