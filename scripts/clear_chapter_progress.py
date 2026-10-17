"""Clear the chapter story progress so the next room entry is a first run.

The chapter state lives in two places:
  CharacterChapterStory  - objective index, clear mask, reward flag
  CharacterTasks         - the fixed task slot the client shows in its list

Usage (client may stay open, but closing it avoids a write race):
  python -B scripts/clear_chapter_progress.py
  python -B scripts/clear_chapter_progress.py --client <client root>

The default client root is the deployment directory this repository sits in
(one level up); pass --client when the client lives elsewhere.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DB_RELATIVE = Path("adapter_data") / "game.db"
FIRST_CHAPTER, LAST_CHAPTER = 73_000_000, 73_000_015


def default_client() -> Path:
    """Client root without a host-specific literal.

    This repository is normally a checkout one level below the deployed client,
    so the parent directory wins when it holds the adapter database; a release
    layout keeps both in the same directory.
    """
    here = Path(__file__).resolve().parents[1]
    for candidate in (here.parent, here):
        if (candidate / DB_RELATIVE).is_file():
            return candidate
    return here.parent


DEFAULT_CLIENT = default_client()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", type=Path, default=DEFAULT_CLIENT,
                        help="client root that holds adapter_data/game.db")
    args = parser.parse_args(argv)
    db = Path(args.client) / DB_RELATIVE
    if not db.is_file():
        print(f"missing database: {db}", file=sys.stderr)
        return 1

    connection = sqlite3.connect(db, timeout=10)
    try:
        stories = connection.execute(
            "SELECT CharacterId, ObjectiveIndex, ClearMask, RewardPending FROM CharacterChapterStory"
        ).fetchall()
        slots = connection.execute(
            "SELECT COUNT(*) FROM CharacterTasks WHERE QuestId BETWEEN ? AND ?",
            (FIRST_CHAPTER, LAST_CHAPTER),
        ).fetchone()[0]
        print(f"before: {len(stories)} story rows, objective max "
              f"{max((row[1] for row in stories), default=0)}, {slots} chapter task slot(s)")

        connection.execute(
            "UPDATE CharacterChapterStory SET ObjectiveIndex=0, ClearMask=0, "
            "RewardPending=0, Finished=0, Revision=Revision+1")
        connection.execute(
            "DELETE FROM CharacterTasks WHERE QuestId BETWEEN ? AND ?",
            (FIRST_CHAPTER, LAST_CHAPTER))
        connection.commit()

        after = connection.execute(
            "SELECT COUNT(*), MAX(ObjectiveIndex), MAX(ClearMask) FROM CharacterChapterStory"
        ).fetchone()
        left = connection.execute(
            "SELECT COUNT(*) FROM CharacterTasks WHERE QuestId BETWEEN ? AND ?",
            (FIRST_CHAPTER, LAST_CHAPTER),
        ).fetchone()[0]
        print(f"after : {after[0]} story rows, objective max {after[1]}, mask max {after[2]}, "
              f"{left} chapter task slot(s)")
        for row in connection.execute(
            "SELECT s.CharacterId, c.Name, s.ObjectiveIndex, s.ClearMask, s.Revision "
            "FROM CharacterChapterStory s JOIN Characters c ON c.Id = s.CharacterId "
            "ORDER BY s.CharacterId"):
            print(f"  id={row[0]:<3} {row[1]:<12} objective={row[2]} mask={row[3]} revision={row[4]}")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())