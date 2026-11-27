"""Build a source-linked event feed from the reports Radar already produces."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from breaking_news import is_official, normalized_news_url
from historical_memory import DATE_NAME, MD_LINK, RAW_URL, SKIP_HEADINGS
from research_search import clean, parse_date

REPORTS = {'inbox': 'daily', 'company': 'company'}
DOMAIN = re.compile(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', re.ASCII)
HEADING = re.compile(r'^###\s+(?:\d+\.\s+)?(.+)$')
NUMBERED_LINK = re.compile(r'^\d+\.\s+(?=\[)')
FIELD = re.compile(r'^-\s*([^:：]+)[:：]\s*(.+)$')
COMPANY_DATE = re.compile(r'\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b')


@dataclass
class Occurrence:
    title: str
    url: str
    kind: str
    seen: str
    summary: str = ''
    published: str | None = None
    identity: str = ''


@dataclass
class Event:
    id: str
    title: str
    summary: str
    urls: list[str]
    kinds: list[str]
    published: str | None
    first_seen: str
    last_seen: str

    @property
    def date(self) -> str:
        return self.published or self.first_seen


@dataclass
class Topic:
    name: str
    include: list[str]
    exclude: list[str]
    sources: list[str]
    kinds: list[str]


def information_date(value: str) -> str | None:
    parsed = parse_date(value)
    if parsed:
        return parsed.isoformat()
    for match in COMPANY_DATE.finditer(value):
        for fmt in ('%B %d %Y', '%b %d %Y'):
            try:
                return dt.datetime.strptime(' '.join(match.groups()), fmt).date().isoformat()
            except ValueError:
                continue
    return None


def read_occurrences(path: Path, day: str, kind: str) -> list[Occurrence]:
    occurrences: list[Occurrence] = []
    item: Occurrence | None = None
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        heading = HEADING.match(line)
        numbered = NUMBERED_LINK.match(line)
        linked = MD_LINK.match(line[numbered.end():]) if numbered else None
        if heading or linked or line.startswith('#'):
            item = None
            if heading or linked:
                title = clean(heading[1] if heading else linked[1], 220)
                if title and not any(ignored in title for ignored in SKIP_HEADINGS):
                    item = Occurrence(title, '' if heading else linked[2], kind, day)
                    if kind == 'company':
                        item.published = information_date(title)
                    occurrences.append(item)
            continue
        field = FIELD.match(line)
        if not item or not field:
            continue
        label, value = field[1].casefold(), field[2]
        if label in ('link', '链接') and not item.url:
            url = RAW_URL.search(value)
            if url:
                item.url = url[0].rstrip('.,;，。；')
        elif label in ('日期', 'published', 'date'):
            item.published = information_date(value) or item.published
        elif label in ('判断', 'ai 判断', '信息', '摘要', 'why', 'summary'):
            item.summary = clean(value, 260)
    return occurrences


def collect_events(root: Path, as_of: dt.date) -> list[Event]:
    by_url: dict[str, list[Occurrence]] = defaultdict(list)
    for directory, kind in REPORTS.items():
        for path in sorted((root / directory).glob('*.md')):
            valid_day = DATE_NAME.fullmatch(path.name)
            day = parse_date(valid_day[1]) if valid_day else None
            if day is None or day > as_of:
                continue
            for item in read_occurrences(path, day.isoformat(), kind):
                key = normalized_news_url(item.url)
                if not key or key.startswith('https://github.com/chromiii/ai-agent-radar/'):
                    continue
                item.identity = key
                by_url[key].append(item)

    groups: dict[str, list[Occurrence]] = defaultdict(list)
    for key, rows in by_url.items():
        dated = next((row for row in rows if row.published), None)
        title = re.sub(r'\s+', ' ', dated.title.lower()).strip() if dated else ''
        # Require an exact, descriptive title and explicitly dated evidence before
        # merging different URLs. The canonical paper ID takes precedence.
        if len(title) >= 24 and not key.startswith('https://arxiv.org/abs/'):
            key = f'title:{dated.published}:{title}'
        groups[key].extend(rows)

    events = []
    for rows in groups.values():
        rows.sort(key=lambda item: (not is_official(item.identity), not item.published, not item.summary, item.url))
        sources: dict[tuple[str, str | None], Occurrence] = {}
        for item in sorted(rows, key=lambda row: (row.seen, row.url), reverse=True):
            sources.setdefault((item.identity, urlsplit(item.url).hostname), item)
        evidence = sorted(sources.values(), key=lambda item: (
            urlsplit(item.url).hostname not in ('arxiv.org', 'export.arxiv.org'),
            not is_official(item.identity), item.url,
        ))
        dates = [item.published for item in rows if item.published]
        first = min(rows, key=lambda item: (item.seen, item.identity))
        events.append(Event(
            id=hashlib.sha256(first.identity.encode()).hexdigest()[:20], title=rows[0].title,
            summary=next((item.summary for item in rows if item.summary), ''),
            urls=[item.url for item in evidence], kinds=sorted({item.kind for item in rows}),
            published=min(dates, default=None),
            first_seen=first.seen, last_seen=max(item.seen for item in rows),
        ))
    return sorted(events, key=lambda row: (row.date, row.first_seen, row.id), reverse=True)


def load_watchlist(path: Path) -> list[Topic]:
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    rows = value.get('topics') if isinstance(value, dict) else None
    if not isinstance(rows, list) or len(rows) > 12:
        raise ValueError('watchlist must contain a topics list of up to 12 entries')
    topics: list[Topic] = []
    names: set[str] = set()
    for row in rows:
        name = row.get('name') if isinstance(row, dict) else None
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60 or '\n' in name or '\r' in name:
            raise ValueError('topic name must be a nonempty single line of up to 60 characters')
        name = name.strip()
        if name.lower() in names:
            raise ValueError(f'duplicate topic name: {name}')
        lists: dict[str, list[str]] = {}
        for field in ('include', 'exclude', 'sources', 'kinds'):
            terms = row.get(field, [])
            if (not isinstance(terms, list) or len(terms) > 30 or any(
                not isinstance(term, str) or not term.strip() or len(term.strip()) > 120
                or '\r' in term or '\n' in term for term in terms
            )):
                raise ValueError(f'{name}: {field} must be a list of up to 30 nonempty single-line values')
            lists[field] = list(dict.fromkeys(term.strip().lower() for term in terms))
        if any(not DOMAIN.fullmatch(domain) for domain in lists['sources']):
            raise ValueError(f'{name}: sources must be domain names')
        if set(lists['kinds']) - set(REPORTS.values()):
            raise ValueError(f'{name}: kinds must be daily or company')
        topics.append(Topic(name, **lists))
        names.add(name.lower())
    return topics


def matches_topic(event: Event, topic: Topic) -> bool:
    if topic.kinds and not set(topic.kinds).intersection(event.kinds):
        return False
    if topic.sources:
        domains = [urlsplit(url).hostname or '' for url in event.urls]
        if not any(host == rule or host.endswith('.' + rule) for host in domains for rule in topic.sources):
            return False
    text = (event.title + ' ' + event.summary).lower()

    def matches(term: str) -> bool:
        before = r'(?<![a-z0-9])' if re.match(r'[a-z0-9]', term) else ''
        after = r'(?![a-z0-9])' if re.search(r'[a-z0-9]$', term) else ''
        return bool(re.search(before + re.escape(term) + after, text))

    return (not topic.include or any(map(matches, topic.include))) and not any(map(matches, topic.exclude))
