import datetime as dt
import json
from pathlib import Path

import pytest

import ask_radar
import learning_memory as lm
from learning_agent import AgentState
from research_search import canonical_url


REPORT = """# AI Agent 应用层学习周报 - 2026-10-10

范围：2026-10-04 到 2026-10-10

## 这周先学什么

### 1. Agent memory checkpoint

- **学习深度**：先知道
- **30 秒概念**：run state 与长期记忆分开存储。
- **为什么值得了解**：agent memory persistence 需要容错恢复。
- **用在哪里**：基于 checkpoint 的恢复。
- **应用层学到这里**：checkpoint；persistence
- **动手建议（建议 20 分钟）**：写一个玩具 checkpoint。
- **完成标准**：输出两个恢复结果。
- **来源**：[来源 1](https://huggingface.co/papers/2610.12345)

### 2. MCP mock dispatcher

- **学习深度**：值得动手
- **30 秒概念**：用本地 schema 定义工具参数。
- **为什么值得了解**：MCP tools 需要接口边界。
- **用在哪里**：Python 工具层。
- **应用层学到这里**：schema；dispatcher
- **动手建议（建议 20 分钟）**：写一个玩具 mock。
- **完成标准**：输出两次调用日志。
- **来源**：[来源 1](https://example.com/mcp-tools)

### 3. RAG source verification

- **学习深度**：理解原因
- **30 秒概念**：区分 RAG citation 与 claim entailment。
- **为什么值得了解**：减少编造引用。
- **用在哪里**：RAG 验证。
- **应用层学到这里**：citations；reranking
- **动手建议（建议 20 分钟）**：手动核验两条来源。
- **完成标准**：标注可信度。
- **来源**：[来源 1](https://example.com/rag-check)

## Tier 1 热词

- agent memory
"""


def cards():
    return lm.cards_from_weekly(REPORT, "2026-10-10")


def test_card_catalog_stable_ids_from_canonical_source():
    rows = cards()
    assert len(rows) == 3
    assert rows[0].topic == "memory"
    assert rows[1].topic == "mcp"
    assert rows[2].topic == "rag"
    assert rows[0].source_url == "https://arxiv.org/abs/2610.12345"
    assert lm.card_id_for("https://arxiv.org/abs/2610.12345v2", "Different title") == rows[0].card_id


def test_progress_is_explicit_idempotent_and_tracks_history(tmp_path):
    path = tmp_path / "private.json"
    first = cards()[0]
    assert lm.read_memory(path)["entries"] == {} and not path.exists()
    lm.weekly_recommendations(REPORT, path)
    assert not path.exists()  # opening Weekly is not evidence of learning
    at = dt.datetime(2026, 10, 10, 9, tzinfo=dt.timezone.utc)
    saved = lm.mark_progress(first, "saved", path, at=at)
    assert saved["status"] == "saved"
    assert len(saved["history"]) == 1
    duplicate = lm.mark_progress(first, "saved", path, at=at)
    assert len(duplicate["history"]) == 1
    practiced = lm.mark_progress(first, "practiced", path, at=at)
    assert practiced["status"] == "practiced"
    assert [step["status"] for step in practiced["history"]] == ["saved", "practiced"]
    assert lm.read_memory(path)["entries"][first.card_id]["status"] == "practiced"


def test_recommendations_are_explicit_and_skip_old_basics(tmp_path):
    path = tmp_path / "private.json"
    memory, mcp, rag = cards()
    lm.mark_progress(memory, "studied", path)
    lm.mark_progress(mcp, "practiced", path)
    lm.mark_progress(rag, "skipped", path)
    ranking = lm.prioritize(cards(), lm.read_memory(path))
    assert [r["item"].card_id for r in ranking] == [memory.card_id, mcp.card_id, rag.card_id]
    assert ranking[0]["score"] > ranking[1]["score"] > ranking[2]["score"]
    text = lm.weekly_recommendations(REPORT, path)
    assert "优先补做" in text
    assert "RAG source verification" not in text  # manually skipped
    assert "完成练习 1 张" in text


def test_new_card_in_practiced_topic_gets_advanced_guidance_without_mastery_claim(tmp_path):
    path = tmp_path / "private.json"
    old = cards()[0]
    lm.mark_progress(old, "practiced", path)
    new = lm.LearningItem(
        lm.card_id_for("https://example.com/memory-v2"),
        "Agent memory failure recovery",
        "https://example.com/memory-v2",
        "memory",
        "值得动手",
        "2026-10-17",
    )
    ranked = lm.prioritize([new, old], lm.read_memory(path))
    assert ranked[0]["item"] == new
    assert "边界和失败恢复" in ranked[0]["advice"]
    assert "掌握" not in ranked[0]["advice"]


def test_bad_status_id_source_and_schema_are_rejected(tmp_path):
    path = tmp_path / "state.json"
    item = cards()[0]
    with pytest.raises(ValueError, match="status"):
        lm.mark_progress(item, "mastered", path)
    with pytest.raises(ValueError, match="card ID"):
        lm.mark_progress(lm.LearningItem("lc-bad", item.title, item.source_url, item.topic, item.level, ""), "studied", path)
    with pytest.raises(ValueError, match="match"):
        lm.mark_progress(lm.LearningItem(item.card_id, item.title, "https://example.org/other", item.topic, item.level, ""), "studied", path)
    path.write_text('{"schema_version":3,"entries":{}}')
    with pytest.raises(ValueError, match="schema"):
        lm.read_memory(path)


def test_no_private_file_or_no_manual_marks_means_no_personalized_section(tmp_path):
    path = tmp_path / "progress.json"
    assert lm.weekly_recommendations(REPORT, path) == ""
    assert lm.research_recommendations([], [], path) == ""
    path.write_text(json.dumps({"schema_version": 1, "entries": {}}))
    assert lm.weekly_recommendations(REPORT, path) == ""
    assert "state/learning_progress.json" in (Path(__file__).parents[1] / ".gitignore").read_text()


def test_personalized_ask_radar_uses_explicit_memory_only(tmp_path, monkeypatch):
    progress = tmp_path / "learning.json"
    old = cards()[0]
    lm.mark_progress(old, "studied", progress)
    monkeypatch.setenv("RADAR_LEARNING_MEMORY_PATH", str(progress))

    def fake_agent(state, markdown, config, **kwargs):
        state.status = "finished"
        state.findings = [{
            "topic": "Agent memory checkpoint",
            "evidence_ids": ["S1"],
            "level": "build",
        }]
        state.selected_items = [{
            "id": "S1",
            "url": "https://arxiv.org/abs/2610.12345",
            "date_kind": "published",
        }]
        state.final_answer = "有来源的模拟回答。"
        return state

    monkeypatch.setattr(ask_radar, "run_agent", fake_agent)
    state, answer = ask_radar.run_request("最近 agent memory?", {}, tmp_path / "out")
    assert state.status == "finished"
    assert "结合你的学习记录" in answer
    assert "优先补做" in answer
    assert "有来源的模拟回答" in answer
    assert len(lm.read_memory(progress)["entries"][old.card_id]["history"]) == 1


def test_weekly_parser_ignores_trend_index_and_unreferenced_content():
    report = REPORT.replace("## Tier 1 热词", "### 4. No source\n- 你好\n\n## Tier 1 热词")
    assert len(lm.cards_from_weekly(report)) == 3
    assert lm.cards_from_weekly("## Tier 1 热词\n### 1. Agent memory") == []
