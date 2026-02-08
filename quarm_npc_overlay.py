import os
import sys
import traceback
from pathlib import Path
from datetime import datetime

# Setup logging before anything else
# In packaged builds, we redirect stdout/stderr to overlay.log (there's no console).
# When running from source, keep console output by default; opt-in via EQ_OVERLAY_LOG_TO_FILE=1.
log_path = Path(__file__).parent / 'overlay.log' if not hasattr(sys, 'frozen') else Path(sys.executable).parent / 'overlay.log'
_no_console = (sys.stdout is None) or (sys.stderr is None)
_log_to_file = hasattr(sys, 'frozen') or _no_console or os.environ.get('EQ_OVERLAY_LOG_TO_FILE') == '1'
if _log_to_file:
    try:
        log_file = open(str(log_path), 'a', encoding='utf-8', buffering=1)
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = log_file
        sys.stderr = log_file
    except Exception:
        pass

from config_manager import ConfigManager
from database import EQResistDatabase
from log_watcher import EQLogWatcher
from gui import ResistOverlayGUI, HAS_TK, tk, messagebox


def main():
    try:
        # Get script directory - handle PyInstaller onefile extraction
        if hasattr(sys, 'frozen'):
            script_dir = Path(sys.executable).parent
            resource_dir = Path(getattr(sys, '_MEIPASS', script_dir))
        else:
            script_dir = Path(__file__).parent
            resource_dir = script_dir

        db_path = script_dir / 'npc_data.db'

        # DB source: require a full Quarm/eqemu SQL dump (zone/spawn aware).
        # Look for `quarm.sql` first, then any `quarm*.sql` (e.g. quarm_YYYY-....sql).
        sql_path = None
        quarm_candidates = []
        for base in (script_dir, resource_dir):
            try:
                p = base / 'quarm.sql'
                if p.exists():
                    quarm_candidates.append(p)
            except Exception:
                pass
            try:
                quarm_candidates.extend(sorted(base.glob('quarm*.sql')))
            except Exception:
                pass

        quarm_candidates = [p for p in quarm_candidates if getattr(p, 'exists', lambda: False)()]
        if quarm_candidates:
            # Pick the most recently modified candidate.
            try:
                sql_path = max(quarm_candidates, key=lambda p: p.stat().st_mtime_ns)
            except Exception:
                sql_path = quarm_candidates[0]

        print(f"Script dir: {script_dir}")
        print(f"SQL path: {sql_path}")
        print(f"SQL exists: {bool(sql_path and sql_path.exists())}")

        print("=" * 50)
        print("Quarm NPC Overlay")
        print(f"Starting at {datetime.now()}")
        print("=" * 50)

        # Load configuration
        config = ConfigManager()
        try:
            print(
                f"Config: show_stats={config.get_show_stats()} "
                f"show_resists={config.get_show_resists()} "
                f"show_special_abilities={config.get_show_special_abilities()} "
                f"overlay_opacity={config.get_overlay_opacity()}"
            )
            print(f"Config log path: {config.get_eq_log_path()}")
        except Exception:
            pass

        # Initialize database
        db = EQResistDatabase(str(db_path))

        # Check if we need to populate from SQL
        cursor = db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM npcs")
        count = cursor.fetchone()[0]

        print(f"Database has {count} NPCs")

        # If the DB existed from an older build/run, it may not have populated special_abilities.
        # In that case, reload from the bundled SQL to backfill without requiring a manual rebuild.
        special_count = 0
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM npcs WHERE special_abilities IS NOT NULL AND TRIM(special_abilities) <> ''"
            )
            special_count = int(cursor.fetchone()[0] or 0)
        except Exception:
            special_count = 0
        print(f"Database has {special_count} NPCs with special abilities")

        stats_count = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM npcs WHERE level IS NOT NULL AND level <> 0")
            stats_count = int(cursor.fetchone()[0] or 0)
        except Exception:
            stats_count = 0
        print(f"Database has {stats_count} NPCs with stats")

        dmg_count = 0
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM npcs WHERE (mindmg IS NOT NULL AND mindmg <> 0) OR (maxdmg IS NOT NULL AND maxdmg <> 0)"
            )
            dmg_count = int(cursor.fetchone()[0] or 0)
        except Exception:
            dmg_count = 0
        print(f"Database has {dmg_count} NPCs with min/max damage")

        maxlevel_count = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM npcs WHERE maxlevel IS NOT NULL AND maxlevel <> 0")
            maxlevel_count = int(cursor.fetchone()[0] or 0)
        except Exception:
            maxlevel_count = 0
        print(f"Database has {maxlevel_count} NPCs with maxlevel")

        zone_map_count = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM npc_zones")
            zone_map_count = int(cursor.fetchone()[0] or 0)
        except Exception:
            zone_map_count = 0
        if zone_map_count:
            print(f"Database has {zone_map_count} npc-zone mappings")
        else:
            print("Database has 0 npc-zone mappings")

        zones_ok = False
        try:
            cursor.execute("SELECT COUNT(*) FROM zones")
            z_total = int(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT COUNT(*) FROM zones WHERE short_name NOT GLOB '[0-9]*'")
            z_non_numeric = int(cursor.fetchone()[0] or 0)
            zones_ok = (z_total > 0 and z_non_numeric > 0)
        except Exception:
            zones_ok = False

        needs_backfill = (count > 0 and (special_count == 0 or stats_count == 0 or dmg_count == 0 or maxlevel_count == 0))
        needs_reload = bool(getattr(db, 'requires_reload', False))
        needs_zone_backfill = (count > 0 and (zone_map_count == 0 or not zones_ok))

        # Auto-refresh DB if the SQL dump changed.
        needs_sql_refresh = False
        sql_sig = None
        if sql_path and sql_path.exists():
            try:
                cursor.execute("CREATE TABLE IF NOT EXISTS db_meta (key TEXT PRIMARY KEY, value TEXT)")
                cursor.execute("SELECT value FROM db_meta WHERE key='source_signature'")
                prev = cursor.fetchone()
                prev_sig = prev[0] if prev and prev[0] else None
                st = sql_path.stat()
                sql_sig = f"{str(sql_path.resolve())}|{st.st_mtime_ns}|{st.st_size}"
                needs_sql_refresh = (prev_sig != sql_sig)
            except Exception:
                needs_sql_refresh = False

        if (count == 0 or needs_backfill or needs_reload or needs_zone_backfill or needs_sql_refresh):
            if sql_path and sql_path.exists():
                if needs_sql_refresh:
                    print(f"Refreshing DB from {sql_path} (SQL dump changed)")
                elif needs_reload:
                    print(f"Reloading DB from {sql_path} (schema migration)")
                elif needs_zone_backfill:
                    print(f"Backfilling zone/spawn mappings from {sql_path}")
                elif count == 0:
                    print(f"Loading from {sql_path}")
                else:
                    print(f"Backfilling data from {sql_path}")

                # Quarm dumps include zone/spawn tables, so always rebuild zone mapping.
                db.populate_from_sql(str(sql_path), clear_zone_data=True)
                if sql_sig:
                    try:
                        cursor.execute("CREATE TABLE IF NOT EXISTS db_meta (key TEXT PRIMARY KEY, value TEXT)")
                        cursor.execute(
                            "INSERT OR REPLACE INTO db_meta(key,value) VALUES('source_signature', ?)",
                            (sql_sig,),
                        )
                        cursor.execute(
                            "INSERT OR REPLACE INTO db_meta(key,value) VALUES('source_sql', ?)",
                            (str(sql_path.name),),
                        )
                        db.conn.commit()
                    except Exception:
                        pass
            else:
                msg = (
                    "Database needs to be (re)built, but no Quarm SQL dump was found.\n\n"
                    "Releases normally ship with npc_data.db and do not require any SQL.\n"
                    "If your npc_data.db is missing/corrupt, place a full Quarm/eqemu dump next to the EXE/script as 'quarm.sql' (or 'quarm_*.sql') and restart."
                )
                print("Warning: no quarm.sql / quarm*.sql found")
                print(msg)
                try:
                    if HAS_TK:
                        messagebox.showwarning("Quarm NPC Overlay", msg)
                except Exception:
                    pass

        # Create GUI overlay
        if HAS_TK:
            root = tk.Tk()
            overlay = ResistOverlayGUI(root, config)

            def _prompt_for_log_path_if_needed():
                try:
                    p = config.get_eq_log_path()
                    if not p or not Path(p).exists():
                        overlay.open_settings()
                except Exception:
                    pass

            root.after(250, _prompt_for_log_path_if_needed)

            def on_npc_consider(resists):
                try:
                    overlay.update_display(resists)
                    root.update()
                except Exception as e:
                    print(f"Error updating display: {e}")
                    traceback.print_exc()

            # Start watcher in background
            watcher = EQLogWatcher(db, on_npc_consider, config)

            def watch_in_background():
                try:
                    watcher.watch()
                except KeyboardInterrupt:
                    root.quit()
                except Exception as e:
                    print(f"Watcher error: {e}")
                    traceback.print_exc()

            import threading

            watcher_thread = threading.Thread(target=watch_in_background, daemon=True)
            watcher_thread.start()

            print("\n[OK] Overlay running")
            print("[OK] Use /consider command in EQ to see NPC resistances")
            print("[OK] Double-click or right-click the overlay to open settings")
            print("[OK] Close window to exit\n")

            root.mainloop()
        else:
            print("Tkinter not available. Running in console mode.")
            watcher = EQLogWatcher(db, lambda r: print_resists(r), config)
            watcher.watch()

    except Exception as e:
        print(f"FATAL ERROR: {e}")
        traceback.print_exc()
        if HAS_TK and tk and messagebox:
            try:
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror("Error", f"Failed to start:\n\n{str(e)}\n\nCheck overlay.log for details")
                root.destroy()
            except Exception:
                pass


def print_resists(resists):
    """Console output version"""
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"\n{'=' * 30}")
    print(f"{resists['name']:^30}")
    print(f"{'=' * 30}")
    print(f"Magic Resist (MR): {resists['MR']}")
    print(f"Cold Resist  (CR): {resists['CR']}")
    print(f"Disease Resist (DR): {resists['DR']}")
    print(f"Fire Resist  (FR): {resists['FR']}")
    print(f"Poison Resist (PR): {resists['PR']}")
    print(f"{'=' * 30}\n")


if __name__ == '__main__':
    main()
