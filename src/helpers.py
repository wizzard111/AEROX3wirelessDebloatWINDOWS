"""
helpers.py — helper module state WITHOUT importing the modules.

On startup Aerox Lite reads which modules are enabled here and imports only those:
a disabled module is not loaded and uses no resources.
Also stores, for the "Helper functions" tray item, which modules were enabled
before the global "off", so exactly those can be restored.
"""
import os, json

APPDIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AeroxLite")
MODULES = ("directional", "rclick", "battery")
TRAY_MODULES = ("directional", "rclick")  # tray item: multi-click + directional sensitivity (battery is left alone)
FILES = {
    "directional": ("directional_state.json", False),
    "rclick": ("rclick.json", False),
    "battery": ("smartbattery.json", True),
}
STATE_PATH = os.path.join(APPDIR, "helpers.json")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def module_on(name):
    fname, default = FILES[name]
    value = _read(os.path.join(APPDIR, fname)).get("enabled", default)
    return value is True


def remember(names):
    """Remember what was enabled before the global "off" (None — forget)."""
    os.makedirs(APPDIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"saved": list(names) if names else None}, f)
    os.replace(tmp, STATE_PATH)


def recall():
    saved = _read(STATE_PATH).get("saved")
    return [n for n in saved if n in MODULES] if isinstance(saved, list) else []


def read_json(fname):
    """Read a module JSON file from %APPDATA%\\AeroxLite (for display in the UI)."""
    return _read(os.path.join(APPDIR, fname))
