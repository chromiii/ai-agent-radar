"""Blend local Radar history with bounded external evidence search."""
from __future__ import annotations

from typing import Any

from historical_memory import HistoryIndex, ROOT
from research_search import EvidenceSearch, QueryPlan, SearchBatch


class HybridEvidenceSearch:
    """History-first retrieval without letting historical observations replace publications."""

    def __init__(self, config: dict[str, Any], session: Any = None, history_index: HistoryIndex | None = None):
        self.config = config
        self.external = EvidenceSearch(config, session=session)
        self.history = history_index or HistoryIndex.from_repo(ROOT, config)
        cfg = config.get("history", {})
        self.history_limit = int(cfg.get("max_results_per_round", 4))
        if not 0 <= self.history_limit <= 6:
            raise ValueError("history.max_results_per_round must be between 0 and 6")
        self.max_calls = self.external.max_calls

    @property
    def used_calls(self) -> int:
        return self.external.used_calls

    def search(self, plan: QueryPlan, queries: list[str], selected_urls: set[str]) -> SearchBatch:
        history_items = self.history.search(
            plan,
            queries,
            selected_urls=selected_urls,
            limit=self.history_limit,
        )
        history_urls = {item["url"] for item in history_items}
        external = self.external.search(plan, queries, selected_urls | history_urls)
        items = history_items + external.items
        trace = [
            {
                "provider": "radar_history",
                "status": "ok",
                "queries": queries,
                "selected": len(history_items),
                "used_external_calls": self.external.used_calls,
            },
            *external.trace,
        ]
        warnings = list(external.warnings)
        if history_items:
            warnings.append(
                "已加入历史 Radar 记录作为跨运行上下文；radar_observed 只表示过去曾记录，"
                "不能替代独立 published source 证明当前趋势。"
            )
        return SearchBatch(items=items[:12], trace=trace, warnings=list(dict.fromkeys(warnings)))
