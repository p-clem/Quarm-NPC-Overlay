import os
import re
import time
import sqlite3
import traceback
from pathlib import Path
from utils import npc_lookup_keys
from special_abilities import parse_special_abilities


class EQLogWatcher:
    """Monitor EverQuest log file for 'consider' commands"""

    def __init__(self, db, callback, config=None):
        self.db = db
        self.db_path = db.db_path  # Store path to recreate connection in thread
        self.callback = callback
        self.config = config
        self.last_position = 0
        self._last_missing_config_path = None
        self.log_file = self._find_eq_log()
        self.first_run = True
        self.current_zone_long = None
        self.current_zone_short = None
        # Compile consider regex once
        self.consider_re = re.compile(
            r'^(?P<target>.*?)\s+(?P<faction>scowls|glar(?:es|es).*?|glowers|is|looks|judges?|kindly|regards).*?(?P<sep>-- )?(?P<diff>.*)?$',
            re.IGNORECASE
        )
        self.entered_re = re.compile(r'^You have entered (?P<zone>.+?)\.$', re.IGNORECASE)

    def _find_eq_log(self):
        """Find the EQ log file.

        This app does not auto-detect log locations; the user must explicitly set
        the EQ log file path in settings.
        """
        if not self.config:
            return None

        configured_path = self.config.get_eq_log_path()
        if not configured_path:
            self._last_missing_config_path = None
            return None

        configured = Path(configured_path)
        if configured.exists():
            self._last_missing_config_path = None
            return configured

        if configured_path != self._last_missing_config_path:
            print(f"Configured log path does not exist: {configured_path}")
            self._last_missing_config_path = configured_path
        return None

    def watch(self):
        """Start watching the log file"""
        # Create a new database connection in this thread
        db_conn = sqlite3.connect(self.db_path)
        debug_specials = os.environ.get('EQ_OVERLAY_DEBUG_SPECIALS') == '1'

        print("Watcher thread started - waiting for EQ log file...")
        try:
            if self.log_file:
                print(f"Watching log file: {self.log_file}")
            else:
                configured_path = self.config.get_eq_log_path() if self.config else None
                if configured_path:
                    print(f"Configured log path not found yet: {configured_path}")
                else:
                    print("No EQ log path configured. Open settings to select eqlog_*.txt")
        except Exception:
            pass

        while True:
            try:
                # Check for updated log file path from config.
                # If the user selects a new file, switch without restarting.
                if self.config:
                    configured_path = self.config.get_eq_log_path()
                    if configured_path:
                        candidate = Path(configured_path)
                        if candidate.exists() and (not self.log_file or candidate != self.log_file):
                            self.log_file = candidate
                            print(f"Watching log file: {self.log_file}")
                            self.first_run = True
                            self.last_position = 0

                if not self.log_file:
                    self.log_file = self._find_eq_log()
                    if self.log_file:
                        print(f"Watching log file: {self.log_file}")
                        self.first_run = True
                        self.last_position = 0

                if not self.log_file:
                    # Still no log file, wait and retry
                    time.sleep(1)
                    continue

                # Handle log truncation/rotation (file shrank)
                try:
                    current_size = self.log_file.stat().st_size
                    if current_size < self.last_position:
                        print("Log file size decreased; resetting watcher position")
                        self.last_position = 0
                        self.first_run = True
                except Exception:
                    pass

                if self.log_file.stat().st_size > self.last_position:
                    with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        # On first run, skip to end of file so we only catch NEW considers
                        if self.first_run:
                            f.seek(0, 2)  # Seek to end
                            self.last_position = f.tell()
                            self.first_run = False
                            print("Watcher initialized - watching for NEW considers")
                        else:
                            f.seek(self.last_position)

                            # If last_position landed mid-line, discard the partial line
                            if self.last_position > 0:
                                try:
                                    f.seek(self.last_position - 1)
                                    prev_char = f.read(1)
                                    f.seek(self.last_position)
                                    if prev_char != '\n':
                                        f.readline()
                                except Exception:
                                    pass

                            for line in f:
                                # Remove timestamp prefix [Day Mon DD HH:MM:SS YYYY]
                                clean_line = re.sub(r'^\[.*?\]\s+', '', line.strip())

                                # Track current zone (helps disambiguate NPCs with non-unique names)
                                try:
                                    m_zone = self.entered_re.match(clean_line)
                                    if m_zone:
                                        zone_long = (m_zone.group('zone') or '').strip()
                                        self.current_zone_long = zone_long
                                        try:
                                            zcur = db_conn.cursor()
                                            self.current_zone_short = self.db.get_zone_short_name(zone_long, cursor=zcur)
                                        except Exception:
                                            self.current_zone_short = None
                                        if self.current_zone_short:
                                            print(f"[ZONE] Entered {zone_long} ({self.current_zone_short})")
                                        else:
                                            print(f"[ZONE] Entered {zone_long}")
                                except Exception:
                                    pass

                                # Match proper EQ consider format
                                match = self.consider_re.match(clean_line)
                                if match:
                                    npc_name = match.group('target').strip()
                                    print(f"Found consider: {npc_name}")
                                    if debug_specials:
                                        try:
                                            print(f"[DEBUG] db_path={self.db_path}")
                                            print(f"[DEBUG] raw_line={line.strip()!r}")
                                            print(f"[DEBUG] clean_line={clean_line!r}")
                                            print(f"[DEBUG] consider target={npc_name!r} faction={match.group('faction')!r} diff={match.group('diff')!r}")
                                        except Exception:
                                            pass

                                    cursor = db_conn.cursor()
                                    resists = self.db.get_npc_resists(
                                        npc_name,
                                        cursor=cursor,
                                        zone_short_name=self.current_zone_short,
                                    )
                                    if resists:
                                        # Always include current zone context for display.
                                        resists['current_zone_long'] = self.current_zone_long
                                        resists['current_zone_short'] = self.current_zone_short

                                        # Prefer the in-game name for display, with a small ambiguity marker.
                                        display_name = npc_name
                                        if resists.get('ambiguous'):
                                            display_name = f"{npc_name} (?)"
                                        resists['display_name'] = display_name

                                        try:
                                            zs = self.current_zone_short
                                            zl = self.current_zone_long
                                            if zl and not zs:
                                                print(f"[WARN] Zone known but not resolved to short_name: {zl!r}; zone-filtered lookup disabled")
                                            print(f"[LOOKUP] zone_short={zs!r} npc={npc_name!r} ambiguous={bool(resists.get('ambiguous'))}")
                                        except Exception:
                                            pass

                                        print(
                                            f"Match found: {npc_name} - MR:{resists['MR']} CR:{resists['CR']} "
                                            f"DR:{resists['DR']} FR:{resists['FR']} PR:{resists['PR']}"
                                        )
                                        if resists.get('ambiguous'):
                                            mc = resists.get('match_count')
                                            mc_txt = f"{mc}" if isinstance(mc, int) and mc > 0 else "multiple"
                                            print(f"[WARN] Ambiguous NPC name: {npc_name} matched {mc_txt} DB rows; showing best guess")
                                        self.callback(resists)
                                    else:
                                        print(f"No resists found for: {npc_name}")

                            self.last_position = self.log_file.stat().st_size

                time.sleep(0.5)
            except Exception as e:
                print(f"Error watching log: {e}")
                traceback.print_exc()
                time.sleep(1)
