"""Other SteelSeries mice: detection, settings, button mapping and pictures, from the device descriptions
of the open-source rivalcfg project (WTFPL, https://github.com/flozz/rivalcfg).

The Aerox 3 Wireless keeps its own full-featured code path in aerox_lite.py. Every other mouse that
rivalcfg describes is found here by its USB product ID; its settings (CPI, polling rate, colours,
effects, timers, ...) become a panel of ordinary controls. Nothing is downloaded: the descriptions
of all supported models are part of the app and rivalcfg is imported only when such a mouse is
looked for (no Aerox 3 found).
"""
import re
import sys
import threading

VID = 0x1038
CMD_DELAY = 0.02
GROUPS = ("Performance", "Lighting", "Power", "Other", "Buttons")
BUTTON_LABELS = {"button1": "Left button", "button2": "Right button", "button3": "Wheel click",
                 "button4": "Side back", "button5": "Side forward", "tiltleft": "Wheel tilt left",
                 "tiltright": "Wheel tilt right", "scrollup": "Scroll up", "scrolldown": "Scroll down"}
# picture (model_art.py) for each model family: first matching name prefix wins
ART_FAMILIES = [("Aerox 5", "aerox-5"), ("Aerox 9", "aerox-9"), ("Prime Mini", "prime-mini"), ("Prime", "prime"),
                ("Rival 3", "rival-3"), ("Rival 5", "rival-5"), ("Rival 95", "rival-95"), ("Rival 100", "rival-100"),
                ("Rival 105", "rival-100"), ("Rival 106", "rival-100"), ("Rival 110", "rival-100"),
                ("Rival 310", "rival-310"), ("Rival 300", "rival-300"), ("Rival 500", "rival-500"),
                ("Rival 600", "rival-600"), ("Rival 650", "rival-600"), ("Rival 700", "rival-700"),
                ("Rival 710", "rival-700"), ("Rival", "rival-300"), ("Sensei [RAW]", "sensei-raw"),
                ("Sensei", "sensei"), ("Kana", "kana-v2"), ("Kinzu", "kinzu-v2")]


def art_slug(name):
    """Picture for a model name ('Rival 3 Wireless' -> 'rival-3'); None for the Aerox 3 (own picture)."""
    for prefix, slug in ART_FAMILIES:
        rest = name[len(prefix):]
        if name.startswith(prefix) and (not rest or not rest[0].isdigit()):
            return slug
    return None


def button_list(setting):
    """[(name, label, default)] of a mouse's buttons in a natural order (Button1.., tilt, scroll)."""
    def order(k):
        m = re.fullmatch(r"button(\d+)", k.lower())
        return (0, int(m.group(1))) if m else (1, ["tiltleft", "tiltright", "scrollup", "scrolldown"].index(k.lower())
                                                  if k.lower() in ("tiltleft", "tiltright", "scrollup", "scrolldown") else 9)
    out = []
    for k in sorted(setting["buttons"], key=order):
        low = k.lower()
        num = re.fullmatch(r"button(\d+)", low)
        label = BUTTON_LABELS.get(low) or ("Button {0}".format(num.group(1)) if num else _label(k))
        out.append((k, label, str(setting["buttons"][k].get("default", low)).lower()))
    return out


def button_value(app_value, spec):
    """App binding ('button2', 'dpi', 'key:A', 'media:Mute', 'macro:3', ...) -> rivalcfg value, or None.
    A macro is the key F13 + slot: the app hears that key and plays the macro (as with the Aerox 3)."""
    v, act = str(app_value), spec["actions"]
    names = {b[0].lower() for b in spec["buttons"]}
    if v in names: return v
    if v == "dpi": return v if act["dpi"] else None
    if v in ("scrollup", "scrolldown"): return v if (act["scroll"] or v in names) else None
    if v == "disabled": return v if act["disabled"] else None
    if v.startswith("key:") and act["keys"] and re.fullmatch(r"[A-Za-z0-9]+", v[4:]): return v[4:]
    if v.startswith("media:") and act["media"] and v[6:] in ("Mute", "Next", "PlayPause", "Previous", "VolumeUp", "VolumeDown"):
        return v[6:]
    if v.startswith("macro:") and act["keys"] and v[6:].isdigit() and 0 <= int(v[6:]) < 12:
        return "F{0}".format(13 + int(v[6:]))
    return None
COLOR_TYPES = ("rgbcolor", "rgbgradient", "rgbgradientv2")
DPI_TYPES = ("multidpi_range", "multidpi_range_choice", "multidpi_range_choice_xy")
_rc = None


def _rivalcfg(hid_mod):
    """Import rivalcfg once. It imports `hid` at load time; when the app uses another backend with
    the same API (Linux: hidraw), that module stands in, as rivalcfg never opens devices itself here."""
    global _rc
    if _rc is None:
        if hid_mod is not None and "hid" not in sys.modules:
            sys.modules["hid"] = hid_mod
        from rivalcfg import devices, mouse, color_helpers
        _rc = (devices, mouse, color_helpers)
    return _rc


def profiles(hid_mod=None):
    """{(vid, pid): rivalcfg profile} of every supported mouse."""
    return _rivalcfg(hid_mod)[0].PROFILES


def short_name(profile):
    """'SteelSeries Aerox 5 Wireless (2.4 GHz wireless mode)' -> 'Aerox 5 Wireless'."""
    name = re.sub(r"\s*\([^)]*\bmode\)\s*$", "", profile["name"])
    return name[len("SteelSeries "):] if name.startswith("SteelSeries ") else name


def device_key(pid):
    return "{0:04x}:{1:04x}".format(VID, pid)


class _NoStore:
    """rivalcfg keeps its own settings file; the app stores settings in its own config instead."""
    def set(self, *args): pass
    def get(self, *args): return None
    def save(self): pass


# ---------------------------------------------------------------- settings description
def _label(text):
    text = str(text or "").strip()
    return text[:1].upper() + text[1:]


def _group(name, vtype):
    if "sensitivity" in name or name == "polling_rate" or name.startswith("btn"): return "Performance"
    if "timer" in name: return "Power"
    if (vtype in COLOR_TYPES or vtype == "reactive_rgbcolor" or "light" in name or "effect" in name
            or "brightness" in name or "color" in name): return "Lighting"
    return "Other"


def specs(profile):
    """Settings of one mouse as plain dicts the panel can draw:
    {name, label, kind (choice|range|dpi|color|reactive|action), group, default, choices, range, max}.
    Button remapping is left out (it needs the per-model button layout editor of the Aerox 3)."""
    out = []
    for name, s in profile["settings"].items():
        vtype = s.get("value_type")
        spec = {"name": name, "label": _label(s.get("label") or name.replace("_", " ")),
                "group": _group(name, vtype), "default": s.get("default")}
        if vtype == "choice":
            seen, choices = set(), []
            for key, value in s["choices"].items():  # several names may mean the same value
                if repr(value) in seen: continue
                seen.add(repr(value)); choices.append(key)
            spec.update(kind="choice", choices=choices)
        elif vtype in ("range", "range_choice"):
            lo, hi, step = s["input_range"]
            spec.update(kind="range", range=(lo, hi, step))
        elif vtype in DPI_TYPES:
            lo, hi, step = s["input_range"]
            spec.update(kind="dpi", range=(lo, hi, step), max=s.get("max_preset_count", 5))
        elif vtype in COLOR_TYPES or vtype == "rgbuniversal":
            spec.update(kind="color", label=spec["label"].replace(" colors and effects", " color"))
        elif vtype == "reactive_rgbcolor":
            spec.update(kind="reactive")
        elif vtype == "none":
            spec.update(kind="action")
        elif vtype == "buttons":
            spec.update(kind="buttons", group="Buttons", label="Buttons", buttons=button_list(s),
                        actions={"dpi": s.get("button_dpi_switch") is not None,
                                 "scroll": s.get("button_scroll_up") is not None,
                                 "disabled": s.get("button_disable") is not None,
                                 "keys": s.get("button_keyboard") is not None,
                                 "media": s.get("button_multimedia") is not None})
        else:
            continue  # anything new
        out.append(spec)
    order = {g: i for i, g in enumerate(GROUPS)}
    return sorted(out, key=lambda x: order[x["group"]])


def parse_dpi(value, spec):
    """'400, 800' or [400, 800] -> valid list of CPI levels (clamped, rounded to the step), or None."""
    if isinstance(value, str): parts = re.split(r"[,;\s]+", value.strip())
    elif isinstance(value, (list, tuple)): parts = list(value)
    else: return None
    lo, hi, step = spec["range"]
    levels = []
    for p in parts:
        if p in ("", None): continue
        try: n = float(p)
        except (TypeError, ValueError): return None
        n = int(round(n / step) * step)
        levels.append(max(lo, min(hi, n)))
    return levels[:spec.get("max", 5)] or None


def valid_value(spec, value):
    """The value in the form the mouse accepts, or None if it does not fit this setting."""
    kind = spec["kind"]
    if kind == "choice":
        for c in spec["choices"]:
            if str(c) == str(value): return c
        return None
    if kind == "range":
        if isinstance(value, bool): return None
        try: n = float(value)
        except (TypeError, ValueError): return None
        lo, hi, step = spec["range"]
        n = round(n / step) * step
        return int(max(lo, min(hi, n))) if float(step).is_integer() else max(lo, min(hi, n))
    if kind == "dpi":
        return parse_dpi(value, spec)
    if kind == "color":
        return value if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else None
    if kind == "reactive":
        if value == "off": return "off"
        return value if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else None
    if kind == "buttons":  # {"Button2": "key:A", ...} -> rivalcfg mapping; unknown values fall back to default
        if not isinstance(value, dict): return None
        mapping = {}
        for name, _, _ in spec["buttons"]:
            v = value.get(name)
            r = button_value(v, spec) if v is not None else None
            mapping[name] = r if r is not None else "default"
        return {"buttons": mapping}
    return None


def color_hex(value, fallback="#808080"):
    """A colour for the swatch: '#rrggbb', a colour name, or the first colour of a gradient."""
    if isinstance(value, str):
        m = re.search(r"#[0-9a-fA-F]{6}", value)
        if m: return m.group(0).lower()
        if _rc is not None:
            try: return "#%02x%02x%02x" % tuple(_rc[2].parse_color_string(value))
            except Exception: pass
    return fallback


# ---------------------------------------------------------------- device
class GenericMouse:
    """Same small interface as aerox_lite.Mouse (open/close/connected/battery/drain/lock/...)."""
    generic = True

    def __init__(self, hid_mod, exclude=()):
        self.hid, self.exclude = hid_mod, set(exclude)
        self.lock = threading.RLock()
        self.dev = self.rc = self.profile = None
        self.pid, self.product, self.key, self.diag, self.wireless = 0, "", "", "", False
        self.specs = []

    def connected(self): return self.rc is not None

    @property
    def has_battery(self):
        return bool(self.profile and "battery_level" in self.profile)

    def open(self, scan=None):
        """scan: the result of hid.enumerate(VID, 0) when the caller already has it."""
        with self.lock:
            if self.rc: return True
            scan = list(self.hid.enumerate(VID, 0) if scan is None else scan)
            if not any(d.get("product_id") not in self.exclude for d in scan):
                self.diag = ""; return False   # no other SteelSeries device: rivalcfg is not even loaded
            devices, mouse, _ = _rivalcfg(self.hid)
            cands, errors = [], []
            for d in scan:
                pid = d.get("product_id", 0)
                prof = devices.PROFILES.get((VID, pid))
                if pid in self.exclude or not prof: continue
                iface = d.get("interface_number")
                if iface == prof["endpoint"]: rank = 0
                elif iface in (-1, None) and d.get("usage_page", 0) >= 0xFF00: rank = 1  # backend without interface numbers
                else: continue
                cands.append((rank, d, prof))
            # vendor-defined collections first (Windows lists the system mouse collection too, which cannot be written)
            for _, d, prof in sorted(cands, key=lambda c: (c[0], c[1].get("usage_page", 0) < 0xFF00)):
                try:
                    h = self.hid.device(); h.open_path(d["path"])
                except (OSError, IOError) as e:
                    errors.append((d, e)); continue
                try:
                    self.rc = mouse.Mouse(h, prof, _NoStore(), command_delay=CMD_DELAY)
                except Exception as e:
                    try: h.close()
                    except Exception: pass
                    errors.append((d, e)); continue
                self.dev, self.profile, self.pid = h, prof, d["product_id"]
                self.product, self.key = short_name(prof), device_key(self.pid)
                self.wireless = "wireless mode" in prof["name"].lower()
                self.specs, self.diag = specs(prof), ""
                return True
            if errors:
                d, e = errors[0]
                self.diag = "HID: found the {0} but could not open it: {1}".format(
                    short_name(devices.PROFILES[(VID, d["product_id"])]), e)
            else:
                self.diag = ""
            return False

    def close(self):
        with self.lock:
            try:
                if self.dev: self.dev.close()
            except Exception: pass
            self.dev = self.rc = None

    def _io(self, fn, *args):
        """Run one rivalcfg call; a failed USB transfer means the mouse is gone."""
        with self.lock:
            if not self.rc: raise IOError("no device")
            try:
                return fn(*args)
            except (OSError, IOError) as e:
                self.close(); raise IOError(str(e))

    def apply(self, values, names=None):
        """Send settings ({name: value}); returns a list of (name, error) for values the mouse refused."""
        refused = []
        by_name = {s["name"]: s for s in self.specs}
        for name in (names if names is not None else list(values)):
            spec = by_name.get(name)
            if spec is None or spec["kind"] == "action" or name not in values: continue
            value = valid_value(spec, values[name])
            if value is None: refused.append((name, "invalid value")); continue
            try:
                self._io(getattr(self.rc, "set_" + name), value)
            except ValueError as e:
                refused.append((name, str(e)))
        return refused

    def run(self, name):
        self._io(getattr(self.rc, "set_" + name))

    def save(self):
        if self.profile and self.profile.get("save_command"):
            self._io(self.rc.save)

    def battery(self):
        with self.lock:
            if not self.rc: return None, None
            if not self.has_battery:  # wired mouse: only check that it is still plugged in
                try: present = any(d.get("product_id") == self.pid for d in self.hid.enumerate(VID, self.pid))
                except Exception: present = True
                if not present: self.close()
                return None, None
            try:
                b = self.rc.battery
            except (OSError, IOError, ValueError):
                self.close(); return None, None
            return b.get("level"), b.get("is_charging")

    def drain(self): return []
