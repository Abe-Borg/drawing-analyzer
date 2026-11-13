"""Small persisted GUI preferences (``gui_preferences.json`` in the config dir).

Holds user choices that should survive a restart but are not secrets and not
run inputs — whether the full-QC cost confirmation is shown, whether the
Activity section shows the Live view board or the log, and the budget cap.
Every
read tolerates a missing, unreadable, or corrupt file (it reads as "no
preference set"), and every write is best-effort: a preference that cannot be
saved must never block a run.
"""
from __future__ import annotations

import json
from pathlib import Path

from .app_paths import app_config_dir

PREFERENCES_FILENAME = "gui_preferences.json"

# True once the user ticks "Don't show this again" on the full-QC cost
# confirmation and proceeds. The QC section's "Confirm estimated cost" box
# turns it back off.
SKIP_FULL_QC_CONFIRM = "skip_full_qc_cost_confirm"
# The budget cap beside the Analyze button: whether it is on, and the dollar
# amount as the user typed it (kept as text so an off cap keeps its figure).
BUDGET_CAP_ENABLED = "budget_cap_enabled"
BUDGET_CAP_AMOUNT = "budget_cap_amount"

# Whether the Activity section shows the Live view board (True, the default)
# or the log. The Live view | Log toggle sets it.
LIVE_VIEW = "live_view"


def default_preferences_path() -> Path:
    return app_config_dir() / PREFERENCES_FILENAME


def load_preferences(path: str | Path) -> dict:
    """The stored preferences, or ``{}`` when the file is missing or unusable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get_bool(path: str | Path, key: str, default: bool = False) -> bool:
    """One boolean preference; anything that is not a real bool reads as ``default``."""
    value = load_preferences(path).get(key, default)
    return value if isinstance(value, bool) else default


def get_str(path: str | Path, key: str, default: str = "") -> str:
    """One text preference; anything that is not a string reads as ``default``."""
    value = load_preferences(path).get(key, default)
    return value if isinstance(value, str) else default


def set_preference(path: str | Path, key: str, value) -> bool:
    """Write one preference, keeping the others. Returns whether it was saved."""
    prefs = load_preferences(path)
    prefs[key] = value
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(prefs, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return False
    return True
