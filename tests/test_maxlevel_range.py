#!/usr/bin/env python3
"""Smoke test for maxlevel support.

- Confirms the `npcs` table has a `maxlevel` column.
- Finds a few NPCs where maxlevel != level and prints the display text.
- Includes lightweight formatting assertions matching the GUI behavior.

Run:
  python tests/test_maxlevel_range.py
  python -m tests.test_maxlevel_range
"""

from __future__ import annotations

from pathlib import Path

try:
    from ._bootstrap import REPO_ROOT
except ImportError:
    from _bootstrap import REPO_ROOT  # type: ignore

from database import EQResistDatabase
from utils import format_level_text


def _pick_db_path() -> Path:
    for p in (REPO_ROOT / "npc_data.db", REPO_ROOT / "dist" / "npc_data.db"):
        if p.exists():
            return p
    return REPO_ROOT / "npc_data.db"


def main() -> int:
    assert format_level_text(10, 10) == "10"
    assert format_level_text("10", "11") == "10-11"
    assert format_level_text(11, 10) == "10-11"
    assert format_level_text("--", 0) == "--"

    db_path = _pick_db_path()
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        print("Run the app once (or run load_db.py) to create/populate npc_data.db.")
        return 0

    db = EQResistDatabase(str(db_path))
    cursor = db.conn.cursor()

    cursor.execute("PRAGMA table_info(npcs)")
    cols = {row[1] for row in cursor.fetchall()}
    if "maxlevel" not in cols:
        print("Column missing: npcs.maxlevel")
        return 1

    maxlevel_count = 0
    try:
        cursor.execute("SELECT COUNT(*) FROM npcs WHERE maxlevel IS NOT NULL AND maxlevel <> 0")
        maxlevel_count = int(cursor.fetchone()[0] or 0)
    except Exception:
        maxlevel_count = 0

    # NOTE: This repo no longer ships npc_types.sql. If maxlevel is unpopulated,
    # rebuild your DB from a full Quarm dump (quarm.sql / quarm_*.sql).

    cursor.execute(
        """
        SELECT name, level, maxlevel
        FROM npcs
        WHERE level IS NOT NULL
          AND maxlevel IS NOT NULL
          AND level <> 0
          AND maxlevel <> 0
          AND maxlevel <> level
        LIMIT 5
        """
    )
    rows = cursor.fetchall()

    if not rows:
        print("No NPCs found where maxlevel != level (unexpected, but not fatal).")
        return 0

    print("NPCs with level ranges:")
    for name, level, maxlevel in rows:
        level_text = format_level_text(level, maxlevel)
        print(f"  {name} | level={level} maxlevel={maxlevel} -> Lv:{level_text}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
