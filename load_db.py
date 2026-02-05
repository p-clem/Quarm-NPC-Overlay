#!/usr/bin/env python3
import argparse
import os
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build npc_data.db from npc_types.sql")
    parser.add_argument("--sql", default="npc_types.sql", help="Path to npc_types.sql")
    parser.add_argument("--out", default="npc_data.db", help="Output SQLite DB path")
    args = parser.parse_args()

    sql_file = Path(args.sql)
    db_path = Path(args.out)

    if not sql_file.exists():
        print(f"SQL file not found: {sql_file}")
        return 1

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS npcs (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        name_lower TEXT UNIQUE NOT NULL,
        level INTEGER DEFAULT 0,
        hp INTEGER DEFAULT 0,
        mana INTEGER DEFAULT 0,
        mindmg INTEGER DEFAULT 0,
        maxdmg INTEGER DEFAULT 0,
        ac INTEGER DEFAULT 0,
        mr INTEGER DEFAULT 0,
        cr INTEGER DEFAULT 0,
        dr INTEGER DEFAULT 0,
        fr INTEGER DEFAULT 0,
        pr INTEGER DEFAULT 0,
        special_abilities TEXT DEFAULT NULL
    )
''')
    conn.commit()

    print(f"Loading {sql_file} into {db_path}...")

    with open(sql_file, 'r', encoding='utf-8', errors='ignore') as f:
        for raw_line in f:
            line = raw_line
            if line.startswith('(') and not line.startswith('PRIMARY'):
                try:
                    # Parse CSV-like SQL values line
                    line = line.strip()[1:-2]  # Remove ( and ),

                    values = []
                    in_quotes = False
                    current = ''

                    for i, char in enumerate(line):
                        if char == "'" and (i == 0 or line[i-1] != '\\'):
                            in_quotes = not in_quotes
                        elif char == ',' and not in_quotes:
                            values.append(current.strip().strip("'"))
                            current = ''
                            continue
                        current += char

                    if current:
                        values.append(current.strip().strip("'"))

                    if len(values) >= 50 and values[1]:
                        name = values[1]
                        name_lower = name.lstrip('#').replace(' ', '_').lower()
                        level = int(values[3]) if values[3] else 0
                        hp = int(values[7]) if values[7] else 0
                        mana = int(values[8]) if values[8] else 0
                        mindmg = int(values[20]) if len(values) > 20 and values[20] else 0
                        maxdmg = int(values[21]) if len(values) > 21 and values[21] else 0
                        special_abilities = values[23] if len(values) > 23 else ''
                        mr = int(values[43]) if values[43] else 0
                        cr = int(values[44]) if values[44] else 0
                        dr = int(values[45]) if values[45] else 0
                        fr = int(values[46]) if values[46] else 0
                        pr = int(values[47]) if values[47] else 0
                        ac = int(values[51]) if len(values) > 51 and values[51] else 0

                        cursor.execute('''
                            INSERT OR REPLACE INTO npcs (id, name, name_lower, level, hp, mana, mindmg, maxdmg, ac, mr, cr, dr, fr, pr, special_abilities)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (values[0], name, name_lower, level, hp, mana, mindmg, maxdmg, ac, mr, cr, dr, fr, pr, special_abilities))
                except Exception:
                    continue

    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM npcs")
    final_count = cursor.fetchone()[0]
    print(f"Loaded {final_count} NPCs total")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
