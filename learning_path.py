"""Explicit, public, reviewable LangChain-first learning path.

Concept progress is not inferred from newsletter reads. Dates are review
suggestions, not claims that a person forgot or mastered material.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
CURRICULUM = ROOT / "curriculum.yaml"
PROGRESS = ROOT / "state" / "learning_path.json"
STATES = {"studying", "practiced", "reviewed", "skipped", "reset"}
REVIEW_INTERVALS = (1, 7, 30)


def read_curriculum(path: Path = CURRICULUM) -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rows = data.get("lessons", []) if isinstance(data, dict) else []
    if not isinstance(rows, list) or not rows:
        raise ValueError("curriculum must define lessons")
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not re.fullmatch(r"lc[0-9]{2}-[a-z0-9-]+", str(row.get("id", ""))):
            raise ValueError("invalid lesson ID")
        if row["id"] in ids:
            raise ValueError("duplicate lesson ID")
        prereqs = row.get("prerequisites", [])
        if not isinstance(prereqs, list) or any(p not in ids for p in prereqs):
            raise ValueError("prerequisites must refer to earlier lessons")
        ids.add(row["id"])
    return rows


def read_progress(path: Path = PROGRESS) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"schema_version": 1, "lessons": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid curriculum progress JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("lessons"), dict):
        raise ValueError("unsupported curriculum progress schema")
    for key, row in payload["lessons"].items():
        if not isinstance(key, str) or not isinstance(row, dict) or row.get("status") not in STATES:
            raise ValueError("invalid curriculum progress entry")
    return payload


def write_progress(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".curriculum-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(payload, out, ensure_ascii=False, indent=2)
            out.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def mark_lesson(lesson_id: str, status: str, *, progress_path: Path = PROGRESS,
                curriculum_path: Path = CURRICULUM, today: dt.date | None = None) -> dict[str, Any]:
    lessons = {x["id"]: x for x in read_curriculum(curriculum_path)}
    if lesson_id not in lessons:
        raise ValueError("unknown lesson")
    if status not in STATES:
        raise ValueError("unknown progress action")
    today = today or dt.date.today()
    progress = read_progress(progress_path)
    previous = progress["lessons"].get(lesson_id, {})
    if previous.get("status") == status and status != "reviewed":
        return previous
    if status in {"practiced", "reviewed"}:
        missing = [p for p in lessons[lesson_id]["prerequisites"]
                   if progress["lessons"].get(p, {}).get("status") not in {"practiced", "reviewed"}]
        if missing:
            raise ValueError(f"prerequisite not practiced: {', '.join(missing)}")
    rounds = int(previous.get("reviews", 0))
    if status == "reviewed":
        if previous.get("status") not in {"practiced", "reviewed"}:
            raise ValueError("review requires a practiced lesson")
        rounds = min(rounds + 1, len(REVIEW_INTERVALS) - 1)
    elif status == "practiced" and previous.get("status") not in {"practiced", "reviewed"}:
        rounds = 0
    elif status == "reset":
        rounds = 0
    due = (today + dt.timedelta(days=REVIEW_INTERVALS[rounds])).isoformat() if status in {"practiced", "reviewed"} else None
    events = previous.get("events", [])
    if not isinstance(events, list):
        events = []
    events = events[-29:] + [{"status": status, "date": today.isoformat()}]
    updated = {"status": status, "updated_at": today.isoformat(), "reviews": rounds, "next_review": due,
               "events": events}
    progress["lessons"][lesson_id] = updated
    write_progress(progress_path, progress)
    return updated


def next_lessons(*, curriculum_path: Path = CURRICULUM, progress_path: Path = PROGRESS,
                 today: dt.date | None = None, limit: int = 3) -> list[dict[str, Any]]:
    today = today or dt.date.today()
    progress = read_progress(progress_path)["lessons"]
    lessons = read_curriculum(curriculum_path)
    due, ready = [], []
    for lesson in lessons:
        state = progress.get(lesson["id"], {})
        status = state.get("status")
        prereq_ok = all(progress.get(p, {}).get("status") in {"practiced", "reviewed"}
                        for p in lesson["prerequisites"])
        if status in {"practiced", "reviewed"}:
            if state.get("next_review") and state["next_review"] <= today.isoformat():
                due.append({"lesson": lesson, "action": "review", "due": state["next_review"]})
        elif prereq_ok and status != "skipped":
            ready.append({"lesson": lesson, "action": "practice" if status == "studying" else "start",
                          "due": None})
    return (due + ready)[:max(0, limit)]


def format_plan(*, curriculum_path: Path = CURRICULUM, progress_path: Path = PROGRESS,
                today: dt.date | None = None, limit: int = 3) -> str:
    picks = next_lessons(curriculum_path=curriculum_path, progress_path=progress_path, today=today, limit=limit)
    lines = ["## 本周 LangChain 学习路线", "",
             "进度由你主动标记；复习日期只是一条建议，不代表自动测出的掌握水平。", ""]
    if not picks:
        lines.append("当前没有可安排条目；检查前置课程或跳过状态。")
    for index, row in enumerate(picks, 1):
        lesson = row["lesson"]
        action = {"start": "开始", "practice": "完成练习", "review": "建议复习"}[row["action"]]
        lines.extend([f"{index}. **{lesson['title']}**（{action}，约 {lesson['minutes']} 分钟）",
                      f"   - 目标：{lesson['objective']}",
                      f"   - 完成标准：{lesson.get('done_when', '自己完成练习')}",
                      f"   - [官方文档]({lesson['docs']})",
                      f"   - 课程 ID：\u0000{lesson['id']}\u0000".replace("\u0000", "\u0060"), ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--progress", type=Path, default=PROGRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("next")
    sub.add_parser("status")
    mark = sub.add_parser("mark")
    mark.add_argument("lesson_id")
    mark.add_argument("status", choices=sorted(STATES))
    args = parser.parse_args()
    if args.command == "mark":
        row = mark_lesson(args.lesson_id, args.status, progress_path=args.progress)
        print(f"{args.lesson_id}: {row['status']}; next_review={row['next_review']}")
    elif args.command == "status":
        print(json.dumps(read_progress(args.progress), ensure_ascii=False, indent=2))
    else:
        print(format_plan(progress_path=args.progress))


if __name__ == "__main__":
    main()
