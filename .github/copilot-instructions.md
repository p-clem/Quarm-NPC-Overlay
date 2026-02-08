# Copilot instructions for Quarm NPC Overlay

## Big picture
- Single-app Python overlay with three core pieces: log watcher, SQLite NPC resist DB, and Tkinter GUI, all in quarm_npc_overlay.py.
- Data flow: EverQuest log line -> regex parse (consider output) -> normalize NPC name (spaces→underscores, lower-case) -> SQLite lookup -> GUI update.
- Releases ship with a prebuilt `npc_data.db` (built from a full Quarm SQL dump). A Quarm dump is only needed for rebuilding/updating the DB during release builds or manual refreshes.

## Key files to know
- quarm_npc_overlay.py: main entry, ConfigManager, EQResistDatabase, EQLogWatcher, and GUI (ResistOverlayGUI).
- quarm.sql / quarm_*.sql: full dump used to build NPC + zone/spawn mapping.
- load_db.py: helper to load quarm.sql into dist/npc_data.db (used for packaged builds).
- Spec files: PyInstaller specs for packaged builds (no SQL dump is bundled).
- build.bat: one-click release build (EXE + zip) using app_config.json name/version.
- test_*.py: standalone smoke tests for DB lookup and log parsing.

## Project-specific conventions
- Name normalization is essential: always convert spaces to underscores and strip leading “#” before DB lookup (see EQResistDatabase.get_npc_resists and EQLogWatcher.watch).
- DB schema uses name_lower for case-insensitive exact matches (no LIKE searches in app logic).
- Config is stored in config.json next to the script/exe; EQ log path can be auto-detected or user-specified via GUI.
- Logging is redirected to overlay.log next to the script/exe before any Tkinter import.

## Workflows
- Run from source: python quarm_npc_overlay.py (Tkinter GUI).
- Build executable (Windows): run build.bat (PyInstaller onefile, windowed).
- Prepare packaged DB: python load_db.py (writes dist/npc_data.db).
- Quick checks: python test_complete.py, test_lookup_fixed.py, test_log_parsing.py.

## Integration points
- External dependency is the EverQuest log file (eqlog_*.txt); auto-detection uses common Windows install paths.
- When changing data paths or packaging, update the spec files and verify db/sql lookup in quarm_npc_overlay.py.
