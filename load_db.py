#!/usr/bin/env python3
import argparse
from pathlib import Path

from database import EQResistDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description="Build npc_data.db from a Quarm/eqemu SQL dump")
    parser.add_argument(
        "--sql",
        default="quarm.sql",
        help="Path to SQL dump (expected: full Quarm/eqemu dump like quarm.sql or quarm_*.sql)",
    )
    parser.add_argument("--out", default="npc_data.db", help="Output SQLite DB path")
    args = parser.parse_args()

    sql_file = Path(args.sql)
    db_path = Path(args.out)

    if not sql_file.exists():
        print(f"SQL file not found: {sql_file}")
        return 1

    db_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading {sql_file} into {db_path}...")
    db = EQResistDatabase(str(db_path))
    clear_zone = sql_file.name.lower().startswith('quarm')
    ok = db.populate_from_sql(str(sql_file), clear_zone_data=clear_zone)
    if not ok:
        return 1

    try:
        cur = db.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM npcs")
        final_count = int(cur.fetchone()[0] or 0)
        print(f"Loaded {final_count} NPCs total")
        cur.execute("SELECT COUNT(*) FROM npc_zones")
        nz = int(cur.fetchone()[0] or 0)
        if nz:
            print(f"Loaded {nz} npc-zone mappings")
    except Exception:
        pass
    try:
        db.conn.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
