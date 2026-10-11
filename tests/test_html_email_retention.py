import datetime as dt
import html
from email.message import EmailMessage
from pathlib import Path

import pytest

import archive_retention as ar
import email_render as er
import send_email


SAMPLE = """# AI Agent Radar · 周度情报与学习简报 — 2026-10-11

覆盖区间：2026-10-05 至 2026-10-11。

## 本周值得查看的论文 / 工程项目

1. [Safe paper](https://arxiv.org/abs/2610.12345)（Radar 2026-10-10）
2. [Malicious <script>](javascript:alert(1)) should remain literal text

## 本周公司与产品动态

- **公司**：可靠来源 https://example.com

## 本周 LangChain 学习路线

1. **RunnableLambda**：第一课，约 25 分钟。
   - [官方文档](https://docs.langchain.com/oss/python/langchain/overview)
"""


def test_html_mail_has_safe_links_and_no_raw_source_html():
    output = er.render_html(SAMPLE, "Radar weekly")
    assert "<html" in output and 'lang="zh-CN"' in output
    assert "https://arxiv.org/abs/2610.12345" in output
    assert "<script>" not in output
    assert "javascript:alert(1)" in output  # escaped as literal text, not clickable
    assert "href=\"javascript:" not in output
    assert "RunnableLambda" in output
    assert "background:#0f172a" in output


def test_text_fallback_does_not_expose_markdown_markup():
    plain = er.render_text(SAMPLE)
    assert "Safe paper — https://arxiv.org/abs/2610.12345" in plain
    assert "**RunnableLambda**" not in plain
    assert "## " not in plain


def test_html_mail_multipart_without_real_smtp(tmp_path, monkeypatch):
    report = tmp_path / "week.md"
    report.write_text(SAMPLE, encoding="utf-8")
    sent = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def login(self, username, password):
            assert username == "test@fake.com" and password == "test-secret"
        def send_message(self, msg):
            sent.append(msg)

    monkeypatch.setattr(send_email.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(send_email.sys, "argv", ["send_email.py", str(report), "漂亮周报"])
    monkeypatch.setenv("QQ_MAIL_USERNAME", "test@fake.com")
    monkeypatch.setenv("QQ_MAIL_PASSWORD", "test-secret")
    monkeypatch.setenv("QQ_MAIL_TO", "reader@fake.com")
    send_email.main()
    assert len(sent) == 1
    message = sent[0]
    assert isinstance(message, EmailMessage) and message.is_multipart()
    assert message.get_body(preferencelist=("html",)).get_content().startswith("<!doctype html>")
    assert "Safe paper" in message.get_body(preferencelist=("plain",)).get_content()


def test_archive_retention_only_removes_old_reports(tmp_path):
    files = [
        "inbox/2026-08-01.md",
        "inbox/2026-10-01.md",
        "inbox/2026-10-11.md",
        "company/2026-07-01.md",
        "company/2026-10-10.md",
        "weekly/2026-08-01.md",
        "weekly/2026-09-01.md",
        "weekly/2026-10-03.md",
        "weekly/2026-10-10.md",
        "briefings/2026-07-01.md",
        "briefings/2026-07-01.html",
        "briefings/2026-10-11.md",
        "state/learning_progress.json",
    ]
    for name in files:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("test")
    expired = {p.relative_to(tmp_path).as_posix() for p in ar.expired_reports(tmp_path, as_of=dt.date(2026, 10, 11))}
    assert "inbox/2026-08-01.md" in expired
    assert "inbox/2026-10-01.md" not in expired
    assert "company/2026-07-01.md" in expired
    assert "weekly/2026-08-01.md" in expired
    assert "weekly/2026-09-01.md" in expired
    assert "briefings/2026-07-01.md" not in expired  # only two, keep four
    assert "state/learning_progress.json" not in expired


def test_retention_never_deletes_unrecognized_filenames(tmp_path):
    p = tmp_path / "inbox" / "custom_notes.md"
    p.parent.mkdir(parents=True)
    p.write_text("keep")
    assert not ar.expired_reports(tmp_path, as_of=dt.date(2026, 10, 11))


def test_real_weekly_teaching_cards_lead_finished_newsletter(tmp_path):
    from weekly_briefing import build_briefing

    root = Path(__file__).parents[1]
    markdown = build_briefing(root=root, as_of=dt.date(2026, 10, 11))
    assert "本周先看这 3 件事" in markdown
    assert "Agent Harness 优化" in markdown
    assert "发生了什么" in markdown
    assert "实际有什么用" in markdown
    assert "你可以怎么练" in markdown
    assert "https://arxiv.org/abs/2610.00906" in markdown
    assert "无需下载 Markdown" in markdown
    rendered = er.render_html(markdown)
    assert "Agent Harness" in rendered
    assert "href=\"https://arxiv.org/abs/2610.00906\"" in rendered
