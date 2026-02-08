try:
    import tkinter as tk
    from tkinter import ttk
    from tkinter import messagebox
    from tkinter import filedialog
    import os
    HAS_TK = True
except ImportError:
    tk = None
    ttk = None
    messagebox = None
    filedialog = None
    os = None
    HAS_TK = False

from special_abilities import SPECIAL_ABILITIES, parse_special_abilities_ids
from utils import format_level_text


class ResistOverlayGUI:
    """Simple tkinter overlay window"""

    def __init__(self, root, config):
        self.root = root
        self.config = config
        self.watcher = None
        self._settings_win = None
        self._last_resists = None
        self._show_stats = self.config.get_show_stats() if self.config else True
        self._show_resists = self.config.get_show_resists() if self.config else True
        self._show_special_abilities = self.config.get_show_special_abilities() if self.config else False
        self._specials_filter = self.config.get_special_abilities_filter() if self.config else {}
        self._width = 520
        # Window position should persist and never reset during resizes.
        try:
            x, y = self.config.get_overlay_position() if self.config else (50, 50)
        except Exception:
            x, y = 50, 50
        self._x = int(x)
        self._y = int(y)
        self._save_pos_after_id = None
        self._is_applying_geometry = False
        self._main_frame = None
        # Wrap special abilities by commas (not by spaces)
        self._specials_wrap_chars = 62

        self.root.title("Quarm NPC Overlay")
        # Set an initial size; we'll recompute precisely after widgets exist.
        try:
            self.root.geometry(f"{self._width}x60+{self._x}+{self._y}")
        except Exception:
            pass
        self.root.attributes('-topmost', True)
        # Modern translucent overlay effect (user adjustable)
        self._opacity = self.config.get_overlay_opacity() if self.config else 0.88
        self.root.attributes('-alpha', self._opacity)

        # Make window click-through if possible
        try:
            self.root.attributes('-type', 'splash')
        except Exception:
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
        self._main_frame = main_frame
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Make the root grid expand so main_frame can fill the full window width.
        try:
            self.root.grid_columnconfigure(0, weight=1)
            self.root.grid_rowconfigure(0, weight=1)
        except Exception:
            pass

        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=0)

        # Row 0: NPC name + Share button
        self.name_label = ttk.Label(main_frame, text="---", font=("Arial", 11, "bold"))
        self.name_label.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N), padx=(0, 10))

        # Share button: copies a ready-to-paste message to clipboard
        self.share_btn = ttk.Button(main_frame, text="Share", command=self.share_to_raid)
        self.share_btn.grid(row=0, column=1, sticky=(tk.N, tk.E))

        # Row 1: stats
        self.stats_frame = ttk.Frame(main_frame)
        self.stats_frame.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(2, 0))

        self.stats_labels = {}
        stats = [
            ('Lv', 'level'),
            ('HP', 'hp'),
            ('Mana', 'mana'),
            ('AC', 'ac'),
            ('Dmg', 'dmg'),
        ]
        for col, (label, key) in enumerate(stats):
            lbl = ttk.Label(self.stats_frame, text=f"{label}:--", font=("Arial", 9, "bold"), foreground="#333")
            lbl.grid(row=0, column=col, sticky=tk.W, padx=(0, 10))
            self.stats_labels[key] = lbl

        # Row 2: resists
        self.resist_frame = ttk.Frame(main_frame)
        self.resist_frame.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(2, 0))

        self.resist_labels = {}
        resist_keys = ['MR', 'CR', 'DR', 'FR', 'PR']
        for col, key in enumerate(resist_keys, start=1):
            lbl = ttk.Label(self.resist_frame, text=f"{key}:--", font=("Arial", 10, "bold"), foreground="blue")
            lbl.grid(row=0, column=col - 1, sticky=tk.W, padx=(0, 10))
            self.resist_labels[key] = lbl

        # Row 3: special abilities
        self.special_label = ttk.Label(
            main_frame,
            text="",
            font=("Arial", 9, "bold"),
            foreground="#222",
            wraplength=0,
            justify="left",
            anchor="w",
        )
        self.special_label.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(2, 0))

        self._apply_visibility()

        # Keep overlay minimal: open settings via double-click or right-click
        self.root.bind('<Double-Button-1>', lambda _e: self.open_settings())
        self.root.bind('<Button-3>', lambda _e: self.open_settings())

        # Opacity hotkeys: Ctrl+Up / Ctrl+Down (persisted)
        self.root.bind('<Control-Up>', lambda _e: self._adjust_opacity(+0.05))
        self.root.bind('<Control-Down>', lambda _e: self._adjust_opacity(-0.05))

        # Track window moves so resizes keep the last position.
        try:
            self.root.bind('<Configure>', self._on_root_configure)
        except Exception:
            pass

    def _on_root_configure(self, event):
        try:
            if getattr(event, 'widget', None) is not self.root:
                return
            if self._is_applying_geometry:
                return

            # For Toplevel/Tk, Configure has screen coords.
            x = int(getattr(event, 'x', self._x))
            y = int(getattr(event, 'y', self._y))

            # Ignore obviously bogus values (can happen during init).
            if x == 0 and y == 0:
                return

            if x != self._x or y != self._y:
                self._x, self._y = x, y
                self._debounced_save_position()
        except Exception:
            return

    def _debounced_save_position(self):
        if not self.config:
            return
        try:
            if self._save_pos_after_id is not None:
                try:
                    self.root.after_cancel(self._save_pos_after_id)
                except Exception:
                    pass

            def _save():
                self._save_pos_after_id = None
                try:
                    self.config.set_overlay_position(self._x, self._y)
                except Exception:
                    pass

            self._save_pos_after_id = self.root.after(300, _save)
        except Exception:
            pass

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
        settings_win.title("Quarm NPC Overlay - Settings")
        settings_win.geometry("520x520")
        settings_win.attributes('-topmost', True)

        frame = ttk.Frame(settings_win, padding="10")
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Current path display
        ttk.Label(frame, text="Quarm Log Path:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=(0, 5))

        current_path = self.config.get_eq_log_path() or "Not set"
        path_label = ttk.Label(frame, text=current_path, font=("Arial", 9), foreground="blue", wraplength=350)
        path_label.grid(row=1, column=0, sticky=tk.W, pady=(0, 10))

        # Browse button
        def browse_file():
            file_path = filedialog.askopenfilename(
                title="Select Quarm Log File",
                filetypes=[("Log files", "eqlog_*.txt"), ("Text files", "*.txt"), ("All files", "*.*")]
            )
            if file_path:
                self.config.set_eq_log_path(file_path)
                path_label.config(text=file_path)
                messagebox.showinfo(
                    "Success",
                    "Log path saved!\n\nThe overlay will begin reading new /consider lines shortly."
                )
                try:
                    settings_win.destroy()
                except Exception:
                    pass

        browse_btn = ttk.Button(frame, text="Browse for Log File", command=browse_file)
        browse_btn.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 5))

        show_resists_var = tk.BooleanVar(value=self._show_resists)
        show_specials_var = tk.BooleanVar(value=self._show_special_abilities)
        show_stats_var = tk.BooleanVar(value=self._show_stats)

        def toggle_show_stats():
            self._show_stats = bool(show_stats_var.get())
            if self.config:
                self.config.set_show_stats(self._show_stats)
            self._apply_visibility()
            if self._last_resists:
                try:
                    self.update_display(self._last_resists)
                except Exception:
                    pass

        def toggle_show_resists():
            self._show_resists = bool(show_resists_var.get())
            if self.config:
                self.config.set_show_resists(self._show_resists)
            self._apply_visibility()
            if self._last_resists:
                try:
                    self.update_display(self._last_resists)
                except Exception:
                    pass

        def toggle_show_specials():
            self._show_special_abilities = bool(show_specials_var.get())
            if self.config:
                self.config.set_show_special_abilities(self._show_special_abilities)
            self._apply_visibility()
            _apply_specials_filter_visibility()
            if self._last_resists:
                try:
                    self.update_display(self._last_resists)
                except Exception:
                    pass

        show_stats_cb = ttk.Checkbutton(frame, text="Show stats", variable=show_stats_var, command=toggle_show_stats)
        show_stats_cb.grid(row=3, column=0, sticky=tk.W)

        show_resists_cb = ttk.Checkbutton(frame, text="Show resists", variable=show_resists_var, command=toggle_show_resists)
        show_resists_cb.grid(row=4, column=0, sticky=tk.W)

        show_specials_cb = ttk.Checkbutton(frame, text="Show special abilities", variable=show_specials_var, command=toggle_show_specials)
        show_specials_cb.grid(row=5, column=0, sticky=tk.W)

        # Per-ability checklist (only visible when specials are enabled)
        specials_frame = ttk.Labelframe(frame, text="Special abilities to show", padding="8")
        specials_frame.grid(row=6, column=0, sticky=(tk.W, tk.E), pady=(8, 0))

        # Scrollable area
        canvas = tk.Canvas(specials_frame, highlightthickness=0, height=260)
        scrollbar = ttk.Scrollbar(specials_frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)

        inner.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky=(tk.W, tk.E))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        specials_frame.columnconfigure(0, weight=1)

        # Build vars from config filter; missing IDs default to shown
        ability_vars = {}
        for idx, (aid, name) in enumerate(sorted(SPECIAL_ABILITIES.items(), key=lambda x: x[0])):
            enabled = self._specials_filter.get(str(aid), True)
            var = tk.BooleanVar(value=bool(enabled))
            ability_vars[aid] = var

            def _make_cmd(_aid=aid, _var=var):
                def _cmd():
                    self._specials_filter[str(_aid)] = bool(_var.get())
                    if self.config:
                        self.config.set_special_ability_enabled(_aid, bool(_var.get()))
                    if self._last_resists:
                        try:
                            self.update_display(self._last_resists)
                        except Exception:
                            pass
                return _cmd

            cb = ttk.Checkbutton(inner, text=f"{aid}: {name}", variable=var, command=_make_cmd())
            cb.grid(row=idx // 2, column=idx % 2, sticky=tk.W, padx=(0, 18), pady=(0, 2))

        def _apply_specials_filter_visibility():
            try:
                if self._show_special_abilities:
                    specials_frame.grid()
                else:
                    specials_frame.grid_remove()
            except Exception:
                pass

        _apply_specials_filter_visibility()

        def _on_close():
            try:
                settings_win.destroy()
            finally:
                self._settings_win = None

        settings_win.protocol("WM_DELETE_WINDOW", _on_close)

    def _apply_geometry(self):
        try:
            self.root.update_idletasks()
        except Exception:
            return

        height = None
        try:
            if self._main_frame is not None:
                height = int(self._main_frame.winfo_reqheight())
            else:
                height = int(self.root.winfo_reqheight())
        except Exception:
            height = 60

        # Add a tiny buffer so the last row never clips.
        height = max(40, int(height) + 2)

        # Preserve current position during geometry updates.
        try:
            try:
                x_now = int(self.root.winfo_x())
                y_now = int(self.root.winfo_y())
                if not (x_now == 0 and y_now == 0):
                    self._x, self._y = x_now, y_now
            except Exception:
                pass

            self._is_applying_geometry = True
            self.root.geometry(f"{self._width}x{height}+{self._x}+{self._y}")
        except Exception:
            pass
        finally:
            self._is_applying_geometry = False

    def _apply_visibility(self):
        try:
            if self._show_stats:
                self.stats_frame.grid()
            else:
                self.stats_frame.grid_remove()
        except Exception:
            pass

        try:
            if self._show_resists:
                self.resist_frame.grid()
            else:
                self.resist_frame.grid_remove()
        except Exception:
            pass

        try:
            if self._show_special_abilities:
                self.special_label.grid()
            else:
                self.special_label.grid_remove()
        except Exception:
            pass

        self._apply_geometry()

    def _format_specials(self, labels: str) -> str:
        items = [p.strip() for p in str(labels).split(',') if p.strip()]
        if not items:
            return ""

        lines = []
        current = []
        limit = int(self._specials_wrap_chars) if self._specials_wrap_chars else 62

        for item in items:
            candidate = ", ".join(current + [item])
            if current and len(candidate) > limit:
                lines.append(current)
                current = [item]
            else:
                current.append(item)

        if current:
            lines.append(current)

        line_texts = []
        for idx, line_items in enumerate(lines):
            text = ", ".join(line_items)
            if idx < len(lines) - 1:
                text += ","
            line_texts.append(text)

        return "\n".join(line_texts)

    def share_to_raid(self):
        resists = self._last_resists
        if not resists:
            return

        name = resists.get('display_name') or resists.get('name')
        if not name or str(name).strip() in ('---', ''):
            return

        try:
            parts = [str(name).strip()]

            if self._show_stats:
                try:
                    level = format_level_text(resists.get('level', '--'), resists.get('maxlevel', 0))
                    hp = resists.get('hp', '--')
                    mana = resists.get('mana', '--')
                    ac = resists.get('ac', '--')
                    mindmg = resists.get('mindmg', 0)
                    maxdmg = resists.get('maxdmg', 0)
                    try:
                        mindmg_i = int(mindmg or 0)
                        maxdmg_i = int(maxdmg or 0)
                        dmg_text = "--" if (mindmg_i == 0 and maxdmg_i == 0) else f"{mindmg_i}-{maxdmg_i}"
                    except Exception:
                        dmg_text = "--"
                    parts.append(f"Lv:{level} HP:{hp} Mana:{mana} AC:{ac} Dmg:{dmg_text}")
                except Exception:
                    pass

            if self._show_resists:
                parts.append(
                    f"MR:{resists.get('MR')} CR:{resists.get('CR')} DR:{resists.get('DR')} "
                    f"FR:{resists.get('FR')} PR:{resists.get('PR')}"
                )

            if self._show_special_abilities:
                raw = resists.get('special_abilities') or ''
                ids = parse_special_abilities_ids(raw) if raw else []
                filtered = []
                for aid in ids:
                    if self._specials_filter.get(str(aid), True):
                        label = SPECIAL_ABILITIES.get(aid)
                        if label:
                            filtered.append(label)
                if filtered:
                    parts.append(", ".join(filtered))

            msg = " | ".join([p for p in parts if p and str(p).strip()])
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
        debug_specials = False
        try:
            debug_specials = bool(os and os.environ.get('EQ_OVERLAY_DEBUG_SPECIALS') == '1')
        except Exception:
            debug_specials = False

        self._last_resists = dict(resists) if resists else None

        # Stats
        try:
            level = format_level_text(resists.get('level', '--'), resists.get('maxlevel', 0))
            hp = resists.get('hp', '--')
            mana = resists.get('mana', '--')
            ac = resists.get('ac', '--')
            mindmg = resists.get('mindmg', 0)
            maxdmg = resists.get('maxdmg', 0)
            self.stats_labels['level'].config(text=f"Lv:{level}")
            self.stats_labels['hp'].config(text=f"HP:{hp}")
            self.stats_labels['mana'].config(text=f"Mana:{mana}")
            self.stats_labels['ac'].config(text=f"AC:{ac}")
            try:
                mindmg_i = int(mindmg or 0)
                maxdmg_i = int(maxdmg or 0)
                dmg_text = "--" if (mindmg_i == 0 and maxdmg_i == 0) else f"{mindmg_i}-{maxdmg_i}"
            except Exception:
                dmg_text = "--"
            if 'dmg' in self.stats_labels:
                self.stats_labels['dmg'].config(text=f"Dmg:{dmg_text}")
        except Exception:
            pass
        # Always show current zone next to NPC name.
        display_name = resists.get('display_name') or resists.get('name') or '---'
        zone_long = resists.get('current_zone_long')
        zone_short = resists.get('current_zone_short')
        zone_text = None
        try:
            if zone_long and str(zone_long).strip():
                zone_text = str(zone_long).strip()
            elif zone_short and str(zone_short).strip():
                zone_text = str(zone_short).strip()
        except Exception:
            zone_text = None

        if not zone_text:
            zone_text = 'Unknown'

        display_name = f"{display_name} ({zone_text})"
        try:
            if resists.get('ambiguous') and '(?)' not in str(display_name):
                display_name = f"{display_name} (?)"
        except Exception:
            pass
        # Allow longer names since resists are on their own row.
        self.name_label.config(text=str(display_name)[:64])
        for key in self.resist_labels:
            value = resists[key]
            color = "green" if value < 0 else "red" if value > 50 else "orange"
            self.resist_labels[key].config(text=f"{key}:{value}", foreground=color)

        if self._show_special_abilities:
            raw = resists.get('special_abilities') or ''
            ids = parse_special_abilities_ids(raw) if raw else []
            filtered = []
            for aid in ids:
                if self._specials_filter.get(str(aid), True):
                    name = SPECIAL_ABILITIES.get(aid)
                    if name:
                        filtered.append(name)
            labels = ", ".join(filtered)
            if debug_specials:
                try:
                    raw_dbg = resists.get('special_abilities')
                    print(f"[DEBUG] GUI show_specials=1 raw={raw_dbg!r} labels={labels!r}")
                except Exception:
                    pass
            if labels:
                self.special_label.config(text=self._format_specials(labels))
            else:
                self.special_label.config(text="-")

        # If wrapping changes the requested height, resize the overlay.
        self._apply_geometry()
