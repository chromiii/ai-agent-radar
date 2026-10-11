"""Roll historical *raw reports* off the active public branch after weekly delivery.

Learning progress, curriculum, Breaking decisions and GitHub Secrets are never
retention targets. Git commit history is not rewritten.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATE_MD = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
RAW_DIRS = ("inbox", "company")


def expired_reports(root: Path, *, as_of: dt.date,
                    raw_days: int = 14, weekly_keep: int = 2,
                    briefing_keep: int = 4) -> list[Path]:
    if not 7 <= raw_days <= 90 or not 1 <= weekly_keep <= 12 or not 1 <= briefing_keep <= 12:
        raise ValueError("invalid retention interval")
    selected: list[Path] = []
    threshold = as_of - dt.timedelta(days=raw_days - 1)
    for folder in RAW_DIRS:
        for path in sorted((root / folder).glob("*.md")):
            if not DATE_MD.fullmatch(path.name):
                continue
            try:
                date = dt.date.fromisoformat(path.stem)
            except ValueError:
                continue
            if date < threshold:
                selected.append(path)

    # Preserve the latest distinct Weekly/Briefing issues, not months of archives.
    for folder, keep in (("weekly", weekly_keep), ("briefings", briefing_keep)):
        files = sorted([p for p in (root / folder).glob("*.md") if DATE_MD.fullmatch(p.name)])
        for path in files[:-keep]:
            selected.append(path)
            if folder == "briefings":
                html_path = path.with_suffix(".html")
                if html_path.exists():
                    selected.append(html_path)
    return selected


def main() -> None:
    from radar import today_local

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--raw-days", type=int, default=14)
    parser.add_argument("--weekly-keep", type=int, default=2)
    parser.add_argument("--briefing-keep", type=int, default=4)
    parser.add_argument("--apply", action="store_true", help="Actually delete expired raw report files")
    args = parser.parse_args()
    selected = expired_reports(
        ROOT, as_of=args.as_of or today_local(), raw_days=args.raw_days,
        weekly_keep=args.weekly_keep, briefing_keep=args.briefing_keep,
    )
    for path in selected:
        print(path.relative_to(ROOT).as_posix())
        if args.apply:
            path.unlink()
    print(f"{'Deleted' if args.apply else 'Would delete'} {len(selected)} old report files.")


if __name__ == "__main__":
    main()
