import os
import sqlite3
from utils import normalize_npc_name, npc_lookup_keys
from special_abilities import parse_special_abilities


class EQResistDatabase:
    """Parse SQL dump and create lightweight SQLite database"""

    def __init__(self, db_path='npc_data.db'):
        self.db_path = db_path
        self.conn = None
        self.schema_updated = False
        self.requires_reload = False
        self.init_db()

    def init_db(self):
        """Open SQLite DB and ensure schema exists."""
        self.conn = sqlite3.connect(self.db_path)
        # Older builds incorrectly enforced UNIQUE(name/name_lower), which silently
        # collapsed NPCs with the same name (often appearing in different zones).
        # Detect and migrate so we can store multiple rows per name_lower.
        try:
            if self._needs_unique_constraint_migration():
                self._migrate_remove_unique_constraints()
                self.requires_reload = True
        except Exception:
            # If migration fails, keep going; the app will still work with the old DB.
            pass

        self._ensure_schema()
        self.schema_updated = bool(self._ensure_columns())

    def _ensure_schema(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS npcs (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                name_lower TEXT NOT NULL,
                level INTEGER DEFAULT 0,
                maxlevel INTEGER DEFAULT 0,
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_npcs_name_lower ON npcs(name_lower)")

        # Zone data (optional). If loaded, we can disambiguate NPCs by zone.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS zones (
                short_name TEXT PRIMARY KEY,
                long_name TEXT DEFAULT '',
                long_name_lower TEXT DEFAULT ''
            )
        ''')
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_zones_long_name_lower ON zones(long_name_lower)")

        # Many-to-many mapping of NPC type IDs to zones.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS npc_zones (
                npc_id INTEGER NOT NULL,
                zone_short_name TEXT NOT NULL,
                PRIMARY KEY (npc_id, zone_short_name)
            )
        ''')
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_npc_zones_zone ON npc_zones(zone_short_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_npc_zones_npc ON npc_zones(npc_id)")
        self.conn.commit()

    def _needs_unique_constraint_migration(self) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='npcs'")
        row = cursor.fetchone()
        if not row or not row[0]:
            return False
        table_sql = str(row[0]).upper()
        if 'UNIQUE' in table_sql:
            return True

        # Defensive: also check any unique indexes that include name/name_lower.
        try:
            cursor.execute("PRAGMA index_list('npcs')")
            for _seq, idx_name, is_unique, *_rest in cursor.fetchall():
                if not is_unique:
                    continue
                cursor.execute(f"PRAGMA index_info('{idx_name}')")
                cols = {r[2] for r in cursor.fetchall()}
                if 'name' in cols or 'name_lower' in cols:
                    return True
        except Exception:
            pass

        return False

    def _migrate_remove_unique_constraints(self):
        cursor = self.conn.cursor()
        cursor.execute("ALTER TABLE npcs RENAME TO npcs_old")

        # Recreate with the non-unique schema.
        self._ensure_schema()

        # Copy over all columns that exist in the old table.
        cursor.execute("PRAGMA table_info('npcs_old')")
        old_cols = {row[1] for row in cursor.fetchall()}
        desired_cols = [
            'id', 'name', 'name_lower', 'level', 'maxlevel', 'hp', 'mana',
            'mindmg', 'maxdmg', 'ac', 'mr', 'cr', 'dr', 'fr', 'pr', 'special_abilities'
        ]
        copy_cols = [c for c in desired_cols if c in old_cols]
        if copy_cols:
            cols_csv = ", ".join(copy_cols)
            cursor.execute(f"INSERT OR REPLACE INTO npcs ({cols_csv}) SELECT {cols_csv} FROM npcs_old")
        cursor.execute("DROP TABLE npcs_old")
        self.conn.commit()

    def _ensure_columns(self) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(npcs)")
        cols = {row[1] for row in cursor.fetchall()}
        to_add = []
        if 'level' not in cols:
            to_add.append("ALTER TABLE npcs ADD COLUMN level INTEGER DEFAULT 0")
        if 'maxlevel' not in cols:
            to_add.append("ALTER TABLE npcs ADD COLUMN maxlevel INTEGER DEFAULT 0")
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
            return True
        return False

    def populate_from_sql(self, sql_file, clear_zone_data: bool = False):
        """Parse a SQL dump and populate database.

        Expected input is a full Quarm/eqemu world dump that includes `npc_types`
        plus zone/spawn tables (`spawn2`, `spawnentry`, `zone`). We build a compact
        `npc_zones` mapping so lookups can be filtered by current zone.
        """
        if not os.path.exists(sql_file):
            print(f"Error: {sql_file} not found")
            return False

        print(f"Loading NPC data from {sql_file}...")
        cursor = self.conn.cursor()

        # Optionally clear existing derived zone data before reloading.
        if clear_zone_data:
            try:
                cursor.execute("DELETE FROM npc_zones")
            except Exception:
                pass
            try:
                cursor.execute("DELETE FROM zones")
            except Exception:
                pass
            self.conn.commit()

        # Temp tables used only when the input file includes spawn/zone info.
        cursor.execute("DROP TABLE IF EXISTS _tmp_spawn2")
        cursor.execute("DROP TABLE IF EXISTS _tmp_spawnentry")
        cursor.execute("CREATE TABLE _tmp_spawn2 (spawngroupID INTEGER NOT NULL, zone TEXT NOT NULL)")
        cursor.execute("CREATE TABLE _tmp_spawnentry (npcID INTEGER NOT NULL, spawngroupID INTEGER NOT NULL)")
        self.conn.commit()

        try:
            current_table = None
            rows_since_commit = 0
            has_zone_spawn_data = False

            with open(sql_file, 'r', encoding='utf-8', errors='ignore') as f:
                for raw_line in f:
                    line = raw_line.strip()

                    if not line:
                        continue

                    if line.startswith('INSERT INTO'):
                        if '`npc_types`' in line:
                            current_table = 'npc_types'
                        elif '`spawn2`' in line:
                            current_table = 'spawn2'
                            has_zone_spawn_data = True
                        elif '`spawnentry`' in line:
                            current_table = 'spawnentry'
                            has_zone_spawn_data = True
                        elif '`zone`' in line:
                            current_table = 'zone'
                            has_zone_spawn_data = True
                        else:
                            current_table = None
                        continue

                    # Data rows are tuples like: (...), or (...);
                    if not line.startswith('(') or line.startswith('PRIMARY'):
                        continue

                    for tuple_line in self._iter_sql_tuple_lines(line):
                        # Extract values
                        try:
                            values = self._parse_sql_row(tuple_line)
                        except Exception:
                            continue

                        if current_table == 'npc_types':
                            try:
                                if len(values) >= 50 and values[1]:
                                    npc_id = int(values[0])
                                    name = values[1]
                                    level = int(values[3]) if values[3] else 0
                                    # npc_types column order: maxlevel is index 67 (0-based)
                                    maxlevel = int(values[67]) if len(values) > 67 and values[67] else 0
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

                                    cursor.execute(
                                        '''
                                        INSERT OR REPLACE INTO npcs (id, name, name_lower, level, maxlevel, hp, mana, mindmg, maxdmg, ac, mr, cr, dr, fr, pr, special_abilities)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        ''',
                                        (npc_id, name, name_lower, level, maxlevel, hp, mana, mindmg, maxdmg, ac, mr, cr, dr, fr, pr, special_abilities)
                                    )
                                    rows_since_commit += 1
                            except (IndexError, ValueError, sqlite3.Error):
                                continue

                        elif current_table == 'spawnentry':
                            # eqemu spawnentry: (spawngroupID, npcID, chance, ...)
                            try:
                                spawngroup_id = int(values[0])
                                npc_id = int(values[1])
                                cursor.execute(
                                    "INSERT INTO _tmp_spawnentry (npcID, spawngroupID) VALUES (?, ?)",
                                    (npc_id, spawngroup_id)
                                )
                                rows_since_commit += 1
                            except Exception:
                                continue

                        elif current_table == 'spawn2':
                            # eqemu spawn2: (id, spawngroupID, zone, ...)
                            try:
                                spawngroup_id = int(values[1])
                                zone = (values[2] or '').strip()
                                if zone:
                                    cursor.execute(
                                        "INSERT INTO _tmp_spawn2 (spawngroupID, zone) VALUES (?, ?)",
                                        (spawngroup_id, zone)
                                    )
                                    rows_since_commit += 1
                            except Exception:
                                continue

                        elif current_table == 'zone':
                            # Quarm/eqemu zone: (short_name, id, file_name, long_name, ...)
                            try:
                                short_name = (values[0] or '').strip()
                                if not short_name:
                                    continue
                                long_name = ''
                                if len(values) > 3 and values[3]:
                                    long_name = str(values[3]).strip()
                                cursor.execute(
                                    "INSERT OR REPLACE INTO zones (short_name, long_name, long_name_lower) VALUES (?, ?, ?)",
                                    (short_name, long_name, long_name.lower())
                                )
                                rows_since_commit += 1
                            except Exception:
                                continue

                        if rows_since_commit >= 5000:
                            self.conn.commit()
                            rows_since_commit = 0

            self.conn.commit()

            if has_zone_spawn_data:
                # Build compact npc_id -> zone mapping.
                cursor.execute(
                    '''
                    INSERT OR IGNORE INTO npc_zones (npc_id, zone_short_name)
                    SELECT DISTINCT se.npcID, s2.zone
                    FROM _tmp_spawnentry se
                    JOIN _tmp_spawn2 s2 ON se.spawngroupID = s2.spawngroupID
                    WHERE s2.zone IS NOT NULL AND TRIM(s2.zone) <> ''
                    '''
                )
                self.conn.commit()
            cursor.execute("SELECT COUNT(*) FROM npcs")
            count = cursor.fetchone()[0]
            print(f"Loaded {count} NPCs")

            if has_zone_spawn_data:
                try:
                    cursor.execute("SELECT COUNT(*) FROM zones")
                    zc = int(cursor.fetchone()[0] or 0)
                    cursor.execute("SELECT COUNT(*) FROM npc_zones")
                    nzc = int(cursor.fetchone()[0] or 0)
                    print(f"Loaded {zc} zones and {nzc} npc-zone mappings")
                except Exception:
                    pass

            # Drop temp tables to keep the DB compact.
            try:
                cursor.execute("DROP TABLE IF EXISTS _tmp_spawn2")
                cursor.execute("DROP TABLE IF EXISTS _tmp_spawnentry")
                self.conn.commit()
            except Exception:
                pass
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

    def _iter_sql_tuple_lines(self, line: str):
        """Yield individual tuple strings from a SQL VALUES line.

        Most dumps emit one tuple per line. Some emit many tuples on one line:
        (..),(..),(..);

        This splitter is intentionally simple (it does not try to handle the
        unlikely case where the sequence '),(' appears inside quoted text).
        """
        s = (line or '').strip()
        if not s.startswith('('):
            return

        if '),(' not in s:
            yield s
            return

        is_last_semicolon = s.endswith(');')
        if s.endswith(');') or s.endswith('),'):
            trimmed = s[:-2]
        else:
            trimmed = s

        parts = trimmed.split('),(')
        for i, part in enumerate(parts):
            if i == 0:
                tuple_str = part
            else:
                tuple_str = '(' + part

            if i == len(parts) - 1 and is_last_semicolon:
                tuple_str = tuple_str + ');'
            else:
                tuple_str = tuple_str + '),'
            yield tuple_str

    def get_zone_short_name(self, zone_name: str, cursor=None):
        """Resolve a log 'You have entered <Zone>' name to a zone short_name.

        Returns None if zone data isn't loaded or no match is found.
        """
        if not zone_name:
            return None
        cursor = cursor or self.conn.cursor()
        z = str(zone_name).strip().rstrip('.')
        zl = z.lower()
        try:
            # Prefer a non-numeric short_name and (when mappings exist) prefer one that
            # appears in npc_zones.
            cursor.execute(
                """
                SELECT z.short_name
                FROM zones z
                WHERE z.long_name_lower = ? COLLATE NOCASE
                  AND z.short_name NOT GLOB '[0-9]*'
                ORDER BY EXISTS(
                    SELECT 1 FROM npc_zones nz WHERE nz.zone_short_name = z.short_name
                ) DESC
                LIMIT 1
                """,
                (zl,),
            )
            row = cursor.fetchone()
            if row and row[0]:
                return str(row[0])
        except sqlite3.Error:
            return None

        # Fallback: user/log may already be short_name.
        try:
            cursor.execute(
                "SELECT short_name FROM zones WHERE short_name = ? COLLATE NOCASE LIMIT 1",
                (z,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                return str(row[0])
        except sqlite3.Error:
            return None
        return None

    def get_npc_resists(self, name, cursor=None, zone_short_name: str | None = None):
        """Lookup NPC resistances.

        NPC names are not unique in the source data. If multiple rows match a
        normalized name, pick a deterministic "best" match and mark the result as
        ambiguous so the UI can warn the user.
        """
        cursor = cursor or self.conn.cursor()
        debug_specials = os.environ.get('EQ_OVERLAY_DEBUG_SPECIALS') == '1'

        rows = None
        matched_key = None
        keys = npc_lookup_keys(name)
        if debug_specials:
            try:
                print(f"[DEBUG] DB.get_npc_resists name={name!r} keys={keys!r} db_path={self.db_path}")
            except Exception:
                pass
        for key in keys:
            key_l = key.lower()

            # Zone-aware lookup when we have a current zone and zone data.
            if zone_short_name:
                try:
                    cursor.execute(
                        '''
                        SELECT n.id, n.name, n.level, n.maxlevel, n.hp, n.mana, n.mindmg, n.maxdmg, n.ac,
                               n.mr, n.cr, n.dr, n.fr, n.pr, n.special_abilities
                        FROM npcs n
                        JOIN npc_zones nz ON nz.npc_id = n.id
                        WHERE n.name_lower = ? AND nz.zone_short_name = ?
                        ORDER BY n.maxlevel DESC, n.level DESC, n.hp DESC, n.id DESC
                        LIMIT 2
                        ''',
                        (key_l, zone_short_name)
                    )
                    rows = cursor.fetchall()
                    if rows:
                        matched_key = key
                        break
                except sqlite3.Error:
                    # Zone tables not present / not loaded.
                    pass

            # Fallback: global lookup by name.
            cursor.execute(
                '''
                SELECT id, name, level, maxlevel, hp, mana, mindmg, maxdmg, ac, mr, cr, dr, fr, pr, special_abilities
                FROM npcs
                WHERE name_lower = ?
                ORDER BY maxlevel DESC, level DESC, hp DESC, id DESC
                LIMIT 2
                ''',
                (key_l,)
            )
            rows = cursor.fetchall()
            if rows:
                matched_key = key
                break

        if rows:
            result = rows[0]
            ambiguous = len(rows) > 1
            match_count = None
            if ambiguous:
                try:
                    if zone_short_name:
                        cursor.execute(
                            "SELECT COUNT(*) FROM npcs n JOIN npc_zones nz ON nz.npc_id = n.id WHERE n.name_lower = ? AND nz.zone_short_name = ?",
                            (matched_key.lower(), zone_short_name)
                        )
                    else:
                        cursor.execute("SELECT COUNT(*) FROM npcs WHERE name_lower = ?", (matched_key.lower(),))
                    match_count = int(cursor.fetchone()[0] or 0)
                except Exception:
                    match_count = None

            special_raw = result[14] if len(result) > 14 else ''
            special_labels = parse_special_abilities(special_raw) if special_raw else ''
            if debug_specials:
                try:
                    print(f"[DEBUG] DB matched_key={matched_key!r} db_name={result[0]!r}")
                    print(f"[DEBUG] DB special_raw={special_raw!r} (len={len(special_raw) if special_raw is not None else 'None'})")
                    print(f"[DEBUG] DB special_labels={special_labels!r}")
                except Exception:
                    pass
            return {
                'npc_id': result[0],
                'name': result[1],
                'level': result[2],
                'maxlevel': result[3],
                'hp': result[4],
                'mana': result[5],
                'mindmg': result[6],
                'maxdmg': result[7],
                'ac': result[8],
                'MR': result[9],
                'CR': result[10],
                'DR': result[11],
                'FR': result[12],
                'PR': result[13],
                'special_abilities': special_raw,
                'special_abilities_labels': special_labels,
                'ambiguous': ambiguous,
                'match_count': match_count,
                'matched_key': matched_key,
                'zone_short_name': zone_short_name,
            }
        return None
