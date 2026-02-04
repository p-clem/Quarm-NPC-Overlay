import os
import sys
import json
import re
import time
import sqlite3
import traceback
from pathlib import Path
from datetime import datetime
from collections import defaultdict


def normalize_npc_name(name: str) -> str:
    """Normalize an NPC name to match DB key conventions."""
    if not name:
        return ''
    name = name.strip().lstrip('#')
    return re.sub(r'\s+', '_', name)


def npc_lookup_keys(name: str) -> list[str]:
    """Generate candidate lookup keys to handle EQ/DB punctuation quirks."""
    base = normalize_npc_name(name)
    if not base:
        return []
    candidates = [base]

    # Some logs/sources may omit the EQ backtick used in certain NPC names.
    if '`' in base:
        candidates.append(base.replace('`', ''))
    else:
        # If the DB includes a backtick but the log omitted it, a strict match will fail.
        # We can't reliably re-insert it, but removing punctuation on both sides often works.
        candidates.append(base)

    # Treat apostrophe/backtick as interchangeable in edge cases.
    if "'" in base:
        candidates.append(base.replace("'", '`'))
    if '`' in base:
        candidates.append(base.replace('`', "'"))

    # Also try a punctuation-stripped variant for stubborn cases.
    candidates.append(re.sub(r"[\'`]+", '', base))

    # De-dupe preserving order
    seen = set()
    out: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out

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

# Try to import tkinter for GUI overlay
try:
    import tkinter as tk
    from tkinter import ttk
    from tkinter import messagebox
    from tkinter import filedialog
    HAS_TK = True
except ImportError:
    HAS_TK = False


class ConfigManager:
    """Manage config file for EQ log path"""
    
    def __init__(self):
        self.config_dir = Path(__file__).parent if not hasattr(sys, 'frozen') else Path(sys.executable).parent
        self.config_file = self.config_dir / 'config.json'
        self.config = self._load_config()
    
    def _load_config(self):
        """Load config from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {
            'eq_log_path': None,
            # Tk alpha (0.0-1.0). Lower = more transparent.
            'overlay_opacity': 0.88,
        }
    
    def save_config(self):
        """Save config to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            return True
        except:
            return False
    
    def get_eq_log_path(self):
        """Get configured EQ log path"""
        return self.config.get('eq_log_path')
    
    def set_eq_log_path(self, path):
        """Set and save EQ log path"""
        self.config['eq_log_path'] = path
        return self.save_config()

    def get_overlay_opacity(self):
        """Get configured overlay opacity (0.0-1.0)."""
        value = self.config.get('overlay_opacity', 0.88)
        try:
            value = float(value)
        except Exception:
            value = 0.88
        return max(0.3, min(1.0, value))

    def set_overlay_opacity(self, value):
        """Set and save overlay opacity (0.0-1.0)."""
        try:
            value = float(value)
        except Exception:
            return False
        value = max(0.3, min(1.0, value))
        self.config['overlay_opacity'] = value
        return self.save_config()


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
                mr INTEGER DEFAULT 0,
                cr INTEGER DEFAULT 0,
                dr INTEGER DEFAULT 0,
                fr INTEGER DEFAULT 0,
                pr INTEGER DEFAULT 0
            )
        ''')
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
                                mr = int(values[43]) if values[43] else 0
                                cr = int(values[44]) if values[44] else 0
                                dr = int(values[45]) if values[45] else 0
                                fr = int(values[46]) if values[46] else 0
                                pr = int(values[47]) if values[47] else 0

                                name_lower = normalize_npc_name(name).lower()
                                
                                try:
                                    cursor.execute('''
                                        INSERT INTO npcs (id, name, name_lower, mr, cr, dr, fr, pr)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    ''', (values[0], name, name_lower, mr, cr, dr, fr, pr))
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

        result = None
        for key in npc_lookup_keys(name):
            cursor.execute('''
                SELECT name, mr, cr, dr, fr, pr FROM npcs WHERE name_lower = ?
            ''', (key.lower(),))
            result = cursor.fetchone()
            if result:
                break
        
        if result:
            return {
                'name': result[0],
                'MR': result[1],
                'CR': result[2],
                'DR': result[3],
                'FR': result[4],
                'PR': result[5]
            }
        return None


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
        # Compile consider regex once
        self.consider_re = re.compile(
            r'^(?P<target>.*?)\s+(?P<faction>scowls|glar(?:es|es).*?|glowers|is|looks|judges?|kindly|regards).*?(?P<sep>-- )?(?P<diff>.*)?$',
            re.IGNORECASE
        )
    
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
        
        print("Watcher thread started - waiting for EQ log file...")
        
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
                                
                                # Match proper EQ consider format
                                match = self.consider_re.match(clean_line)
                                if match:
                                    npc_name = match.group('target').strip()
                                    print(f"Found consider: {npc_name}")

                                    name_normalized = normalize_npc_name(npc_name)
                                    
                                    # Query database using thread-local connection
                                    cursor = db_conn.cursor()
                                    result = None
                                    for key in npc_lookup_keys(npc_name):
                                        cursor.execute('''
                                            SELECT name, mr, cr, dr, fr, pr FROM npcs WHERE name_lower = ?
                                        ''', (key.lower(),))
                                        result = cursor.fetchone()
                                        if result:
                                            break
                                    
                                    if result:
                                        resists = {
                                            # Keep DB name for reference, but prefer the in-game name for display.
                                            'name': result[0],
                                            'display_name': npc_name,
                                            'MR': result[1],
                                            'CR': result[2],
                                            'DR': result[3],
                                            'FR': result[4],
                                            'PR': result[5]
                                        }
                                        print(f"Match found: {npc_name} - MR:{resists['MR']} CR:{resists['CR']} DR:{resists['DR']} FR:{resists['FR']} PR:{resists['PR']}")
                                        self.callback(resists)
                                    else:
                                        print(f"No resists found for: {npc_name}")
                            
                            self.last_position = self.log_file.stat().st_size
                
                time.sleep(0.5)
            except Exception as e:
                print(f"Error watching log: {e}")
                traceback.print_exc()
                time.sleep(1)


class ResistOverlayGUI:
    """Simple tkinter overlay window"""
    
    def __init__(self, root, config):
        self.root = root
        self.config = config
        self.watcher = None
        self._settings_win = None
        self._last_resists = None
        
        self.root.title("EQ Resist Overlay")
        # Minimal one-line overlay
        self.root.geometry("520x38+50+50")
        self.root.attributes('-topmost', True)
        # Modern translucent overlay effect (user adjustable)
        self._opacity = self.config.get_overlay_opacity() if self.config else 0.88
        self.root.attributes('-alpha', self._opacity)
        
        # Make window click-through if possible
        try:
            self.root.attributes('-type', 'splash')
        except:
            pass

        # Ensure the overlay is visible on launch (helps when started from a terminal)
        try:
            self.root.update_idletasks()
            self.root.lift()
            self.root.focus_force()
            self.root.after(200, self.root.lift)
        except Exception:
            pass
        
        # Create main frame
        main_frame = ttk.Frame(root, padding="4")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.columnconfigure(0, weight=1)
        
        # NPC name (left) + resist values in columns (single line)
        self.name_label = ttk.Label(main_frame, text="---", font=("Arial", 11, "bold"))
        self.name_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 10))

        self.resist_labels = {}
        resist_keys = ['MR', 'CR', 'DR', 'FR', 'PR']
        for col, key in enumerate(resist_keys, start=1):
            lbl = ttk.Label(main_frame, text=f"{key}:--", font=("Arial", 10, "bold"), foreground="blue")
            lbl.grid(row=0, column=col, sticky=tk.E, padx=(6, 0))
            self.resist_labels[key] = lbl

        # Share button: copies a ready-to-paste message to clipboard
        self.share_btn = ttk.Button(main_frame, text="Share", command=self.share_to_raid)
        self.share_btn.grid(row=0, column=len(resist_keys) + 1, sticky=tk.E, padx=(10, 0))

        # Keep overlay minimal: open settings via double-click or right-click
        self.root.bind('<Double-Button-1>', lambda _e: self.open_settings())
        self.root.bind('<Button-3>', lambda _e: self.open_settings())

        # Opacity hotkeys: Ctrl+Up / Ctrl+Down (persisted)
        self.root.bind('<Control-Up>', lambda _e: self._adjust_opacity(+0.05))
        self.root.bind('<Control-Down>', lambda _e: self._adjust_opacity(-0.05))

    def _adjust_opacity(self, delta):
        self._opacity = max(0.3, min(1.0, float(self._opacity) + float(delta)))
        try:
            self.root.attributes('-alpha', self._opacity)
        except Exception:
            return
        try:
            if self.config:
                self.config.set_overlay_opacity(self._opacity)
        except Exception:
            pass
    
    def open_settings(self):
        """Open settings dialog"""
        try:
            if self._settings_win is not None and self._settings_win.winfo_exists():
                self._settings_win.lift()
                self._settings_win.focus_force()
                return
        except Exception:
            pass

        settings_win = tk.Toplevel(self.root)
        self._settings_win = settings_win
        settings_win.title("Settings")
        settings_win.geometry("400x150")
        settings_win.attributes('-topmost', True)
        
        frame = ttk.Frame(settings_win, padding="10")
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Current path display
        ttk.Label(frame, text="EQ Log Path:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        current_path = self.config.get_eq_log_path() or "Not set"
        path_label = ttk.Label(frame, text=current_path, font=("Arial", 9), foreground="blue", wraplength=350)
        path_label.grid(row=1, column=0, sticky=tk.W, pady=(0, 10))
        
        # Browse button
        def browse_file():
            file_path = filedialog.askopenfilename(
                title="Select EverQuest Log File",
                filetypes=[("Log files", "eqlog_*.txt"), ("Text files", "*.txt"), ("All files", "*.*")]
            )
            if file_path:
                self.config.set_eq_log_path(file_path)
                path_label.config(text=file_path)
                messagebox.showinfo("Success", "EQ log path saved!\n\nThe overlay will begin reading new /consider lines shortly.")
                try:
                    settings_win.destroy()
                except Exception:
                    pass
        
        browse_btn = ttk.Button(frame, text="Browse for Log File", command=browse_file)
        browse_btn.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        
        def _on_close():
            try:
                settings_win.destroy()
            finally:
                self._settings_win = None

        settings_win.protocol("WM_DELETE_WINDOW", _on_close)

    def share_to_raid(self):
        resists = self._last_resists
        if not resists:
            return

        name = resists.get('display_name') or resists.get('name')
        if not name or str(name).strip() in ('---', ''):
            return

        try:
            msg = (
                f"{name} "
                f"MR:{resists.get('MR')} CR:{resists.get('CR')} DR:{resists.get('DR')} "
                f"FR:{resists.get('FR')} PR:{resists.get('PR')}"
            )
            self.root.clipboard_clear()
            self.root.clipboard_append(msg)
            self.root.update_idletasks()
            print(f"Copied to clipboard: {msg}")
        except Exception as e:
            print(f"Failed to copy share message to clipboard: {e}")
            return

        # Tiny feedback without a dialog
        try:
            self.share_btn.config(text="Copied!")
            self.root.after(900, lambda: self.share_btn.config(text="Share"))
        except Exception:
            pass
    
    def update_display(self, resists):
        """Update overlay with NPC data"""
        self._last_resists = dict(resists) if resists else None
        # Give the name most of the space; keep it short to avoid pushing resist columns off-screen
        display_name = resists.get('display_name') or resists.get('name') or '---'
        self.name_label.config(text=str(display_name)[:32])
        for key in self.resist_labels:
            value = resists[key]
            color = "green" if value < 0 else "red" if value > 50 else "orange"
            self.resist_labels[key].config(text=f"{key}:{value}", foreground=color)


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
        sql_path = resource_dir / 'npc_types.sql'
        
        print(f"Script dir: {script_dir}")
        print(f"SQL path: {sql_path}")
        print(f"SQL exists: {sql_path.exists()}")
        
        print("="*50)
        print("EverQuest Resist Overlay")
        print(f"Starting at {datetime.now()}")
        print("="*50)
        
        # Load configuration
        config = ConfigManager()
        
        # Initialize database
        db = EQResistDatabase(str(db_path))
        
        # Check if we need to populate from SQL
        cursor = db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM npcs")
        count = cursor.fetchone()[0]
        
        print(f"Database has {count} NPCs")
        
        if count == 0:
            # Try multiple locations for SQL file
            sql_locations = [
                sql_path,
                script_dir / 'npc_types.sql',
                resource_dir / 'npc_types.sql',
                Path(__file__).parent / 'npc_types.sql',
                Path(__file__).parent.parent / 'npc_types.sql',  # Parent directory
            ]
            
            sql_found = None
            for loc in sql_locations:
                if loc.exists():
                    sql_found = loc
                    break
            
            if sql_found:
                print(f"Loading from {sql_found}")
                db.populate_from_sql(str(sql_found))
            else:
                print(f"Warning: npc_types.sql not found")
                print(f"Checked locations: {sql_locations}")
                print(f"Database is empty - overlay will not work until SQL is loaded")
        
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
        if HAS_TK:
            try:
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror("Error", f"Failed to start:\n\n{str(e)}\n\nCheck overlay.log for details")
                root.destroy()
            except:
                pass


def print_resists(resists):
    """Console output version"""
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"\n{'='*30}")
    print(f"{resists['name']:^30}")
    print(f"{'='*30}")
    print(f"Magic Resist (MR): {resists['MR']}")
    print(f"Cold Resist  (CR): {resists['CR']}")
    print(f"Disease Resist (DR): {resists['DR']}")
    print(f"Fire Resist  (FR): {resists['FR']}")
    print(f"Poison Resist (PR): {resists['PR']}")
    print(f"{'='*30}\n")


if __name__ == '__main__':
    main()
