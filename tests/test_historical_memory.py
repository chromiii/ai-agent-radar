import datetime as dt
from pathlib import Path

import pytest

from historical_memory import HistoryIndex, build_snapshot
from hybrid_search import HybridEvidenceSearch
from learning_agent import verify_findings
from research_search import SearchBatch, build_query_plan


def write_report(root: Path, directory: str, name: str, content: str) -> None:
    path = root / directory
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(content, encoding="utf-8")


def fixture_repo(tmp_path: Path) -> Path:
    write_report(
        tmp_path,
        "weekly",
        "2026-09-27.md",
        """# Weekly

### Agent Memory checkpoint

- **为什么值得了解**：agent memory persistence 和 checkpoint recovery 开始进入应用层评测。
- **来源**：[来源 1](https://arxiv.org/abs/2609.11111)

## Tier 1 热词
- **agent memory**
- **coding agent**

## Tier 2 热词
- **research agent**
""",
    )
    write_report(
        tmp_path,
        "weekly",
        "2026-10-03.md",
        """# Weekly

### Agent Memory isolation

- **为什么值得了解**：agent memory 强调 run state 与 long-term memory isolation。
- **来源**：[来源 1](https://arxiv.org/abs/2610.22222)

## Tier 1 热词
- **agent memory**

## Tier 2 热词
- **coding agent**
""",
    )
    write_report(
        tmp_path,
        "company",
        "2026-10-02.md",
        """# Company

### ExampleAI: Agent memory product
- 链接：https://example.com/memory
- 理由：agent memory persistence

### OtherAI: Coding agent
- 链接：https://example.com/coding
- 理由：coding agent
""",
    )
    write_report(
        tmp_path,
        "inbox",
        "2026-10-01.md",
        """# Daily

### MemoryBench: Agent memory benchmark
- 链接：https://arxiv.org/abs/2610.33333
- AI 判断：agent memory benchmark with checkpoint evaluation
""",
    )
    return tmp_path


def config():
    return {
        "history": {
            "repository_url": "https://github.com/chromiii/ai-agent-radar",
            "repository_branch": "main",
            "max_results_per_round": 2,
        },
        "learning_agent": {"search": {"providers": ["hf"], "max_calls": 8}},
    }


def test_snapshot_tracks_entity_and_weekly_trend_history(tmp_path):
    root = fixture_repo(tmp_path)
    snapshot = build_snapshot(root, config())
    assert snapshot.documents
    assert snapshot.entities["ExampleAI"]["appearances"] == 1
    memory = snapshot.trends["agent memory"]
    assert memory["appearances"] == 2
    assert memory["tier1_count"] == 2
    assert memory["first_seen"] == "2026-09-27"
    assert memory["last_seen"] == "2026-10-03"


def test_history_search_exposes_memory_and_diversifies_results(tmp_path):
    root = fixture_repo(tmp_path)
    plan = build_query_plan("最近 agent memory 有什么变化？", dt.date(2026, 10, 7), 30)
    rows = HistoryIndex.from_repo(root, config()).search(plan, plan.expanded_queries, limit=4)
    assert len(rows) >= 2
    assert all(row["provider"] == "radar_history" for row in rows)
    assert all(row["date_kind"] == "radar_observed" for row in rows)
    assert any(row["evidence_kind"] == "radar_memory" for row in rows)
    assert any("Trend memory: agent memory" in row["title"] for row in rows)
    assert all("/blob/main/" in row["url"] for row in rows)


def test_historical_observations_cannot_satisfy_trend_publication_gate():
    items = [
        {"id": "S1", "url": "https://github.com/chromiii/ai-agent-radar/blob/main/weekly/2026-09-27.md",
         "date_kind": "radar_observed"},
        {"id": "S2", "url": "https://github.com/chromiii/ai-agent-radar/blob/main/weekly/2026-10-03.md",
         "date_kind": "radar_observed"},
    ]
    finding = {
        "topic": "Agent memory",
        "claim": "Agent memory 正在形成明确行业趋势。",
        "claim_type": "trend",
        "evidence_ids": ["S1", "S2"],
        "application": "理解历史信号。",
        "try_next": "做一个状态隔离玩具实验。",
        "level": "know",
        "one_liner": "历史 Radar 记录只能说明之前见过。",
        "learn": ["历史观察", "证据门槛"],
        "practice_minutes": 15,
        "done_when": "输出两个 observation 的日期。",
    }
    with pytest.raises(ValueError, match="published sources"):
        verify_findings([finding], items)


class FakeExternal:
    max_calls = 8
    used_calls = 0

    def search(self, plan, queries, selected_urls):
        self.used_calls += 2
        return SearchBatch(
            items=[{
                "title": "Fresh agent memory paper",
                "url": "https://arxiv.org/abs/2610.44444",
                "summary": "Agent memory evaluation.",
                "date": "2026-10-06",
                "date_kind": "published",
                "provider": "arxiv",
                "evidence_kind": "abstract",
                "retrieved_query": queries[0],
                "relevance_score": 3.0,
            }],
            trace=[{"provider": "fake", "status": "ok"}],
            warnings=[],
        )


def test_hybrid_search_prepends_history_without_spending_external_budget(tmp_path):
    root = fixture_repo(tmp_path)
    hybrid = HybridEvidenceSearch(config(), history_index=HistoryIndex.from_repo(root, config()))
    hybrid.external = FakeExternal()
    plan = build_query_plan("最近 agent memory 有什么变化？", dt.date(2026, 10, 7), 30)
    batch = hybrid.search(plan, plan.expanded_queries, set())
    assert batch.items[0]["provider"] == "radar_history"
    assert any(item["provider"] == "arxiv" for item in batch.items)
    assert hybrid.used_calls == 2
    assert any("不能替代" in warning for warning in batch.warnings)


def test_repeated_external_observations_are_collapsed_with_recurrence_metadata(tmp_path):
    root = fixture_repo(tmp_path)
    write_report(
        root,
        "inbox",
        "2026-10-03.md",
        """# Daily

### MemoryBench: Agent memory benchmark
- 链接：https://arxiv.org/abs/2610.33333
- AI 判断：agent memory benchmark repeated observation
""",
    )
    plan = build_query_plan("agent memory benchmark", dt.date(2026, 10, 7), 30)
    rows = HistoryIndex.from_repo(root, config()).search(plan, plan.expanded_queries, limit=8)
    matching = [row for row in rows if "MemoryBench" in row["title"]]
    assert len(matching) == 1
    assert matching[0]["observation_count"] == 2
    assert matching[0]["first_seen"] == "2026-10-01"
    assert matching[0]["last_seen"] == "2026-10-03"


def test_topic_gate_keeps_mcp_history_specific(tmp_path):
    root = fixture_repo(tmp_path)
    write_report(
        root,
        "inbox",
        "2026-10-04.md",
        """# Daily

### MCP tool validation
- 链接：https://example.com/mcp
- AI 判断：Model Context Protocol tool schema validation for agents

### Generic Agent Harness
- 链接：https://example.com/harness
- AI 判断：generic agent tool workflow
""",
    )
    plan = build_query_plan("MCP 最近有哪些值得学的实现？", dt.date(2026, 10, 7), 30)
    rows = HistoryIndex.from_repo(root, config()).search(plan, plan.expanded_queries, limit=8)
    assert rows
    assert all(
        "mcp" in (row["title"] + " " + row["summary"]).casefold()
        or "model context protocol" in (row["title"] + " " + row["summary"]).casefold()
        for row in rows
    )
    assert not any("Generic Agent Harness" in row["title"] for row in rows)


def test_exact_trend_memory_is_prioritized_for_change_question(tmp_path):
    root = fixture_repo(tmp_path)
    plan = build_query_plan("最近 agent memory 有什么变化？", dt.date(2026, 10, 7), 30)
    rows = HistoryIndex.from_repo(root, config()).search(plan, plan.expanded_queries, limit=5)
    assert rows[0]["evidence_kind"] == "radar_memory"
    assert "Trend memory: agent memory" in rows[0]["title"]
    assert "2 Weekly Radar reports" in rows[0]["summary"]


def test_history_can_be_disabled_without_local_results(tmp_path):
    root = fixture_repo(tmp_path)
    cfg = config()
    cfg["history"]["enabled"] = False
    hybrid = HybridEvidenceSearch(cfg, history_index=HistoryIndex.from_repo(root, config()))
    hybrid.external = FakeExternal()
    plan = build_query_plan("agent memory", dt.date(2026, 10, 7), 30)
    batch = hybrid.search(plan, plan.expanded_queries, set())
    assert [item["provider"] for item in batch.items] == ["arxiv"]
    assert not any("历史 Radar" in warning for warning in batch.warnings)


def test_history_only_signal_cannot_be_published_as_current_research():
    items = [
        {"id": "S1", "url": "https://github.com/chromiii/ai-agent-radar/blob/main/weekly/2026-09-27.md",
         "date_kind": "radar_observed"},
        {"id": "S2", "url": "https://github.com/chromiii/ai-agent-radar/blob/main/weekly/2026-10-03.md",
         "date_kind": "radar_observed"},
    ]
    findings = [
        {
            "topic": "Agent memory history",
            "claim": "Radar 过去多次记录 agent memory。",
            "claim_type": "signal",
            "evidence_ids": ["S1", "S2"],
            "application": "用于回顾历史。",
            "try_next": "整理两次历史记录。",
            "level": "know",
            "one_liner": "历史记录不是当前独立证据。",
            "learn": ["历史上下文", "当前证据"],
            "practice_minutes": 15,
            "done_when": "列出两次 Radar 日期。",
        }
    ]
    with pytest.raises(ValueError, match="non-historical source"):
        verify_findings(findings, items)


def test_history_plus_current_source_can_support_signal_answer():
    items = [
        {"id": "S1", "url": "https://github.com/chromiii/ai-agent-radar/blob/main/weekly/2026-10-03.md",
         "date_kind": "radar_observed"},
        {"id": "S2", "url": "https://arxiv.org/abs/2610.44444", "date_kind": "published"},
    ]
    findings = [
        {
            "topic": "Agent memory context",
            "claim": "Radar 历史和当前论文都出现了 agent memory 相关信号。",
            "claim_type": "signal",
            "evidence_ids": ["S1", "S2"],
            "application": "区分历史观察和当前来源。",
            "try_next": "比较历史记录与当前论文。",
            "level": "know",
            "one_liner": "混合检索把历史上下文与当前证据分开。",
            "learn": ["历史上下文", "当前证据"],
            "practice_minutes": 15,
            "done_when": "分别标注 Radar 与 published 来源。",
        }
    ]
    assert verify_findings(findings, items)[0]["evidence_ids"] == ["S1", "S2"]
