"""Merge a run's post and topic history into the current main checkout.

The posting workflow saves its history after waiting up to hours for approval, and main may have
gained entries in the meantime. A git merge of two appended JSON lists always conflicts, so this
keeps main's entries and appends the run's entries that main does not have yet.

Usage: python scripts/merge_history.py <dir with the run's posted.json and topic_history.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _key(entry) -> str:
    return json.dumps(entry, sort_keys=True, ensure_ascii=False)


def merge_lists(main: list, run: list) -> list:
    seen = {_key(e) for e in main}
    return main + [e for e in run if _key(e) not in seen]


def merge_file(main_path: Path, run_path: Path) -> None:
    if not run_path.exists():
        return
    run = json.loads(run_path.read_text() or "[]")
    main = json.loads(main_path.read_text() or "[]") if main_path.exists() else []
    if not isinstance(main, list) or not isinstance(run, list):
        main_path.write_text(run_path.read_text())  # not a log: the run's copy is the newest
        return
    main_path.write_text(json.dumps(merge_lists(main, run), indent=2, ensure_ascii=False) + "\n")


def main(run_dir: str, target: str = ".") -> None:
    src, dst = Path(run_dir), Path(target)
    for name in ("posted.json", "topic_history.json"):
        merge_file(dst / name, src / name)


if __name__ == "__main__":
    main(*sys.argv[1:])
