#!/usr/bin/env python3
"""Zone-aware lookup smoke test.

Run:
  python tests/test_zone_aware_lookup.py

This test does not require the big SQL dump; it constructs a tiny in-memory DB
with two NPC rows that share the same name_lower but live in different zones.
"""

from __future__ import annotations

try:
    from ._bootstrap import REPO_ROOT  # type: ignore
except ImportError:
    from _bootstrap import REPO_ROOT  # type: ignore

import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from database import EQResistDatabase


def main() -> int:
    db = EQResistDatabase(":memory:")
    cur = db.conn.cursor()

    # Minimal zone data
    cur.execute("INSERT INTO zones (short_name, long_name, long_name_lower) VALUES (?, ?, ?)", ("wakening", "The Wakening Land", "the wakening land"))
    cur.execute("INSERT INTO zones (short_name, long_name, long_name_lower) VALUES (?, ?, ?)", ("karnor", "Karnor's Castle", "karnor's castle"))

    # Two NPCs with same name_lower (common in world DBs)
    cur.execute(
        "INSERT INTO npcs (id, name, name_lower, level, maxlevel, hp, mana, mindmg, maxdmg, ac, mr, cr, dr, fr, pr, special_abilities) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (1001, "a_skeleton", "a_skeleton", 10, 10, 500, 0, 5, 15, 50, 10, 10, 10, 10, 10, ""),
    )
    cur.execute(
        "INSERT INTO npcs (id, name, name_lower, level, maxlevel, hp, mana, mindmg, maxdmg, ac, mr, cr, dr, fr, pr, special_abilities) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (2002, "a_skeleton", "a_skeleton", 55, 55, 50000, 0, 100, 200, 400, 200, 200, 200, 200, 200, ""),
    )

    # Map them to different zones
    cur.execute("INSERT INTO npc_zones (npc_id, zone_short_name) VALUES (?, ?)", (1001, "wakening"))
    cur.execute("INSERT INTO npc_zones (npc_id, zone_short_name) VALUES (?, ?)", (2002, "karnor"))
    db.conn.commit()

    # Resolve long name -> short name
    zs = db.get_zone_short_name("The Wakening Land")
    assert zs == "wakening", zs

    r1 = db.get_npc_resists("a skeleton", zone_short_name="wakening")
    assert r1 and r1["npc_id"] == 1001, r1

    r2 = db.get_npc_resists("a skeleton", zone_short_name="karnor")
    assert r2 and r2["npc_id"] == 2002, r2

    r3 = db.get_npc_resists("a skeleton")
    assert r3 and r3["npc_id"] in (1001, 2002)

    print("OK: zone-aware lookup selects the correct NPC per zone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
