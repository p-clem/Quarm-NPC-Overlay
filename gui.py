import os
import sys

HAS_QT = False
QApplication = None

try:
    from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPoint, QSize
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
        QDialog, QCheckBox, QSlider, QFileDialog, QMessageBox, QSystemTrayIcon,
        QMenu, QScrollArea, QGridLayout, QGroupBox, QSizePolicy, QFrame,
    )
    from PyQt6.QtGui import (
        QColor, QPainter, QBrush, QFont, QIcon, QPixmap, QPainterPath, QAction,
    )
    HAS_QT = True
except ImportError:
    pass

_IS_WINDOWS = sys.platform == 'win32'
_HAS_CTYPES = False
if _IS_WINDOWS:
    try:
        import ctypes
        import ctypes.wintypes
        _HAS_CTYPES = True
    except ImportError:
        pass

from special_abilities import SPECIAL_ABILITIES, parse_special_abilities_ids
from utils import format_level_text


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
def _resist_color(value):
    try:
        v = int(value)
    except Exception:
        return "#aaaaaa"
    if v < 0:
        return "#44cc44"
    if v > 50:
        return "#ee4444"
    return "#ee8822"


def _make_label_style(color="#ffffff", size=10, bold=True):
    weight = "bold" if bold else "normal"
    return f"color: {color}; font-size: {size}pt; font-weight: {weight}; background: transparent;"


# ---------------------------------------------------------------------------
# Main overlay widget
# ---------------------------------------------------------------------------
if HAS_QT:
    class ResistOverlayGUI(QWidget):
        """PyQt6 frameless overlay with per-element transparency."""

        # Thread-safe bridge: emit from watcher thread, slot runs on GUI thread
        npc_updated = pyqtSignal(object)

        def __init__(self, config, parent=None):
            super().__init__(parent)
            self.config = config
            self.watcher = None
            self._last_resists = None
            self._settings_win = None

            self._show_stats = config.get_show_stats() if config else True
            self._show_resists = config.get_show_resists() if config else True
            self._show_special_abilities = config.get_show_special_abilities() if config else True
            self._specials_filter = config.get_special_abilities_filter() if config else {}
            self._specials_wrap_chars = 72

            self._bg_opacity = config.get_overlay_opacity() if config else 0.88
            self._locked = config.get_overlay_locked() if config else False
            self._hotkey_registered = False
            self._hotkey_id = 9001

            # Drag state
            self._drag_pos = None

            # Position save debounce
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.setInterval(300)
            self._save_timer.timeout.connect(self._save_position)

            # Window flags: frameless, always on top, tool window (skip taskbar)
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setMinimumWidth(420)

            # Restore position
            try:
                x, y = config.get_overlay_position() if config else (50, 50)
            except Exception:
                x, y = 50, 50
            self.move(int(x), int(y))

            self._build_ui()
            self._apply_visibility()

            # Connect signal
            self.npc_updated.connect(self._on_npc_updated)

            # System tray
            self._tray_icon = None
            self._build_tray()

            # Click-through + global hotkey (Windows)
            if _IS_WINDOWS and _HAS_CTYPES:
                QTimer.singleShot(500, self._apply_click_through)
                self._register_global_hotkey()

        # ---- UI construction --------------------------------------------------

        def _build_ui(self):
            layout = QVBoxLayout(self)
            layout.setContentsMargins(10, 8, 10, 8)
            layout.setSpacing(4)

            # Row 0: NPC name + gear + share
            top_row = QHBoxLayout()
            top_row.setSpacing(6)

            self.name_label = QLabel("---")
            self.name_label.setStyleSheet(_make_label_style("#ffffff", 11, True))
            self.name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            top_row.addWidget(self.name_label)

            self.gear_btn = QPushButton("\u2699")
            self.gear_btn.setFixedSize(28, 28)
            self.gear_btn.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,30); color: white; border: none; border-radius: 4px; font-size: 14pt; }"
                "QPushButton:hover { background: rgba(255,255,255,60); }"
            )
            self.gear_btn.clicked.connect(self.open_settings)
            top_row.addWidget(self.gear_btn)

            self.share_btn = QPushButton("Share")
            self.share_btn.setFixedHeight(28)
            self.share_btn.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,30); color: white; border: none; border-radius: 4px; font-size: 9pt; padding: 0 8px; }"
                "QPushButton:hover { background: rgba(255,255,255,60); }"
            )
            self.share_btn.clicked.connect(self.share_to_raid)
            top_row.addWidget(self.share_btn)

            layout.addLayout(top_row)

            # Row 1: stats
            self.stats_widget = QWidget()
            stats_layout = QHBoxLayout(self.stats_widget)
            stats_layout.setContentsMargins(0, 0, 0, 0)
            stats_layout.setSpacing(12)

            self.stats_labels = {}
            for label, key in [('Lv', 'level'), ('HP', 'hp'), ('Mana', 'mana'), ('AC', 'ac'), ('Dmg', 'dmg')]:
                lbl = QLabel(f"{label}:--")
                lbl.setStyleSheet(_make_label_style("#cccccc", 9, True))
                stats_layout.addWidget(lbl)
                self.stats_labels[key] = lbl
            stats_layout.addStretch()
            layout.addWidget(self.stats_widget)

            # Row 2: resists
            self.resist_widget = QWidget()
            resist_layout = QHBoxLayout(self.resist_widget)
            resist_layout.setContentsMargins(0, 0, 0, 0)
            resist_layout.setSpacing(12)

            self.resist_labels = {}
            for key in ['MR', 'CR', 'DR', 'FR', 'PR']:
                lbl = QLabel(f"{key}:--")
                lbl.setStyleSheet(_make_label_style("#aaaaaa", 10, True))
                resist_layout.addWidget(lbl)
                self.resist_labels[key] = lbl
            resist_layout.addStretch()
            layout.addWidget(self.resist_widget)

            # Row 3: special abilities
            self.special_label = QLabel("")
            self.special_label.setStyleSheet(_make_label_style("#dddddd", 9, True))
            self.special_label.setWordWrap(True)
            layout.addWidget(self.special_label)

            self.setLayout(layout)

        # ---- Paint translucent background ------------------------------------

        def paintEvent(self, event):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            alpha = max(0, min(255, int(self._bg_opacity * 255)))
            p.setBrush(QBrush(QColor(30, 30, 30, alpha)))
            p.setPen(Qt.PenStyle.NoPen)
            path = QPainterPath()
            path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()), 8.0, 8.0)
            p.drawPath(path)
            p.end()

        # ---- Mouse drag / context menu / double-click ------------------------

        def mousePressEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
            elif event.button() == Qt.MouseButton.RightButton:
                self.open_settings()
                event.accept()

        def mouseMoveEvent(self, event):
            if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
                new_pos = event.globalPosition().toPoint() - self._drag_pos
                self.move(new_pos)
                self._save_timer.start()
                event.accept()

        def mouseReleaseEvent(self, event):
            self._drag_pos = None

        def mouseDoubleClickEvent(self, event):
            self.open_settings()
            event.accept()

        # ---- Position persistence -------------------------------------------

        def _save_position(self):
            if self.config:
                try:
                    pos = self.pos()
                    self.config.set_overlay_position(pos.x(), pos.y())
                except Exception:
                    pass

        # ---- Visibility helpers ---------------------------------------------

        def _apply_visibility(self):
            self.stats_widget.setVisible(self._show_stats)
            self.resist_widget.setVisible(self._show_resists)
            has_specials = self._show_special_abilities and self.special_label.text().strip() not in ("", "-")
            self.special_label.setVisible(self._show_special_abilities)
            self.adjustSize()

        # ---- Click-through (Windows) ----------------------------------------

        def _get_hwnd(self):
            if not (_IS_WINDOWS and _HAS_CTYPES):
                return None
            try:
                return int(self.winId())
            except Exception:
                return None

        def _apply_click_through(self):
            if not (_IS_WINDOWS and _HAS_CTYPES):
                return
            hwnd = self._get_hwnd()
            if not hwnd:
                return
            try:
                GWL_EXSTYLE = -20
                WS_EX_TRANSPARENT = 0x00000020
                WS_EX_LAYERED = 0x00080000
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                if self._locked:
                    new_style = style | WS_EX_TRANSPARENT | WS_EX_LAYERED
                else:
                    new_style = (style | WS_EX_LAYERED) & ~WS_EX_TRANSPARENT
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOZORDER = 0x0004
                SWP_FRAMECHANGED = 0x0020
                ctypes.windll.user32.SetWindowPos(
                    hwnd, None, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
                )
            except Exception:
                pass

        def _toggle_lock(self):
            self._locked = not self._locked
            if self.config:
                self.config.set_overlay_locked(self._locked)
            self._apply_click_through()
            self._refresh_tray_menu()
            state = "locked (click-through)" if self._locked else "unlocked"
            print(f"[LOCK] Overlay {state}")

        # ---- Global hotkey (Ctrl+Shift+L, Windows) --------------------------

        def _register_global_hotkey(self):
            if not (_IS_WINDOWS and _HAS_CTYPES):
                return
            try:
                MOD_CONTROL = 0x0002
                MOD_SHIFT = 0x0004
                VK_L = 0x4C
                result = ctypes.windll.user32.RegisterHotKey(
                    None, self._hotkey_id, MOD_CONTROL | MOD_SHIFT, VK_L,
                )
                if result:
                    self._hotkey_registered = True
                    self._hotkey_timer = QTimer(self)
                    self._hotkey_timer.setInterval(100)
                    self._hotkey_timer.timeout.connect(self._poll_global_hotkey)
                    self._hotkey_timer.start()
            except Exception:
                pass

        def _poll_global_hotkey(self):
            if not self._hotkey_registered:
                return
            try:
                msg = ctypes.wintypes.MSG()
                WM_HOTKEY = 0x0312
                PM_REMOVE = 0x0001
                while ctypes.windll.user32.PeekMessageW(
                    ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE,
                ):
                    if msg.wParam == self._hotkey_id:
                        self._toggle_lock()
            except Exception:
                pass

        def _cleanup_hotkey(self):
            if self._hotkey_registered and _IS_WINDOWS and _HAS_CTYPES:
                try:
                    ctypes.windll.user32.UnregisterHotKey(None, self._hotkey_id)
                except Exception:
                    pass
                self._hotkey_registered = False

        # ---- System tray ----------------------------------------------------

        def _build_tray(self):
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
            # Build a small icon: blue circle with "Q"
            pix = QPixmap(64, 64)
            pix.fill(QColor(0, 0, 0, 0))
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QBrush(QColor(60, 130, 200)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(4, 4, 56, 56)
            p.setPen(QColor(255, 255, 255))
            font = QFont("Arial", 28, QFont.Weight.Bold)
            p.setFont(font)
            p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "Q")
            p.end()

            icon = QIcon(pix)
            self._tray_icon = QSystemTrayIcon(icon, self)
            self._tray_icon.setToolTip("Quarm NPC Overlay")
            self._tray_icon.activated.connect(self._on_tray_activated)

            self._tray_menu = QMenu()
            self._build_tray_menu()
            self._tray_icon.setContextMenu(self._tray_menu)
            self._tray_icon.show()

        def _build_tray_menu(self):
            self._tray_menu.clear()

            settings_action = QAction("Settings", self)
            settings_action.triggered.connect(self.open_settings)
            self._tray_menu.addAction(settings_action)

            lock_text = "Unlock Overlay" if self._locked else "Lock Overlay"
            lock_action = QAction(lock_text, self)
            lock_action.triggered.connect(self._toggle_lock)
            self._tray_menu.addAction(lock_action)

            self._tray_menu.addSeparator()

            exit_action = QAction("Exit", self)
            exit_action.triggered.connect(self._on_close)
            self._tray_menu.addAction(exit_action)

        def _refresh_tray_menu(self):
            if self._tray_icon is not None:
                try:
                    self._build_tray_menu()
                    self._tray_icon.setContextMenu(self._tray_menu)
                except Exception:
                    pass

        def _on_tray_activated(self, reason):
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
                self.open_settings()

        # ---- Settings dialog ------------------------------------------------

        def open_settings(self):
            if self._settings_win is not None:
                try:
                    self._settings_win.raise_()
                    self._settings_win.activateWindow()
                    return
                except Exception:
                    self._settings_win = None

            dlg = QDialog()
            dlg.setWindowTitle("Quarm NPC Overlay - Settings")
            dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            dlg.resize(520, 620)
            self._settings_win = dlg

            outer = QVBoxLayout(dlg)
            outer.setSpacing(8)

            # --- Log path ---
            outer.addWidget(QLabel("Quarm Log Path:"))
            current_path = self.config.get_eq_log_path() or "Not set"
            path_label = QLabel(current_path)
            path_label.setStyleSheet("color: #3377cc;")
            path_label.setWordWrap(True)
            outer.addWidget(path_label)

            def browse_file():
                file_path, _ = QFileDialog.getOpenFileName(
                    dlg, "Select Quarm Log File", "",
                    "Log files (eqlog_*.txt);;Text files (*.txt);;All files (*.*)",
                )
                if file_path:
                    self.config.set_eq_log_path(file_path)
                    path_label.setText(file_path)
                    QMessageBox.information(
                        dlg, "Success",
                        "Log path saved!\n\nThe overlay will begin reading new /consider lines shortly.",
                    )
                    dlg.close()

            browse_btn = QPushButton("Browse for Log File")
            browse_btn.clicked.connect(browse_file)
            outer.addWidget(browse_btn)

            # --- Checkboxes ---
            show_stats_cb = QCheckBox("Show stats")
            show_stats_cb.setChecked(self._show_stats)

            show_resists_cb = QCheckBox("Show resists")
            show_resists_cb.setChecked(self._show_resists)

            show_specials_cb = QCheckBox("Show special abilities")
            show_specials_cb.setChecked(self._show_special_abilities)

            lock_cb = QCheckBox("Lock overlay (click-through, Ctrl+Shift+L to toggle)")
            lock_cb.setChecked(self._locked)

            def toggle_stats(state):
                self._show_stats = show_stats_cb.isChecked()
                if self.config:
                    self.config.set_show_stats(self._show_stats)
                self._apply_visibility()
                if self._last_resists:
                    self.update_display(self._last_resists)

            def toggle_resists(state):
                self._show_resists = show_resists_cb.isChecked()
                if self.config:
                    self.config.set_show_resists(self._show_resists)
                self._apply_visibility()
                if self._last_resists:
                    self.update_display(self._last_resists)

            def toggle_specials(state):
                self._show_special_abilities = show_specials_cb.isChecked()
                if self.config:
                    self.config.set_show_special_abilities(self._show_special_abilities)
                self._apply_visibility()
                _apply_specials_filter_visibility()
                if self._last_resists:
                    self.update_display(self._last_resists)

            def toggle_lock(state):
                self._locked = lock_cb.isChecked()
                if self.config:
                    self.config.set_overlay_locked(self._locked)
                self._apply_click_through()
                self._refresh_tray_menu()

            show_stats_cb.stateChanged.connect(toggle_stats)
            show_resists_cb.stateChanged.connect(toggle_resists)
            show_specials_cb.stateChanged.connect(toggle_specials)
            lock_cb.stateChanged.connect(toggle_lock)

            outer.addWidget(show_stats_cb)
            outer.addWidget(show_resists_cb)
            outer.addWidget(show_specials_cb)
            outer.addWidget(lock_cb)

            # --- Opacity slider ---
            opacity_widget = QWidget()
            opacity_layout = QHBoxLayout(opacity_widget)
            opacity_layout.setContentsMargins(0, 0, 0, 0)

            opacity_layout.addWidget(QLabel("Opacity:"))

            opacity_slider = QSlider(Qt.Orientation.Horizontal)
            opacity_slider.setMinimum(30)
            opacity_slider.setMaximum(100)
            opacity_slider.setValue(int(self._bg_opacity * 100))
            opacity_layout.addWidget(opacity_slider, stretch=1)

            opacity_val = QLabel(f"{int(self._bg_opacity * 100)}%")
            opacity_val.setFixedWidth(40)
            opacity_layout.addWidget(opacity_val)

            def on_opacity_change(val):
                self._bg_opacity = max(0.3, min(1.0, val / 100.0))
                opacity_val.setText(f"{val}%")
                self.update()  # repaint background
                if self.config:
                    self.config.set_overlay_opacity(self._bg_opacity)

            opacity_slider.valueChanged.connect(on_opacity_change)
            outer.addWidget(opacity_widget)

            # --- Special abilities filter ---
            specials_group = QGroupBox("Special abilities to show")
            specials_outer = QVBoxLayout(specials_group)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setMaximumHeight(260)
            inner_widget = QWidget()
            inner_layout = QGridLayout(inner_widget)
            inner_layout.setContentsMargins(4, 4, 4, 4)

            for idx, (aid, name) in enumerate(sorted(SPECIAL_ABILITIES.items(), key=lambda x: x[0])):
                enabled = self._specials_filter.get(str(aid), True)
                cb = QCheckBox(f"{aid}: {name}")
                cb.setChecked(bool(enabled))

                def _make_cmd(_aid=aid, _cb=cb):
                    def _cmd(state):
                        self._specials_filter[str(_aid)] = _cb.isChecked()
                        if self.config:
                            self.config.set_special_ability_enabled(_aid, _cb.isChecked())
                        if self._last_resists:
                            self.update_display(self._last_resists)
                    return _cmd

                cb.stateChanged.connect(_make_cmd())
                inner_layout.addWidget(cb, idx // 2, idx % 2)

            scroll.setWidget(inner_widget)
            specials_outer.addWidget(scroll)
            outer.addWidget(specials_group)

            def _apply_specials_filter_visibility():
                specials_group.setVisible(self._show_special_abilities)

            _apply_specials_filter_visibility()

            outer.addStretch()

            def _on_close():
                self._settings_win = None

            dlg.finished.connect(lambda _: _on_close())
            dlg.show()

        # ---- Share to clipboard ---------------------------------------------

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

                clipboard = QApplication.clipboard()
                if clipboard:
                    clipboard.setText(msg)
                print(f"Copied to clipboard: {msg}")
            except Exception as e:
                print(f"Failed to copy share message to clipboard: {e}")
                return

            # Brief visual feedback
            try:
                self.share_btn.setText("Copied!")
                QTimer.singleShot(900, lambda: self.share_btn.setText("Share"))
            except Exception:
                pass

        # ---- Thread-safe NPC update -----------------------------------------

        def on_npc_consider(self, resists):
            """Called from the watcher thread. Emits signal to marshal to GUI thread."""
            self.npc_updated.emit(resists)

        def _on_npc_updated(self, resists):
            """Slot running on the GUI thread."""
            try:
                self.update_display(resists)
            except Exception as e:
                print(f"Error in display update: {e}")

        # ---- Display update -------------------------------------------------

        def update_display(self, resists):
            self._last_resists = dict(resists) if resists else None

            # Stats
            try:
                level = format_level_text(resists.get('level', '--'), resists.get('maxlevel', 0))
                hp = resists.get('hp', '--')
                mana = resists.get('mana', '--')
                ac = resists.get('ac', '--')
                mindmg = resists.get('mindmg', 0)
                maxdmg = resists.get('maxdmg', 0)
                self.stats_labels['level'].setText(f"Lv:{level}")
                self.stats_labels['hp'].setText(f"HP:{hp}")
                self.stats_labels['mana'].setText(f"Mana:{mana}")
                self.stats_labels['ac'].setText(f"AC:{ac}")
                try:
                    mindmg_i = int(mindmg or 0)
                    maxdmg_i = int(maxdmg or 0)
                    dmg_text = "--" if (mindmg_i == 0 and maxdmg_i == 0) else f"{mindmg_i}-{maxdmg_i}"
                except Exception:
                    dmg_text = "--"
                if 'dmg' in self.stats_labels:
                    self.stats_labels['dmg'].setText(f"Dmg:{dmg_text}")
            except Exception:
                pass

            # NPC name + zone
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
            self.name_label.setText(str(display_name)[:64])

            # Resists
            for key in self.resist_labels:
                value = resists.get(key, 0)
                color = _resist_color(value)
                self.resist_labels[key].setText(f"{key}:{value}")
                self.resist_labels[key].setStyleSheet(_make_label_style(color, 10, True))

            # Special abilities
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
                if labels:
                    self.special_label.setText(self._format_specials(labels))
                else:
                    self.special_label.setText("-")

            self._apply_visibility()

        def _format_specials(self, labels: str) -> str:
            items = [p.strip() for p in str(labels).split(',') if p.strip()]
            if not items:
                return ""
            lines = []
            current = []
            limit = int(self._specials_wrap_chars) if self._specials_wrap_chars else 72
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

        # ---- Close / cleanup ------------------------------------------------

        def _on_close(self):
            self._cleanup_hotkey()
            if self._tray_icon is not None:
                self._tray_icon.hide()
                self._tray_icon = None
            QApplication.instance().quit()

        def closeEvent(self, event):
            self._on_close()
            event.accept()

else:
    # PyQt6 not available
    ResistOverlayGUI = None
