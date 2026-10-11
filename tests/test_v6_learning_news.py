import datetime as dt
import json
from pathlib import Path

import pytest
import yaml

import breaking_news as bn
import learning_path as lp
import weekly_briefing as wb


ROOT = Path(__file__).resolve().parents[1]
DAY = dt.date(2026, 10, 10)


def test_curriculum_has_explicit_order_and_first_lesson_without_prereqs(tmp_path):
    lessons = lp.read_curriculum()
    assert len(lessons) >= 8
    assert lessons[0]["id"] == "lc01-runnables"
    assert lessons[0]["prerequisites"] == []
    path = tmp_path / "public_learning_path.json"
    first = lp.next_lessons(progress_path=path, today=DAY)
    assert first[0]["lesson"]["id"] == "lc01-runnables"
    assert first[0]["action"] == "start"
    with pytest.raises(ValueError, match="prerequisite"):
        lp.mark_lesson("lc02-prompts-messages", "practiced", progress_path=path, today=DAY)
    row = lp.mark_lesson("lc01-runnables", "practiced", progress_path=path, today=DAY)
    assert row["next_review"] == "2026-10-11"
    assert lp.next_lessons(progress_path=path, today=DAY)[0]["lesson"]["id"] == "lc02-prompts-messages"
    assert lp.next_lessons(progress_path=path, today=dt.date(2026, 10, 11))[0]["action"] == "review"
    reviewed = lp.mark_lesson("lc01-runnables", "reviewed", progress_path=path,
                              today=dt.date(2026, 10, 11))
    assert reviewed["next_review"] == "2026-10-18"
    assert len(reviewed["events"]) == 2


def test_curriculum_manual_only_and_reset_removes_false_completion(tmp_path):
    path = tmp_path / "public.json"
    assert not path.exists()
    assert "lc01-runnables" in lp.format_plan(progress_path=path)
    assert not path.exists()
    lp.mark_lesson("lc01-runnables", "practiced", progress_path=path, today=DAY)
    lp.mark_lesson("lc01-runnables", "reset", progress_path=path, today=DAY)
    with pytest.raises(ValueError, match="prerequisite"):
        lp.mark_lesson("lc02-prompts-messages", "practiced", progress_path=path, today=DAY)
    with pytest.raises(ValueError, match="review requires"):
        lp.mark_lesson("lc01-runnables", "reviewed", progress_path=path, today=DAY)


def write_report(root, name, content, folder="inbox"):
    path = root / folder
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(content, encoding="utf-8")


DAILY = """# Daily Radar

### LangGraph Critical security advisory
- 链接：[官方修复](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-AAAA-BBBB-CCCC)
- 日期：2026-10-09
- 信息：Critical vulnerability in an Agent runtime, manual impact verification required.

### Everyday coding agent tutorial
- 链接：https://example.org/tutorial
- 信息：A normal coding agent tutorial with mock scripts, not an outage or breaking change.
"""

COMPANY = """# Company Radar

### Vendor: Major release
- 链接：https://example.org/major-release
- 日期：2026-10-09
- 信息：A major release requiring review of claimed significance.
"""


def test_breaking_desk_source_and_manual_status_survive_rescan(tmp_path):
    write_report(tmp_path, "2026-10-09.md", DAILY)
    q = tmp_path / "state" / "breaking_queue.json"
    data = bn.scan_reports(tmp_path, q, as_of=DAY)
    assert len(data["items"]) == 1  # generic new tutorial and release link not auto-breaking
    item = next(iter(data["items"].values()))
    assert item["status"] == "pending"
    assert item["severity"] == "high"
    assert item["official_source_candidate"]
    assert item["source_url"].startswith("https://github.com/langchain-ai")
    assert "待核验" in bn.render_desk(data)
    approved = bn.mark_item(item["id"], "approved", queue_path=q, today=DAY)
    assert approved["status"] == "approved"
    bn.scan_reports(tmp_path, q, as_of=DAY)
    assert bn.read_queue(q)["items"][item["id"]]["status"] == "approved"
    bn.mark_item(item["id"], "dismissed", queue_path=q, today=DAY)
    assert item["id"] not in bn.render_desk(bn.read_queue(q))
    assert item["id"] in bn.render_desk(bn.read_queue(q), include_dismissed=True)
    assert len(bn.read_queue(q)["items"][item["id"]]["history"]) == 2


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return [
            {"name": "critical vulnerability hotfix", "body": "Fix security advisory", "published_at": "2026-10-10T06:00:00Z",
             "html_url": "https://github.com/langchain-ai/langgraph/releases/tag/v2.1.0"},
            {"name": "regular patch", "body": "Minor improvements", "published_at": "2026-10-10T05:00:00Z",
             "html_url": "https://github.com/langchain-ai/langgraph/releases/tag/v2.1.1"},
        ]


def test_official_release_watch_selects_impact_and_keeps_approval(tmp_path):
    path = tmp_path / "queue.json"
    calls = []
    def request(url, **kwargs):
        calls.append(url)
        return FakeResponse()
    at = dt.datetime(2026, 10, 10, 12, tzinfo=dt.timezone.utc)
    state = bn.watch_official_releases(queue_path=path, as_of=at, request=request)
    assert calls
    assert any("langgraph" in x for x in calls)
    assert len(state["items"]) == 1
    item = next(iter(state["items"].values()))
    assert item["severity"] == "high"
    bn.mark_item(item["id"], "resolved", queue_path=path, today=DAY)
    bn.watch_official_releases(queue_path=path, as_of=at, request=request)
    assert bn.read_queue(path)["items"][item["id"]]["status"] == "resolved"


def test_weekly_news_dedup_date_and_learning_path(tmp_path):
    write_report(tmp_path, "2026-10-09.md", DAILY)
    write_report(tmp_path, "2026-10-08.md", DAILY)  # same URLs in another report
    write_report(tmp_path, "2026-10-09.md", COMPANY, folder="company")
    write_report(tmp_path, "2026-09-20.md", DAILY)  # outside window
    queue = tmp_path / "state" / "breaking_queue.json"
    bn.scan_reports(tmp_path, queue, as_of=DAY)
    news = wb.collect(tmp_path, DAY)
    assert len(news["research"]) == 2  # dedup by canonical external source
    assert len(news["companies"]) == 1
    briefing = wb.build_briefing(tmp_path, DAY, queue)
    assert briefing.count("langgraph/security/advisories") >= 1
    assert "Breaking Desk" in briefing
    assert "本周 LangChain 学习路线" in briefing
    assert "lc01-runnables" in briefing
    assert "需复核" in briefing or "待核验" in briefing


def test_weekly_is_only_regular_notification_and_breaking_requires_review():
    daily = (ROOT / ".github/workflows/daily.yml").read_text()
    company = (ROOT / ".github/workflows/company-radar.yml").read_text()
    weekly = (ROOT / ".github/workflows/weekly-trends.yml").read_text()
    breaking = (ROOT / ".github/workflows/breaking-desk.yml").read_text()
    assert "python send_email.py" not in daily
    assert "python send_email.py" not in company
    assert weekly.count("python send_email.py") == 1
    assert "weekly_briefing.py" in weekly
    assert "python send_email.py" not in breaking
    assert "*/6" in breaking


def test_public_progress_initial_states_do_not_contain_secrets():
    for name in ("learning_progress.json", "learning_path.json", "breaking_queue.json"):
        path = ROOT / "state" / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "state/learning_progress.json" not in ignore
    assert "state/agent_runs/" in ignore


def test_manual_breaking_notification_requires_approval_and_is_deduplicated(tmp_path):
    write_report(tmp_path, "2026-10-09.md", DAILY)
    queue_path = tmp_path / "breaking.json"
    state = bn.scan_reports(tmp_path, queue_path, as_of=DAY)
    cid = next(iter(state["items"]))
    sent = []
    with pytest.raises(ValueError, match="human-approved"):
        bn.notify_approved(cid, queue_path=queue_path, sender=lambda item: sent.append(item))
    assert sent == []
    bn.mark_item(cid, "approved", queue_path=queue_path, today=DAY)
    at = dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc)
    row = bn.notify_approved(cid, queue_path=queue_path, sender=lambda item: sent.append(item), at=at)
    assert row["notified_at"] == "2026-10-10T00:00:00+00:00"
    bn.notify_approved(cid, queue_path=queue_path, sender=lambda item: sent.append(item), at=at)
    assert len(sent) == 1
    bn.scan_reports(tmp_path, queue_path, as_of=DAY)
    assert bn.read_queue(queue_path)["items"][cid]["notified_at"] == row["notified_at"]


def test_no_mail_or_progress_writes_on_read():
    workflow = (ROOT / ".github/workflows/breaking-desk.yml").read_text(encoding="utf-8")
    assert "notify) python breaking_news.py notify" in workflow
    assert "*/6" in workflow
    assert "send_email.py" not in workflow
    assert "state/learning_progress.json" not in (ROOT / ".gitignore").read_text()
