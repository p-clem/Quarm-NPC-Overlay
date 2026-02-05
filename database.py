import os
import sqlite3
from utils import normalize_npc_name, npc_lookup_keys
from special_abilities import parse_special_abilities


class EQResistDatabase:
    """Parse SQL dump and create lightweight SQLite database"""

    def __init__(self, db_path='npc_data.db'):
        self.db_path = db_path
        self.conn = None
        self.init_db()

    def init_db(self):
        """Open SQLite DB and ensure schema exists."""
        self.conn = sqlite3.connect(self.db_path)
        cursor = self.conn.cursor()
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
        self.conn.commit()
        self._ensure_columns()

    def _ensure_columns(self):
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(npcs)")
        cols = {row[1] for row in cursor.fetchall()}
        to_add = []
        if 'level' not in cols:
            to_add.append("ALTER TABLE npcs ADD COLUMN level INTEGER DEFAULT 0")
        if 'hp' not in cols:
            to_add.append("ALTER TABLE npcs ADD COLUMN hp INTEGER DEFAULT 0")
        if 'mana' not in cols:
            to_add.append("ALTER TABLE npcs ADD COLUMN mana INTEGER DEFAULT 0")
        if 'mindmg' not in cols:
            to_add.append("ALTER TABLE npcs ADD COLUMN mindmg INTEGER DEFAULT 0")
        if 'maxdmg' not in cols:
            to_add.append("ALTER TABLE npcs ADD COLUMN maxdmg INTEGER DEFAULT 0")
        if 'ac' not in cols:
            to_add.append("ALTER TABLE npcs ADD COLUMN ac INTEGER DEFAULT 0")
        if 'special_abilities' not in cols:
            to_add.append("ALTER TABLE npcs ADD COLUMN special_abilities TEXT")

        for stmt in to_add:
            cursor.execute(stmt)
        if to_add:
            self.conn.commit()

    def populate_from_sql(self, sql_file):
        """Parse SQL dump and populate database"""
        if not os.path.exists(sql_file):
            print(f"Error: {sql_file} not found")
            return False

        print(f"Loading NPC data from {sql_file}...")
        cursor = self.conn.cursor()

        try:
            with open(sql_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # Match: (id,'name','lastname',level,race,class,...,MR,CR,DR,FR,PR,...)
                    if line.startswith('(') and not line.startswith('PRIMARY'):
                        try:
                            # Extract values - the pattern is consistent in npc_types
                            values = self._parse_sql_row(line)
                            if len(values) >= 50 and values[1]:
                                name = values[1]
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

                                name_lower = normalize_npc_name(name).lower()

                                try:
                                    cursor.execute('''
                                        INSERT OR REPLACE INTO npcs (id, name, name_lower, level, hp, mana, mindmg, maxdmg, ac, mr, cr, dr, fr, pr, special_abilities)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ''', (values[0], name, name_lower, level, hp, mana, mindmg, maxdmg, ac, mr, cr, dr, fr, pr, special_abilities))
                                except sqlite3.IntegrityError:
                                    pass  # Duplicate, skip
                        except (IndexError, ValueError):
                            continue

            self.conn.commit()
            cursor.execute("SELECT COUNT(*) FROM npcs")
            count = cursor.fetchone()[0]
            print(f"Loaded {count} NPCs")
            return True
        except Exception as e:
            print(f"Error parsing SQL: {e}")
            return False

    def _parse_sql_row(self, line):
        """Extract values from SQL INSERT line"""
        # Remove leading ( and trailing ),
        line = line.strip()[1:-2]

        values = []
        in_quotes = False
        current = ''
        i = 0

        while i < len(line):
            char = line[i]

            if char == "'" and (i == 0 or line[i-1] != '\\'):
                in_quotes = not in_quotes
            elif char == ',' and not in_quotes:
                values.append(current.strip().strip("'"))
                current = ''
                i += 1
                continue

            current += char
            i += 1

        if current:
            values.append(current.strip().strip("'"))

        return values

    def get_npc_resists(self, name):
        """Lookup NPC resistances - handle space/underscore conversion"""
        cursor = self.conn.cursor()
        debug_specials = os.environ.get('EQ_OVERLAY_DEBUG_SPECIALS') == '1'

        result = None
        matched_key = None
        keys = npc_lookup_keys(name)
        if debug_specials:
            try:
                print(f"[DEBUG] DB.get_npc_resists name={name!r} keys={keys!r} db_path={self.db_path}")
            except Exception:
                pass
        for key in keys:
            cursor.execute('''
                SELECT name, level, hp, mana, mindmg, maxdmg, ac, mr, cr, dr, fr, pr, special_abilities FROM npcs WHERE name_lower = ?
            ''', (key.lower(),))
            result = cursor.fetchone()
            if result:
                matched_key = key
                break

        if result:
            special_raw = result[12] if len(result) > 12 else ''
            special_labels = parse_special_abilities(special_raw) if special_raw else ''
            if debug_specials:
                try:
                    print(f"[DEBUG] DB matched_key={matched_key!r} db_name={result[0]!r}")
                    print(f"[DEBUG] DB special_raw={special_raw!r} (len={len(special_raw) if special_raw is not None else 'None'})")
                    print(f"[DEBUG] DB special_labels={special_labels!r}")
                except Exception:
                    pass
            return {
                'name': result[0],
                'level': result[1],
                'hp': result[2],
                'mana': result[3],
                'mindmg': result[4],
                'maxdmg': result[5],
                'ac': result[6],
                'MR': result[7],
                'CR': result[8],
                'DR': result[9],
                'FR': result[10],
                'PR': result[11],
                'special_abilities': special_raw,
                'special_abilities_labels': special_labels,
            }
        return None
