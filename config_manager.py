import json
import sys
from pathlib import Path


class ConfigManager:
    """Manage config file for EQ log path"""

    def __init__(self):
        self.config_dir = Path(__file__).parent if not hasattr(sys, 'frozen') else Path(sys.executable).parent
        self.config_file = self.config_dir / 'config.json'
        self.config = self._load_config()

    def _load_config(self):
        """Load config from file"""
        defaults = {
            'eq_log_path': None,
            # Tk alpha (0.0-1.0). Lower = more transparent.
            'overlay_opacity': 0.88,
            # Overlay window position (screen coordinates)
            # Stored as {"x": int, "y": int}
            'overlay_position': {'x': 50, 'y': 50},
            # Whether to show the stats row (level/HP/mana/AC).
            'show_stats': True,
            # Whether to show resist values in the overlay.
            'show_resists': True,
            # Whether to show special abilities in the overlay.
            'show_special_abilities': False,
            # Optional filter of which special ability IDs to show.
            # Stored as {"10": true, "14": false, ...}. Missing IDs default to shown.
            'special_abilities_filter': {},
        }

        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    merged = dict(defaults)
                    merged.update(loaded)
                    return merged
            except Exception:
                pass
        return defaults

    def get_overlay_position(self) -> tuple[int, int]:
        """Get overlay position as (x, y)."""
        pos = self.config.get('overlay_position', None)
        try:
            if isinstance(pos, dict):
                x = int(pos.get('x', 50))
                y = int(pos.get('y', 50))
            elif isinstance(pos, (list, tuple)) and len(pos) >= 2:
                x = int(pos[0])
                y = int(pos[1])
            else:
                x, y = 50, 50
        except Exception:
            x, y = 50, 50
        return x, y

    def set_overlay_position(self, x: int, y: int):
        """Set and save overlay position."""
        try:
            self.config['overlay_position'] = {'x': int(x), 'y': int(y)}
        except Exception:
            return False
        return self.save_config()

    def save_config(self):
        """Save config to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            return True
        except Exception:
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

    def get_show_special_abilities(self):
        """Get whether to show special abilities in the overlay."""
        return bool(self.config.get('show_special_abilities', False))

    def set_show_special_abilities(self, value: bool):
        """Set and save whether to show special abilities in the overlay."""
        self.config['show_special_abilities'] = bool(value)
        return self.save_config()

    def get_special_abilities_filter(self):
        value = self.config.get('special_abilities_filter', {})
        return value if isinstance(value, dict) else {}

    def set_special_abilities_filter(self, value: dict):
        self.config['special_abilities_filter'] = value if isinstance(value, dict) else {}
        return self.save_config()

    def set_special_ability_enabled(self, ability_id: int, enabled: bool):
        filt = self.get_special_abilities_filter()
        filt[str(int(ability_id))] = bool(enabled)
        return self.set_special_abilities_filter(filt)

    def get_show_resists(self):
        """Get whether to show resist values in the overlay."""
        return bool(self.config.get('show_resists', True))

    def set_show_resists(self, value: bool):
        """Set and save whether to show resist values in the overlay."""
        self.config['show_resists'] = bool(value)
        return self.save_config()

    def get_show_stats(self):
        """Get whether to show level/HP/mana/AC stats in the overlay."""
        return bool(self.config.get('show_stats', True))

    def set_show_stats(self, value: bool):
        """Set and save whether to show level/HP/mana/AC stats in the overlay."""
        self.config['show_stats'] = bool(value)
        return self.save_config()
