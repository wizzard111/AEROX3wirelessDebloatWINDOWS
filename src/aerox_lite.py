"""
Aerox Lite — a lightweight SteelSeries GG replacement for the Aerox 3 Wireless (2020/2022, Snow/Ghost).
The protocol comes from the open-source rivalcfg project (reverse engineering).
Tray with battery level, CPI, polling rate, timers, bindings, lighting (including software effects).

IMPORTANT: close SteelSeries GG / SteelSeries Engine before starting (and remove it from autostart) —
GG is the most common reason the lighting gets overwritten and looks "unstable".
"""
import os, sys, json, time, math, threading, queue, colorsys
from collections import deque
from types import SimpleNamespace
import copy, logging
from config_store import normalize, atomic_save
import tkinter as tk
from tkinter import colorchooser, filedialog

import hid
import pystray
import io, base64
from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageChops, ImageFilter

import mouse_art
import generic  # other SteelSeries mice (rivalcfg device descriptions)
import helpers  # module state without importing the modules

try:
    import winput  # raw input + macros (Windows only)
except Exception:
    winput = None

APP = "Aerox Lite"
VID, IFACE = 0x1038, 3
# PID -> True = wireless dongle (2.4 GHz), False = USB cable
KNOWN_PIDS = {0x183A: False, 0x187A: False, 0x1838: True, 0x1878: True}
WIRELESS_FLAG = 0x40
CMD_DELAY = 0.03
HID_PERMISSION_HINT = ""

CFG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AeroxLite")
CFG_PATH = os.path.join(CFG_DIR, "config.json")

# TrueMove Air sensor CPI table: 100..18000 in steps of 100 -> byte
DPI_CODES = [0, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 16, 17, 18, 19, 20, 22, 23, 24, 25, 26, 27, 29, 30, 31, 32, 33, 35, 37, 38, 39, 40, 41, 42, 44, 45, 46, 47, 48, 50, 51, 52, 53, 54, 56, 57, 58, 59, 60, 62, 63, 64, 65, 66, 68, 69, 70, 71, 72, 74, 75, 76, 77, 78, 80, 81, 82, 83, 84, 86, 87, 88, 89, 90, 92, 93, 94, 95, 96, 98, 99, 100, 101, 102, 104, 105, 106, 107, 108, 110, 111, 112, 113, 114, 116, 117, 118, 119, 120, 122, 123, 124, 125, 126, 128, 129, 130, 131, 132, 134, 135, 136, 137, 138, 140, 141, 142, 143, 144, 146, 147, 148, 149, 150, 152, 153, 154, 155, 156, 158, 159, 160, 161, 162, 164, 165, 166, 167, 168, 170, 171, 172, 173, 174, 176, 177, 178, 179, 180, 181, 182, 183, 184, 185, 186, 187, 188, 189, 191, 192, 194, 195, 196, 197, 198, 199, 201, 202, 203, 204, 205, 207, 208, 209, 210, 211, 213, 214]
ECHO_CMDS = {0x11, 0x21, 0x22, 0x23, 0x26, 0x27, 0x29, 0x2A, 0x2B, 0x2D, 0x92}
POLL = {125: 0x03, 250: 0x02, 500: 0x01, 1000: 0x00}

# ---- Bindings ----
SLOTS = [  # (label, diagram tag, packet offset, default)
    ("Left button", "B1", 0x00, "button1"), ("Right button", "B2", 0x05, "button2"),
    ("Wheel click", "B3", 0x0A, "button3"), ("Side back", "B4", 0x0F, "button4"),
    ("Side forward", "B5", 0x14, "button5"), ("Top button", "B6", 0x19, "dpi"),
    ("Scroll up", "", 0x1E, "scrollup"), ("Scroll down", "", 0x23, "scrolldown"),
]
SPECIAL = {"button1": 0x01, "button2": 0x02, "button3": 0x03, "button4": 0x04, "button5": 0x05,
           "button6": 0x06, "scrollup": 0x31, "scrolldown": 0x32, "dpi": 0x30, "disabled": 0x00}
SPECIAL_NAMES = [("Left click", "button1"), ("Right click", "button2"), ("Middle click", "button3"),
                 ("Back", "button4"), ("Forward", "button5"), ("Cycle CPI", "dpi"),
                 ("Scroll up", "scrollup"), ("Scroll down", "scrolldown"), ("Disabled", "disabled")]
MEDIA = {"PlayPause": ("Play / Pause", 0xCD), "Next": ("Next track", 0xB5), "Previous": ("Previous track", 0xB6),
         "VolumeUp": ("Volume +", 0xE9), "VolumeDown": ("Volume −", 0xEA), "Mute": ("Mute", 0xE2)}
KEYS = {}
for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"): KEYS[ch] = 0x04 + i
for i, ch in enumerate("1234567890"): KEYS[ch] = 0x1E + i
for i in range(12): KEYS[f"F{i+1}"] = 0x3A + i
for i in range(12): KEYS[f"F{i+13}"] = 0x68 + i  # F13–F24: macro triggers
MAX_MACROS = 12
KEYS.update({"Enter": 0x28, "Esc": 0x29, "Backspace": 0x2A, "Tab": 0x2B, "Space": 0x2C,
             "PrintScreen": 0x46, "Insert": 0x49, "Home": 0x4A, "PageUp": 0x4B, "Delete": 0x4C,
             "End": 0x4D, "PageDown": 0x4E, "Right": 0x4F, "Left": 0x50, "Down": 0x51, "Up": 0x52,
             "LCtrl": 0xE0, "LShift": 0xE1, "LAlt": 0xE2, "Win": 0xE3})


KEY_GROUPS = (('Letters', list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")), ('Numbers', list("1234567890")),
              ("F1–F12", [f"F{k}" for k in range(1, 13)]),
              ('Navigation', ["Enter", "Esc", "Backspace", "Tab", "Space", "PrintScreen", "Insert", "Delete",
                              "Home", "End", "PageUp", "PageDown", "Up", "Down", "Left", "Right"]),
              ('Modifiers', ["LCtrl", "LShift", "LAlt", "Win"]))


def action_name(v, macros=()):
    for n, k in SPECIAL_NAMES:
        if k == v: return n
    if v.startswith("macro:"):
        for m in macros:
            if v[6:].isdigit() and m["slot"] == int(v[6:]): return 'Macro: ' + m["name"]
        return 'Macro (deleted)'
    if v.startswith("key:"): return 'Key ' + v[4:]
    if v.startswith("media:"): return MEDIA[v[6:]][0] if v[6:] in MEDIA else v
    return v


def encode_buttons(binds):
    pkt = [0] * 40
    for i, (_, _, off, default) in enumerate(SLOTS):
        v = binds[i] if i < len(binds) else default
        if v in SPECIAL: pkt[off] = SPECIAL[v]
        elif v.startswith("key:") and v[4:] in KEYS: pkt[off], pkt[off + 1] = 0x51, KEYS[v[4:]]
        elif v.startswith("media:") and v[6:] in MEDIA: pkt[off], pkt[off + 1] = 0x61, MEDIA[v[6:]][1]
        elif v.startswith("macro:") and v[6:].isdigit() and 0 <= int(v[6:]) < MAX_MACROS: pkt[off], pkt[off + 1] = 0x51, 0x68 + int(v[6:])
        else: pkt[off] = SPECIAL[default]
    return pkt


def le3(n): n = int(n); return [n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF]
def dpi_byte(d): return DPI_CODES[max(1, min(180, round(d / 100))) - 1]
def hex2rgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
def rgb2hex(c): return "#%02x%02x%02x" % tuple(int(x) for x in c)
def scale(c, k): return tuple(max(0, min(255, int(x * k))) for x in c)
def hsv(h): return tuple(int(x * 255) for x in colorsys.hsv_to_rgb(h % 1, 1, 1))


class _CappedLog(logging.FileHandler):
    """Log file of at most max_bytes; the previous one is kept as .1 (logging.handlers would pull in
    socket and pickle at start-up just for this)."""
    def __init__(self, path, max_bytes):
        super().__init__(path, encoding="utf-8", delay=True)
        self.max_bytes = max_bytes

    def emit(self, record):
        try:
            if self.stream is not None and self.stream.tell() > self.max_bytes:
                self.stream.close(); self.stream = None
                os.replace(self.baseFilename, self.baseFilename + ".1")
        except OSError: pass
        super().emit(record)


# ---------------------------------------------------------------- Device
class Mouse:
    generic, has_battery = False, True

    def __init__(self):
        self.dev, self.wireless, self.lock = None, False, threading.RLock()
        self.diag = ""
        self.pid, self.product = 0, ""
        self.unsolicited = deque(maxlen=50)  # reports the mouse sent on its own

    def connected(self): return self.dev is not None

    def open(self, scan=None):
        """scan: the result of hid.enumerate(VID, 0) when the caller already has it."""
        with self.lock:
            if self.dev: return True
            cands, found, errors = [], [], []
            for d in (hid.enumerate(VID, 0) if scan is None else scan):
                found.append(d)
                iface = d.get("interface_number")
                # hidraw cannot always tell the interface number (-1): fall back to the vendor usage page
                if iface != IFACE and not (iface in (-1, None) and d.get("usage_page", 0) >= 0xFF00): continue
                pid, prod = d["product_id"], (d.get("product_string") or "").lower()
                if pid in KNOWN_PIDS: cands.append((1 if KNOWN_PIDS[pid] else 0, d, KNOWN_PIDS[pid]))
                elif "aerox 3" in prod: cands.append((2, d, None))
            for _, d, wl in sorted(cands, key=lambda c: c[0]):  # cable takes priority over dongle
                try:
                    h = hid.device(); h.open_path(d["path"])
                except (OSError, IOError) as e:
                    errors.append((d, e))
                    continue
                self.dev, self.pid, self.product = h, d["product_id"], d.get("product_string") or "Aerox 3"
                self.wireless = wl if wl is not None else not self._probe_wired()
                self.diag = ""
                return True
            self.diag = hid_diagnosis(found, cands, errors)
            return False

    def _probe_wired(self):
        try:
            self._write_report(bytes([0, 0x92])); r = self.dev.read(64, timeout_ms=200)
            return bool(r) and r[0] == 0x92
        except Exception:
            return False

    def close(self):
        with self.lock:
            try:
                if self.dev: self.dev.close()
            except Exception: pass
            self.dev = None

    def _write_report(self, report):
        # Windows HIDAPI pads to OutputReportByteLength and returns that larger
        # count. Accept padding; reject errors, zero and truncated writes.
        written = self.dev.write(report)
        if written < len(report):
            raise IOError(f"HID write: expected >= {len(report)} bytes, got {written}")
        return written

    def _cmd(self, data, fast=False):
        with self.lock:
            if not self.dev: raise IOError('no device')
            data = list(data)
            if self.wireless: data[0] |= WIRELESS_FLAG
            try:
                self._write_report(bytes([0] + data))
                if self.wireless: self.dev.read(64, timeout_ms=60 if fast else 200)  # dongle ack
            except (OSError, IOError, ValueError) as e:
                self.close(); raise IOError(str(e))
            if not fast: time.sleep(CMD_DELAY)

    def battery(self):
        with self.lock:
            if not self.dev: return None, None
            cmd = 0x92 | (WIRELESS_FLAG if self.wireless else 0)
            try:
                self._drain()
                self._write_report(bytes([0, cmd]))
                best = None
                for _ in range(5):
                    r = self.dev.read(64, timeout_ms=200)
                    if not r: break
                    if r[0] == cmd: best = r; break
                    self.unsolicited.append(bytes(r))
            except (OSError, IOError, ValueError):
                self.close(); return None, None
            if not best or len(best) < 2: return None, None
            lvl = ((best[1] & 0x7F) - 1) * 5
            if not 0 <= lvl <= 100: return None, None  # mouse is off / asleep
            return lvl, bool(best[1] & 0x80)

    def _drain(self):
        for _ in range(64):
            r = self.dev.read(64, timeout_ms=1)
            if not r: break
            self.unsolicited.append(bytes(r))

    def drain(self):
        """Drain reports the mouse sent on its own interface (called once per second, under the lock)."""
        with self.lock:
            if not self.dev: return []
            try: self._drain()
            except (OSError, IOError, ValueError): self.close()
            out = list(self.unsolicited); self.unsolicited.clear()
            return out

    def set_dpi(self, levels, active): self._cmd([0x2D, len(levels), active] + [dpi_byte(x) for x in levels])
    def set_poll(self, hz): self._cmd([0x2B, POLL[hz]])
    def set_zone(self, z, rgb, fast=False): self._cmd([0x21, 0x01, z] + list(rgb), fast)
    def set_rainbow(self): self._cmd([0x22, 0xFF])
    def set_reactive(self, rgb): self._cmd([0x26] + ([0] * 5 if rgb is None else [1, 0] + list(rgb)))
    def set_default_light(self, rainbow, reactive): self._cmd([0x27, int(rainbow), int(reactive)])
    def set_sleep(self, minutes): self._cmd([0x29] + le3(minutes * 60000))
    def set_dim(self, seconds): self._cmd([0x23, 0x0F, 0x01, 0x00, 0x00] + le3(seconds * 1000))
    def set_buttons(self, binds): self._cmd([0x2A] + encode_buttons(binds))
    def save(self): self._cmd([0x11, 0x00])


def hid_diagnosis(found, cands, errors):
    """One log line explaining why no mouse could be opened."""
    if not found:
        return "HID: no SteelSeries device (VID 1038) is visible"
    seen = ", ".join("PID 0x{0:04X} interface {1}".format(d.get("product_id", 0), d.get("interface_number"))
                     for d in found[:8])
    if not cands:
        return "HID: SteelSeries interfaces found ({0}), but none is a supported mouse".format(seen)
    d, e = errors[0] if errors else (cands[0][1], "unknown error")
    path = d.get("path", b"")
    path = path.decode(errors="replace") if isinstance(path, bytes) else str(path)
    msg = "HID: found the Aerox 3 ({0}) but could not open {1}: {2}".format(seen, path, e)
    if os.path.exists(path) and not os.access(path, os.R_OK | os.W_OK):
        msg += " (no permission). " + HID_PERMISSION_HINT
    return msg


# ---------------------------------------------------------------- Config
DEFAULT = {
    "dpi": [200, 400, 1200, 2400, 3200], "dpi_active": 1, "poll": 1000,
    "sleep": 5, "dim": 30, "binds": [s[3] for s in SLOTS],
    "light": {"mode": "static", "colors": ["#ffffff", "#ffffff", "#ffffff"], "brightness": 100,
              "speed": 40, "reactive": False, "reactive_color": "#ffffff"},
    "apply_on_connect": True, "autostart": False, "fps": 15,
    "eco": False, "smart_light": False, "smart_delay": 0.6, "verbose_log": False,
    "ui_scale": 1.0, "theme": "dark",
    "devices": {},  # other mice: {"1038:pid": {setting: value}}
    "macros": [],  # {"slot": 0..11, "name": str, "mode": once|hold|toggle, "script": str}
}
SOFT = ("breathing", "wave", "cycle")
MODES = [("static", "Static"), ("off", "Off"), ("rainbow_hw", "Rainbow (hardware)"),
         ("breathing", "Breathing *"), ("wave", "Wave *"), ("cycle", "Color cycle *")]


def load_cfg():
    try:
        with open(CFG_PATH, encoding="utf-8") as f: user = json.load(f)
    except (OSError, ValueError): user = {}
    return normalize(DEFAULT, user, KEYS, SPECIAL, MEDIA, dict(MODES), MAX_MACROS)


def save_cfg(cfg):
    atomic_save(CFG_PATH, cfg)


def effect_frame(L, t):
    sp, mode = 0.15 + L["speed"] / 100 * 1.6, L["mode"]
    base = [hex2rgb(c) for c in L["colors"]]
    if mode == "breathing":
        k = (1 - math.cos(t * sp * math.pi)) / 2
        cols = [scale(c, k) for c in base]
    elif mode == "wave":
        cols = [hsv(t * sp * 0.2 + i * 0.12) for i in range(3)]
    elif mode == "cycle":
        cols = [hsv(t * sp * 0.2)] * 3
    else:
        cols = base
    return [scale(c, L["brightness"] / 100) for c in cols]


def set_autostart(on):
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if on:
            if getattr(sys, "frozen", False): cmd = f'"{sys.executable}" --tray'
            else:
                pyw = sys.executable.replace("python.exe", "pythonw.exe")
                cmd = f'"{pyw}" "{os.path.abspath(__file__)}" --tray'
            winreg.SetValueEx(key, "AeroxLite", 0, winreg.REG_SZ, cmd)
        else:
            try: winreg.DeleteValue(key, "AeroxLite")
            except FileNotFoundError: pass
        winreg.CloseKey(key)
    except Exception as e: raise OSError(str(e)) from e


TITLE_COLOR, BORDER_COLOR = 0x00303030, 0x00585858  # COLORREF 0x00BBGGRR — gray


def style_titlebar(win):
    """Gray window border/title bar. Win11 — exact color; Win10 — dark title bar."""
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        dwm = ctypes.windll.dwmapi

        def set_attr(attr, val):
            v = ctypes.c_int(val)
            return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        if set_attr(20, 1) != 0: set_attr(19, 1)  # dark mode (older Win10 builds use attribute 19)
        set_attr(35, TITLE_COLOR); set_attr(34, BORDER_COLOR); set_attr(36, 0x00FFFFFF)
    except Exception:
        pass


def gg_running():
    import subprocess  # only for this one check, in a background thread
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True, errors="ignore", creationflags=0x08000000, timeout=3).stdout.lower()
        return "steelseriesgg" in out or "steelseriesengine" in out
    except Exception: return False


_font_cache = {}
def tray_font(size):
    if size not in _font_cache:
        for name in ("seguisb.ttf", "arialbd.ttf", "arial.ttf"):
            try: _font_cache[size] = ImageFont.truetype(name, size); break
            except Exception: pass
        else: _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]


def tray_image(level, charging):
    low = level is not None and level <= 20 and not charging
    bg, fg = ((255, 255, 255, 255), (0, 0, 0, 255)) if low else ((0, 0, 0, 255), (255, 255, 255, 255))
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    d.rounded_rectangle((1, 1, 62, 62), radius=12, fill=bg, outline=fg, width=3)
    txt = "--" if level is None else str(level)
    f = tray_font(36 if len(txt) < 3 else 26)
    x0, y0, x1, y1 = d.textbbox((0, 0), txt, font=f)
    d.text(((64 - (x1 - x0)) / 2 - x0, (60 - (y1 - y0)) / 2 - y0 - (3 if charging else 0)), txt, font=f, fill=fg)
    if charging: d.rectangle((16, 51, 48, 55), fill=fg)
    return img


# ---------------------------------------------------------------- UI
ART_Y = 40
import ui_theme
from ui_theme import Pill, Switch, ColorDot

AUTOSTART_LABEL = 'Start with Windows'


def set_palette(name):
    """Switch the colour theme (dark / light); the module-level colour names follow it."""
    globals().update(ui_theme.set_theme(name))


set_palette("dark")
FONT_SPECS = {  # name: (family, size in points at 100%, weight, underline)
    "AxF": ("Segoe UI", 9, "normal", 0), "AxFB": ("Segoe UI Semibold", 9, "normal", 0),
    "AxFS": ("Segoe UI", 8, "normal", 0), "AxFT": ("Segoe UI Semibold", 11, "normal", 0),
    "AxFU": ("Segoe UI", 8, "normal", 1), "AxFH": ("Segoe UI Semibold", 13, "normal", 0),
    "AxFM": ("Consolas", 8, "normal", 0), "AxFM2": ("Consolas", 10, "normal", 0),
}
UI_SCALES = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6, 1.8, 2.0)
F, FB, FS, FT, FU, FH, FM, FM2 = "AxF", "AxFB", "AxFS", "AxFT", "AxFU", "AxFH", "AxFM", "AxFM2"


_FONTS = {}  # keep references: Tk deletes a named font when its Python object is garbage collected


def init_fonts(root, scale):
    """Create or resize the named fonts; every widget that uses them updates immediately."""
    from tkinter import font as tkfont
    for name, (family, size, weight, underline) in FONT_SPECS.items():
        kw = dict(family=family, size=max(6, round(size * scale)), weight=weight, underline=underline)
        if name in _FONTS: _FONTS[name].configure(**kw)
        else: _FONTS[name] = tkfont.Font(root=root, name=name, exists=False, **kw)


def display_factors(root):
    """(font factor, pixel factor). Tk already scales point-sized fonts with the Windows DPI setting;
    pixel sizes (mouse picture, window size, text wrapping) must follow it too."""
    try: s0 = float(root.tk.call("tk", "scaling"))
    except Exception: return 1.0, 1.0
    return 1.0, max(1.0, s0 / (96 / 72))



def flatbtn(parent, text, cmd, sel=False, **kw):
    """Rounded button (ui_theme.Pill). width, as in Tk, is in characters."""
    font = kw.pop("font", FB)
    width = kw.pop("width", None)
    padx, pady = kw.pop("padx", 12), kw.pop("pady", 6)
    return Pill(parent, text, cmd, sel=sel, kind=kw.pop("kind", "normal"), font=font, padx=padx, pady=pady,
                chars=width, radius=kw.pop("radius", 8))


def panel(parent, title=None):
    """A rounded card with an optional small uppercase title."""
    f = ui_theme.card(parent, radius=12)
    if title: tk.Label(f, text=title, bg=PANEL, fg=DIM, font=FS).pack(anchor="w", padx=14, pady=(12, 6))
    return f


def slider(parent, frm, to, res, cmd):
    return ui_theme.sized(tk.Scale(parent, from_=frm, to=to, resolution=res, orient="horizontal", showvalue=0,
                    bg=ACC, fg=FG, troughcolor=LINE, activebackground=ACC, highlightthickness=0,
                    bd=0, sliderrelief="flat",
                    command=cmd),
                          sliderlength=(16, 10), width=(8, 6))


# what the window for other mice (generic_ui) uses from here
GV_LIB = SimpleNamespace(KEYS=KEYS, MEDIA=MEDIA, KEY_GROUPS=KEY_GROUPS, action_name=action_name,
                         flatbtn=flatbtn, slider=slider)


def stack_raise(panes, key):
    """Tab panes lie on top of each other in one place; switching only raises one (no relayout,
    unlike unpacking one pane and packing another)."""
    p = panes[key]
    if not p.winfo_manager(): p.place(x=0, y=0, relwidth=1, relheight=1)  # shown for the first time
    p.tkraise()


class App:
    def __init__(self, hidden):
        self.cfg = load_cfg()
        self.cfg["verbose_log"] = False  # the sensor log is for this session only: never on at start
        self.aerox = self.mouse = Mouse()
        self.gen, self.gv = generic.GenericMouse(hid, KNOWN_PIDS), None
        self._plugged = False
        set_palette(self.cfg["theme"])
        self.stop_event = threading.Event()
        self.threads = []
        self.ui_q, self.jobs = queue.Queue(), queue.Queue()
        # Threads sleep on these instead of polling; _kick() wakes them when something relevant changes.
        self._fx_wake, self._smart_wake, self._mon_wake = threading.Event(), threading.Event(), threading.Event()
        self._wake_pending, self._visible, self._preview_after = False, not hidden, None
        self._active, self._focus_after = not hidden, None  # one of our windows has the focus (animation plays only then)
        self._fade = None  # colour fade on the mouse picture: (from, start time, to)
        self.logger = logging.getLogger("AeroxLite")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        try:
            os.makedirs(CFG_DIR, exist_ok=True)
            handler = _CappedLog(self.LOG_FILE, 512 * 1024)
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            self.logger.addHandler(handler)
        except OSError: pass
        self.batt, self.preview, self.running, self.tray = (None, None), None, True, None
        self.sel_dpi = min(self.cfg["dpi_active"], len(self.cfg["dpi"]) - 1)
        self._pending, self._after, self._loading, self._low_notified = set(), None, False, False
        self.last_move, self.moving, self.editor = 0.0, False, None
        self.log_text, self.raw = None, None
        self.art_masks = self.art_lines = self.art_tk = None
        self.macros = winput.MacroRunner(self._macro_by_slot) if winput else None

        if self.macros: self.macros.on_error = lambda e: self.log(str(e), True)
        self.saver, self.sb, self.rc = False, None, None  # battery saver, modules
        if winput:
            try:
                self.raw = winput.RawInput(self._on_move, self._macro_key, on_error=lambda e: self.log("Raw input unavailable: {0}".format(e), True))
                self.raw.on_hotplug = self._on_hotplug  # SteelSeries device plugged in/out: check now
            except Exception as e: self.log('Raw input unavailable: {0}'.format(e))
        self._init_modules()
        self.root = tk.Tk()
        if hidden: self.root.withdraw()  # before anything is drawn
        self.root.title(APP); self.root.configure(bg=BG)
        self._ui_built, self._log_buf, self._warn_text = False, deque(maxlen=400), ""
        self.ui_scale = self.cfg["ui_scale"]
        self.font_k, self.px_k = display_factors(self.root)
        init_fonts(self.root, self.ui_scale * self.font_k)
        self.root.option_add("*Menu.font", F)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        # Started in the tray (autostart), the window may never be opened: build it on first show.
        if not hidden: self._ensure_ui()
        if self.px_k != 1:
            self.log('Display scale: {0:g}x (fonts x{1:.2f})'.format(self.px_k, self.font_k))
        self.log('Aerox Lite started')

        for target in (self._worker, self._monitor, self._effects, self._smart):
            thread = threading.Thread(target=target, daemon=True)
            self.threads.append(thread); thread.start()
        if self.raw:
            try: self.raw.start()
            except Exception as e: self.log('Raw input unavailable: {0}'.format(e)); self.raw = None
        self._update_input()
        self._make_tray()
        self.root.bind("<<AxWake>>", self._poll_ui)
        self.root.bind("<Map>", lambda e: e.widget is self.root and self._set_visible(True), add="+")
        self.root.bind("<Unmap>", lambda e: e.widget is self.root and self._set_visible(False), add="+")
        # Tk on Windows sends no <Activate>/<Deactivate> to the main window: after any focus change, ask
        # whether one of our windows still has the keyboard focus (none: another program is in front)
        for ev in ("<FocusIn>", "<FocusOut>"):
            self.root.bind(ev, lambda e: self._focus_check_soon(), add="+")
        self.root.after(100, self._poll_ui)
        self.root.after(60, self._preview_kick)
        def check_gg():
            if gg_running():
                self.post(lambda: self._set_warn('⚠ SteelSeries GG is running — close it to prevent settings conflicts'))
                self.log('Warning: SteelSeries GG is running')
        threading.Thread(target=check_gg, daemon=True).start()

    def persist(self):
        try:
            save_cfg(self.cfg)
            return True
        except OSError as e:
            self.log('Could not save config: {0}'.format(e), True)
            self.save_lbl.config(text='Could not save config')
            return False

    def enqueue(self, cats, save=False):
        snapshot = copy.deepcopy(self.cfg)
        snapshot["_saver"] = getattr(self, "saver", False)  # temporary battery saver, never written to config
        self.jobs.put((set(cats), save, snapshot))

    # ---------- UI construction
    def _build(self):
        ui_theme.set_scale(self.ui_scale * self.px_k)
        self.root.configure(bg=BG)
        # ---- Header: theme switch, logo, connection, battery, interface size, quit
        top = tk.Frame(self.root, bg=BG); top.pack(fill="x", padx=18, pady=(12, 10))
        self.theme_btn = tk.Label(top, image=ui_theme.theme_switch_image(ui_theme.THEME == "light"), bg=BG, bd=0,
                                  cursor="hand2")
        self.theme_btn.bind("<Button-1>", lambda e: self._toggle_theme()); self.theme_btn.pack(side="left", padx=(0, 14))
        self._logo_img = ImageTk.PhotoImage(ui_theme.logo_image(ui_theme.px(32)))
        self._logo_lbl = tk.Label(top, image=self._logo_img, bg=BG, bd=0); self._logo_lbl.pack(side="left")
        names = tk.Frame(top, bg=BG); names.pack(side="left", padx=(10, 0))
        tk.Label(names, text="Aerox Lite", bg=BG, fg=FG, font=FT).pack(anchor="w")
        self.model_lbl = tk.Label(names, text=self._model_name(), bg=BG, fg=DIM, font=FS)
        self.model_lbl.pack(anchor="w")
        Pill(top, icon="power", command=self.quit, kind="ghost", radius=10).pack(side="right")
        zoom = ui_theme.card(top, radius=10); zoom.pack(side="right", padx=(0, 10))
        Pill(zoom, 'A+', lambda: self._zoom(1), kind="quiet", font=FS, padx=8, pady=4, radius=8).pack(side="right", padx=3, pady=3)
        self.zoom_lbl = tk.Label(zoom, text="{0}%".format(round(self.ui_scale * 100)), bg=PANEL, fg=DIM, font=FS, width=5)
        self.zoom_lbl.pack(side="right")
        Pill(zoom, 'A\u2212', lambda: self._zoom(-1), kind="quiet", font=FS, padx=8, pady=4, radius=8).pack(side="right", padx=3, pady=3)
        batt = ui_theme.card(top, radius=10); batt.pack(side="right", padx=(0, 10))
        self.batt_icon = tk.Label(batt, bg=PANEL, bd=0); self.batt_icon.pack(side="left", padx=(12, 6), pady=8)
        self.batt_lbl = tk.Label(batt, text="\u2014", bg=PANEL, fg=FG, font=FB); self.batt_lbl.pack(side="left")
        self.batt_sub = tk.Label(batt, text="", bg=PANEL, fg=DIM, font=FS); self.batt_sub.pack(side="left", padx=(6, 12))
        conn = ui_theme.card(top, radius=10); conn.pack(side="right", padx=(0, 10))
        self.conn_dot = tk.Label(conn, bg=PANEL, bd=0); self.conn_dot.pack(side="left", padx=(12, 6), pady=8)
        self.conn_lbl = tk.Label(conn, text='searching\u2026', bg=PANEL, fg=DIM, font=FS); self.conn_lbl.pack(side="left", padx=(0, 12))
        self.status = self.conn_lbl
        self.warn = tk.Label(self.root, text="", bg=BG, fg=FG, font=FS); self.warn.pack(fill="x", padx=18)

        body = tk.Frame(self.root, bg=BG); body.pack(fill="both", expand=True, padx=18)
        body.columnconfigure(1, weight=1); body.rowconfigure(0, weight=1)

        # ---- Buttons (left)
        left = panel(body); left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        self.binds_box = box = tk.Frame(left, bg=PANEL); box.pack(fill="x")  # Aerox 3 only
        self.bind_btns, self.gv = [], None
        if self.mouse.generic:  # another SteelSeries mouse: its own buttons (generic_ui.py)
            import generic_ui  # with the pictures of all models: only loaded for such a mouse
            self.gv = generic_ui.GenericView(self, GV_LIB)
            self.gv.build_buttons(box)
        else:
            tk.Label(box, text='BUTTONS', bg=PANEL, fg=DIM, font=FS).pack(anchor="w", padx=14, pady=(12, 6))
            for i, (name, tag, _, _) in enumerate(SLOTS):
                row = tk.Frame(box, bg=PANEL); row.pack(fill="x", padx=14, pady=2)
                tk.Label(row, text=tag, bg=PANEL, fg=DIM, font=FS, width=3, anchor="w").pack(side="left")
                tk.Label(row, text=name, bg=PANEL, fg=DIM, font=F, width=12, anchor="w").pack(side="left")
                mb = tk.Menubutton(row, text="", bg=BTN, fg=FG, activebackground=HOV, activeforeground=FG, relief="flat",
                                   font=FB, anchor="w", width=15, padx=10, pady=4, cursor="hand2", bd=0, highlightthickness=0)
                mb["menu"] = self._bind_menu(mb, i); mb.pack(side="right")
                self.bind_btns.append(mb)
            br = tk.Frame(box, bg=PANEL); br.pack(fill="x", padx=14, pady=(10, 2))
            flatbtn(br, 'Reset', self._reset_binds, kind="ghost").pack(side="left", padx=(0, 6))
            flatbtn(br, 'Macros\u2026', self.open_editor, kind="ghost").pack(side="left")
        self.mode_lbl = tk.Label(left, text="", bg=PANEL, fg=DIM, font=FS, justify="left", wraplength=270)
        self.mode_lbl.pack(anchor="w", padx=14, pady=(12, 0))
        lh = tk.Frame(left, bg=PANEL); lh.pack(fill="x", padx=14, pady=(10, 2))
        tk.Label(lh, text='ACTIVITY', bg=PANEL, fg=DIM, font=FS).pack(side="left")
        self.log_toggle = tk.Label(lh, text='Show log', bg=PANEL, fg=DIM, font=FU, cursor="hand2")
        self.log_toggle.bind("<Button-1>", lambda e: self._toggle_log()); self.log_toggle.pack(side="right")
        self.act_lbls = []
        for _ in range(2):
            l = tk.Label(left, text="", bg=PANEL, fg=DIM, font=FS, anchor="w", justify="left")
            l.pack(fill="x", padx=14); self.act_lbls.append(l)
        self.log_frame = tk.Frame(left, bg=PANEL)  # the full log, shown on demand
        lc = tk.Frame(self.log_frame, bg=PANEL); lc.pack(fill="x")
        clr = tk.Label(lc, text='clear', bg=PANEL, fg=DIM, font=FU, cursor="hand2")
        clr.bind("<Button-1>", lambda e: self._clear_log()); clr.pack(side="right")
        self.verb_lbl = tk.Label(lc, bg=PANEL, fg=DIM, font=FU, cursor="hand2")
        self.verb_lbl.bind("<Button-1>", lambda e: self._toggle_verbose()); self.verb_lbl.pack(side="right", padx=(0, 10))
        lw = tk.Frame(self.log_frame, bg=LINE, padx=1, pady=1); lw.pack(fill="both", expand=True, pady=(4, 0))
        self.log_text = tk.Text(lw, bg=LOG_BG, fg=FG, font=FM, relief="flat", wrap="word", height=7, width=36,
                                padx=6, pady=4, state="disabled", cursor="arrow", highlightthickness=0,
                                selectbackground=HOV, inactiveselectbackground=HOV)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_config("t", foreground=LOG_DIM)
        self.log_text.tag_config("w", foreground=FG)
        self._render_verbose()
        self._left_pad = ui_theme.sized(tk.Frame(left, bg=PANEL), height=12)
        self._left_pad.pack(side="bottom", fill="x")
        if getattr(self, "_log_open", False): self.log_frame.pack(fill="both", expand=True, padx=14, pady=(6, 0))
        # the animation in the free space under ACTIVITY (placed, so it never makes the window bigger)
        self.mascot, self._mascot_room, self._mascot_fit_after = ui_theme.Mascot(left), False, None
        for w in [left] + [c for c in left.winfo_children() if c not in left._ax_corners.values()]:
            w.bind("<Configure>", lambda e: self._mascot_fit_soon(), add="+")

        # ---- Center: tabs + mouse picture; right: tab panes
        if self.gv:  # another SteelSeries mouse: the same layout, built from its own settings
            self.center = center = self.gv.build_center(body); center.grid(row=0, column=1, sticky="n", padx=(10, 20))
            self.right = self.gv.build_right(body); self.right.grid(row=0, column=2, sticky="ns")
            self.tgl = {}
        else:
            self.center = center = tk.Frame(body, bg=BG); center.grid(row=0, column=1, sticky="n", padx=(10, 20))
            tabs = ui_theme.card(center, radius=12); tabs.pack(pady=(0, 10))
            self.tab_btns = {}
            for key, txt in (("settings", 'Settings'), ("light", 'Lighting'), ("modules", 'Modules')):
                b = Pill(tabs, txt, lambda k=key: self._tab(k), kind="quiet", font=FT, padx=18, pady=7, radius=9)
                b.pack(side="left", padx=3, pady=3)
                self.tab_btns[key] = b
            self.canvas = tk.Canvas(center, width=320, height=ART_Y + mouse_art.SIZE[1] + 10, bg=BG, highlightthickness=0); self.canvas.pack()
            self._draw_mouse()

            # ---- Right side
            self.right = tk.Frame(body, bg=BG, width=420); self.right.grid(row=0, column=2, sticky="ns")
            self.p_settings = tk.Frame(self.right, bg=BG); self.p_light = tk.Frame(self.right, bg=BG)
            self.p_modules = tk.Frame(self.right, bg=BG)
            self._build_settings(self.p_settings); self._build_light(self.p_light); self._build_modules(self.p_modules)

        # ---- Bottom
        bot = tk.Frame(self.root, bg=BG); bot.pack(fill="x", side="bottom", padx=18, pady=(10, 14))
        self.v_auto = tk.BooleanVar(value=self.cfg["autostart"]); self.v_apply = tk.BooleanVar(value=self.cfg["apply_on_connect"])
        for var, txt, cmd in ((self.v_auto, AUTOSTART_LABEL, self._toggle_autostart),
                              (self.v_apply, 'Apply settings on connect', self._toggle_apply)):
            tk.Checkbutton(bot, text=txt, variable=var, command=cmd, bg=BG, fg=DIM, selectcolor=PANEL,
                           activebackground=BG, activeforeground=FG, font=F, bd=0, highlightthickness=0).pack(side="left", padx=(0, 18))
        self.save_btn = Pill(bot, 'Save to mouse', self.save_all, kind="primary", font=FB, padx=24, pady=10, radius=11)
        self.save_btn.pack(side="right")
        self.save_lbl = tk.Label(bot, text="", bg=BG, fg=DIM, font=F); self.save_lbl.pack(side="right", padx=12)

        self._load_into_ui(); self._tab("settings")
        self._built_scale = self.ui_scale

    # ---------- other SteelSeries mice (generic.py, rivalcfg device descriptions)
    def _model_name(self):
        return self.mouse.product if self.mouse.generic else "Aerox 3 Wireless"

    # ---------- the animation at the bottom of the left panel (ui_theme.Mascot)
    def _mascot_fit_soon(self):
        if self._mascot_fit_after is None: self._mascot_fit_after = self.root.after_idle(self._mascot_fit)

    def _mascot_fit(self):
        """Shown only when it fits under the panel content (not with the log open or a long button list)."""
        self._mascot_fit_after = None
        m = getattr(self, "mascot", None)
        if m is None or not m.winfo_exists() or not self._visible: return  # sizes are not real while hidden
        left = m.master
        bottom = max([c.winfo_y() + c.winfo_height() for c in left.pack_slaves() if c is not self._left_pad] or [0])
        h = ui_theme.px(ui_theme.Mascot.HEIGHT)
        room = left.winfo_height() - self._left_pad.winfo_height() - bottom >= h + ui_theme.px(12)
        if room != self._mascot_room:
            self._mascot_room = room
            if room: m.place(relx=0.5, rely=1.0, y=-self._left_pad.winfo_height(), anchor="s")
            else: m.place_forget(); m.stop(free=True)
        self._mascot_update()

    def _mascot_update(self):
        """Plays only while someone can see it: window shown and active, and there is room for it."""
        m = getattr(self, "mascot", None)
        if m is None or not m.winfo_exists(): return
        if not self._visible: m.stop(free=True)
        elif self._mascot_room: m.run(self._active and ui_theme.ANIMATE)

    def _gen_values(self):
        return self.cfg["devices"].setdefault(self.mouse.key, {})

    def _device_changed(self):
        """Another kind of mouse was connected: rebuild the window for it (Aerox 3 or any other model)."""
        if self._ui_built:
            self._rebuild_ui(); self._fit_window()

    def _gen_set(self, name, value):
        self._gen_values()[name] = value
        self.changed("g:" + name)

    def _gen_run(self, name):
        self.enqueue({"run:" + name})

    def _open_any(self):
        """The Aerox 3 first (its own protocol), then any other mouse rivalcfg describes."""
        try: scan = list(hid.enumerate(VID, 0))   # one USB scan for both kinds of mice
        except Exception: scan = []
        for m in (self.aerox, self.gen):
            try: ok = m.open(scan)
            except Exception as e:  # HID errors, or rivalcfg missing from a self-made build
                ok = False; m.diag = "HID: {0}".format(e)
            if ok:
                if m is not self.mouse:
                    self.mouse = m; self.post(self._device_changed)
                return True
        self.mouse.diag = self.gen.diag or self.aerox.diag
        return False

    def _apply_generic(self, m, cats, save, c):
        stored = c["devices"].get(m.key, {})
        full = {"dpi", "poll", "power", "buttons", "light"} <= set(cats)  # connect / save: everything stored
        names = list(stored) if full else [k[2:] for k in cats if k.startswith("g:")]
        labels = {s["name"]: s["label"] for s in m.specs}
        try:
            for k in cats:
                if k.startswith("run:"):
                    m.run(k[4:]); self.log('Done: {0}'.format(labels.get(k[4:], k[4:])))
            for name, err in m.apply(stored, names):
                self.log('{0}: not accepted ({1})'.format(labels.get(name, name), err), True)
            if save:
                m.save()
                self.post(lambda: self.save_lbl.config(text='Saved to mouse'))
            done = ", ".join(labels[n] for n in names if n in labels and n in stored)
            if done: self.log(('Saved to mouse: ' if save else 'Applied: ') + done)
            elif save: self.log('Saved to mouse')
        except Exception as e:
            self.log('Mouse connection error ({0}) — reconnecting'.format(e), True)
            self.post("conn")
            if save: self.post(lambda: self.save_lbl.config(text='Could not save to mouse'))

    def _toggle_log(self):
        self._log_open = not getattr(self, "_log_open", False)
        if self._log_open:
            self.log_frame.pack(fill="both", expand=True, padx=14, pady=(6, 0)); self.log_toggle.config(text='Hide log')
        else:
            self.log_frame.pack_forget(); self.log_toggle.config(text='Show log')
        self._fit_window(); self._mascot_fit_soon()

    def _toggle_theme(self, step=0):
        """The knob slides to the other side (about 80 ms), then the window is recoloured."""
        if step == 0:
            if getattr(self, "_theming", False): return   # a click while the knob is still moving
            self._theming = True
        if self._ui_built and ui_theme.ANIMATE and step < 5:
            to_light = ui_theme.THEME == "dark"
            t = (step + 1) / 6; t = t * t * (3 - 2 * t)
            self.theme_btn.config(image=ui_theme.theme_switch_image(not to_light, t if to_light else 1 - t))
            self.root.after(16, lambda: self._toggle_theme(step + 1)); return
        self._theming = False
        self.cfg["theme"] = "light" if ui_theme.THEME == "dark" else "dark"
        self.persist()
        old = dict(ui_theme.PAL)
        set_palette(self.cfg["theme"])
        if self._ui_built:
            try: self._retheme(old)
            except Exception as e:  # never leave a half-coloured window: build it again instead
                self.log('Theme: recolouring failed ({0}), rebuilding'.format(e), True); self._rebuild_ui()
        self.log('Theme: {0}'.format(self.cfg["theme"]))

    def _retheme(self, old):
        """Recolour the window in place (~10x faster than building it again)."""
        ui_theme.restyle(self.root, old)
        self.theme_btn.config(image=ui_theme.theme_switch_image(ui_theme.THEME == "light"))
        self._header_images()
        if self.log_text is not None:
            self.log_text.tag_config("t", foreground=LOG_DIM); self.log_text.tag_config("w", foreground=FG)
        if self.gv: self.gv.retheme()
        else: self._art_scale = None; self._draw_mouse()
        self.mascot.refresh()
        self._update_status()

    def _rebuild_ui(self):
        """Recreate the window contents (theme or size change); state lives in cfg, so nothing is lost."""
        if not self._ui_built: return
        tab = getattr(self, "current_tab", "settings")
        for w in list(self.root.winfo_children()):
            if not isinstance(w, tk.Toplevel): w.destroy()
        self.log_text = None
        self.art_masks = self.art_lines = self.art_tk = None; self._art_scale = None; self.art_cols = None
        self._build(); self._tab(tab)
        self._scale_wraps(self.root); self._size_right()
        if self._warn_text: self.warn.config(text=self._warn_text)
        for line in list(self._log_buf): self._append_log(line, keep=False)
        self._update_status()

    def _bind_menu(self, mb, i):
        m = tk.Menu(mb, tearoff=0, bg=PANEL, fg=FG, activebackground=ACC, activeforeground=ON_ACC, font=F)
        for n, v in SPECIAL_NAMES: m.add_command(label=n, command=lambda v=v: self._set_bind(i, v))
        m.add_separator()
        groups = KEY_GROUPS
        kb = tk.Menu(m, tearoff=0, bg=PANEL, fg=FG, activebackground=ACC, activeforeground=ON_ACC, font=F)
        for gname, keys in groups:
            sub = tk.Menu(kb, tearoff=0, bg=PANEL, fg=FG, activebackground=ACC, activeforeground=ON_ACC, font=F)
            for k in keys: sub.add_command(label=k, command=lambda k=k: self._set_bind(i, "key:" + k))
            kb.add_cascade(label=gname, menu=sub)
        m.add_cascade(label='Keyboard', menu=kb)
        mm = tk.Menu(m, tearoff=0, bg=PANEL, fg=FG, activebackground=ACC, activeforeground=ON_ACC, font=F)
        for k, (n, _) in MEDIA.items(): mm.add_command(label=n, command=lambda k=k: self._set_bind(i, "media:" + k))
        m.add_cascade(label='Media', menu=mm)
        mc = tk.Menu(m, tearoff=0, bg=PANEL, fg=FG, activebackground=ACC, activeforeground=ON_ACC, font=F)
        for mac in sorted(self.cfg["macros"], key=lambda x: x["slot"]):
            mc.add_command(label=mac["name"], command=lambda sl=mac["slot"]: self._set_bind(i, f"macro:{sl}"))
        if not self.cfg["macros"]: mc.add_command(label='(no macros — open editor)', state="disabled")
        m.add_cascade(label='Macros', menu=mc)
        return m

    def _rebuild_bind_menus(self):
        if self.gv and self._ui_built:
            self.gv.rebuild_menus(); self._update_input(); return
        for i, mb in enumerate(self.bind_btns if self._ui_built else ()):
            old = mb["menu"]
            mb["menu"] = self._bind_menu(mb, i)
            try: self.root.nametowidget(old).destroy()  # the old menu tree would otherwise leak
            except (KeyError, tk.TclError): pass
            mb.config(text=action_name(self.cfg["binds"][i], self.cfg["macros"]))
        self._update_input()

    def _build_settings(self, p):
        # CPI
        dp = panel(p, 'SENSITIVITY LEVELS (CPI)'); dp.pack(fill="x")
        self.dpi_tabs = tk.Frame(dp, bg=PANEL); self.dpi_tabs.pack(fill="x", padx=14)
        r = tk.Frame(dp, bg=PANEL); r.pack(fill="x", padx=14, pady=(8, 0))
        self.dpi_slider = slider(r, 100, 18000, 100, self._on_dpi_slider); self.dpi_slider.pack(side="left", fill="x", expand=True)
        self.dpi_var = tk.StringVar()
        e = tk.Entry(r, textvariable=self.dpi_var, width=7, bg=BTN, fg=FG, insertbackground=FG, relief="flat", font=FB, justify="center")
        e.pack(side="left", padx=(10, 0), ipady=3); e.bind("<Return>", self._on_dpi_entry); e.bind("<FocusOut>", self._on_dpi_entry)
        r2 = tk.Frame(dp, bg=PANEL); r2.pack(fill="x", padx=14, pady=(2, 4))
        tk.Label(r2, text="100", bg=PANEL, fg=DIM, font=FS).pack(side="left")
        tk.Label(r2, text="18000", bg=PANEL, fg=DIM, font=FS).pack(side="right", padx=(0, 70))
        self.rm_dpi = tk.Label(dp, text='Remove level', bg=PANEL, fg=FG, font=FU, cursor="hand2")
        self.rm_dpi.bind("<Button-1>", lambda e: self._rm_dpi()); self.rm_dpi.pack(anchor="w", padx=14, pady=(0, 10))

        # Power saving
        ep = panel(p, 'POWER SAVING'); ep.pack(fill="x", pady=8)
        self.sleep_lbl, self.sleep_s = self._labeled_slider(ep, 'Sleep timer', 0, 20, 1, self._on_sleep)
        self.dim_lbl, self.dim_s = self._labeled_slider(ep, 'Lighting dim timer', 0, 1200, 30, self._on_dim)
        self.tgl = {}
        self._toggle_row(ep, "eco", 'High efficiency mode',
                         'Lighting off, sleep after 1 min for longer battery life.')
        self._toggle_row(ep, "smart_light", 'Smart lighting mode',
                         'Lighting turns off while moving and returns when the mouse stops.')

        # Polling rate
        pp = panel(p, 'POLLING RATE'); pp.pack(fill="x")
        self.poll_row = tk.Frame(pp, bg=PANEL); self.poll_row.pack(fill="x", padx=14, pady=(0, 10))

    def _toggle_row(self, parent, key, title, desc):
        row = tk.Frame(parent, bg=PANEL); row.pack(fill="x", padx=14, pady=(4, 0))
        b = Switch(row, lambda: self._flip(key)); b.pack(side="right")
        tk.Label(row, text=title, bg=PANEL, fg=FG, font=FB).pack(side="left")
        tk.Label(parent, text=desc, bg=PANEL, fg=DIM, font=FS, wraplength=300, justify="left").pack(anchor="w", padx=14, pady=(0, 10))
        self.tgl[key] = b

    def _render_toggles(self):
        if not self._ui_built or self.gv: return
        for key, b in self.tgl.items():
            b.set(self.cfg[key])

    def _flip(self, key):
        self.cfg[key] = not self.cfg[key]; self._render_toggles()
        self.log({"eco": 'High efficiency mode', "smart_light": 'Smart lighting mode'}[key]
                 + (': on' if self.cfg[key] else ': off'))
        if self.tray:
            try: self.tray.update_menu()
            except Exception: pass
        if key == "eco": self.changed("power")
        self.changed("light")
        self._update_input()

    def _labeled_slider(self, parent, title, frm, to, res, cmd):
        h = tk.Frame(parent, bg=PANEL); h.pack(fill="x", padx=14)
        tk.Label(h, text=title, bg=PANEL, fg=FG, font=F).pack(side="left")
        val = tk.Label(h, text="", bg=PANEL, fg=FG, font=FB); val.pack(side="right")
        s = slider(parent, frm, to, res, cmd); s.pack(fill="x", padx=14, pady=(2, 10))
        return val, s

    def _build_light(self, p):
        mp = panel(p, 'LIGHTING MODE'); mp.pack(fill="x")
        self.mode_grid = tk.Frame(mp, bg=PANEL); self.mode_grid.pack(fill="x", padx=14, pady=(0, 10))

        zp = panel(p, 'ZONES'); zp.pack(fill="x", pady=8)
        self.swatches = []
        for z, name in enumerate(('Zone 1 — front', 'Zone 2 — middle', 'Zone 3 — rear')):
            row = tk.Frame(zp, bg=PANEL); row.pack(fill="x", padx=14, pady=3)
            tk.Label(row, text=name, bg=PANEL, fg=FG, font=F, width=18, anchor="w").pack(side="left")
            sw = ColorDot(row, "#ffffff", 26, lambda z=z: self._pick_zone(z)); sw.pack(side="left")
            self.swatches.append(sw)
        flatbtn(zp, 'One color for all zones', self._pick_all, kind="ghost").pack(fill="x", padx=14, pady=(6, 10))

        op = panel(p, 'OPTIONS'); op.pack(fill="x")
        self.br_lbl, self.br_s = self._labeled_slider(op, 'Brightness', 0, 100, 1, self._on_bright)
        self.sp_lbl, self.sp_s = self._labeled_slider(op, 'Effect speed', 1, 100, 1, self._on_speed)
        rr = tk.Frame(op, bg=PANEL); rr.pack(fill="x", padx=14, pady=(0, 10))
        self.v_react = tk.BooleanVar()
        tk.Checkbutton(rr, text='Flash on click (reactive)', variable=self.v_react, command=self._on_react,
                       bg=PANEL, fg=FG, selectcolor=PANEL, activebackground=PANEL, activeforeground=FG, font=F,
                       bd=0, highlightthickness=0).pack(side="left")
        self.react_sw = ColorDot(rr, "#ffffff", 22, self._pick_react); self.react_sw.pack(side="right")
        tk.Label(p, text='* Software effect: requires the app running (in the tray).\nStatic color and hardware rainbow work without the app after saving.',
                 bg=BG, fg=DIM, font=FS, justify="left").pack(anchor="w", pady=8)

    def _ensure_ui(self):
        """Build the window the first time it is needed (about half a second saved at autostart)."""
        if self._ui_built: return
        self._ui_built = True
        try:
            self._icons = [ImageTk.PhotoImage(ui_theme.logo_image(n, "#18181B", "#FFFFFF")) for n in (64, 32, 16)]
            self.root.iconphoto(True, *self._icons)
        except Exception:
            pass
        self._build()
        self._fit_startup()
        style_titlebar(self.root)
        if self._warn_text: self.warn.config(text=self._warn_text)
        for line in list(self._log_buf): self._append_log(line, keep=False)
        self._update_status()

    def _set_warn(self, text):
        self._warn_text = text
        if self._ui_built: self.warn.config(text=text)

    # ---------- UI scale
    def _px(self, n):
        return round(n * self.ui_scale * self.px_k)

    def _screen_room(self):
        return self.root.winfo_screenwidth(), self.root.winfo_screenheight() - 80  # task bar / title bar

    def _scale_wraps(self, widget):
        """Text wrapping widths are in pixels: keep them proportional to the interface size."""
        for w in widget.winfo_children():
            if isinstance(w, tk.Label) and int(w.cget("wraplength") or 0) > 0:
                if not hasattr(w, "_ax_wrap"): w._ax_wrap = int(w.cget("wraplength"))
                w.config(wraplength=self._px(w._ax_wrap))
            self._scale_wraps(w)

    def _size_right(self):
        """The right column keeps the size of its largest tab, so switching tabs never shifts the layout."""
        if self.gv: return self.gv.size_right()
        self.root.update_idletasks()
        panes = (self.p_settings, self.p_light, self.p_modules)
        self.right.config(width=max(p.winfo_reqwidth() for p in panes),
                          height=max(p.winfo_reqheight() for p in panes))
        self.right.pack_propagate(False)

    def _header_images(self):
        self.theme_btn.config(image=ui_theme.theme_switch_image(ui_theme.THEME == "light"))
        self._logo_img = ImageTk.PhotoImage(ui_theme.logo_image(ui_theme.px(32))); self._logo_lbl.config(image=self._logo_img)

    def _rescale_ui(self, sc):
        """Redraw everything drawn for one interface size (fonts resize by themselves)."""
        ui_theme.rescale(self.root)
        self._header_images()
        self._scale_wraps(self.root)
        if self.gv: self.gv.rescale()
        else: self._art_scale = None; self._draw_mouse()
        self.mascot.refresh(); self._mascot_fit_soon()
        self._size_right(); self._update_status()
        self._built_scale = sc

    def _set_scale(self, sc):
        """Apply a size; True if the window content fits on the screen."""
        self.ui_scale = sc
        init_fonts(self.root, sc * self.font_k)
        ui_theme.set_scale(sc * self.px_k)
        if self._ui_built and getattr(self, "_built_scale", None) != sc:
            try: self._rescale_ui(sc)  # in place: ~5x faster than building the window again
            except Exception as e:
                self.log('Size: redrawing failed ({0}), rebuilding'.format(e), True); self._rebuild_ui()
        else:
            self._scale_wraps(self.root)
            if getattr(self, "_art_scale", None) != sc * self.px_k: self._draw_mouse()
            self._size_right()
        sw, sh = self._screen_room()
        return self.root.winfo_reqwidth() <= sw and self.root.winfo_reqheight() <= sh

    def _fit_window(self, center=False):
        """Never smaller than the content (otherwise Tk squeezes columns over each other)."""
        self.root.update_idletasks()
        sw, sh = self._screen_room()
        rw, rh = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        w, h = min(max(self._px(1180), rw), sw), min(max(self._px(690), rh), sh)
        self.root.minsize(min(rw, sw), min(rh, sh))
        if center:
            x, y = max(0, (sw - w) // 2), max(0, (sh - h) // 2)
        else:
            x = min(max(0, self.root.winfo_x()), max(0, sw - w))
            y = min(max(0, self.root.winfo_y()), max(0, sh - h))
        self.root.geometry("{0}x{1}+{2}+{3}".format(w, h, x, y))

    def _fit_startup(self):
        """Use the saved size, or the largest smaller one that fits this screen (not saved)."""
        i = min(range(len(UI_SCALES)), key=lambda k: abs(UI_SCALES[k] - self.ui_scale))
        while not self._set_scale(UI_SCALES[i]) and i > 0: i -= 1
        self.zoom_lbl.config(text="{0}%".format(round(self.ui_scale * 100)))
        self._fit_window(center=True)

    def _zoom(self, step):
        cur = min(range(len(UI_SCALES)), key=lambda i: abs(UI_SCALES[i] - self.ui_scale))
        new = UI_SCALES[max(0, min(len(UI_SCALES) - 1, cur + step))]
        if new == self.ui_scale: return
        old = self.ui_scale
        if not self._set_scale(new) and step > 0:  # the next size would not fit on this screen
            self._set_scale(old)
            self.log("Interface size: {0}% is the maximum for this screen".format(round(old * 100)))
            return
        self.cfg["ui_scale"] = new
        self.persist()
        self.zoom_lbl.config(text="{0}%".format(round(new * 100)))
        self._fit_window()
        self.log("Interface size: {0}%".format(round(new * 100)))

    def _draw_mouse(self):
        if not self._ui_built: return
        if self.gv: return self.gv.draw_art()
        """Mouse diagram (mouse_art.py): outline + shell holes tinted with the zone colors."""
        c, sc = self.canvas, getattr(self, "ui_scale", 1.0) * getattr(self, "px_k", 1.0)
        self._art_scale = sc
        prev = getattr(self, "art_cols", None)
        c.delete("all")
        lines = Image.open(io.BytesIO(base64.b64decode(mouse_art.LINES))).convert("L")
        cells = Image.open(io.BytesIO(base64.b64decode(mouse_art.CELLS))).convert("L")
        if sc != 1:
            size = (round(cells.size[0] * sc), round(cells.size[1] * sc))
            lines, cells = lines.resize(size, Image.LANCZOS), cells.resize(size, Image.LANCZOS)
        W, H = cells.size
        self.art_size, self.art_lines, self.art_masks = (W, H), lines, []
        for z in range(3):  # zones top to bottom: front / middle / rear
            band = Image.new("L", (W, H), 0)
            ImageDraw.Draw(band).rectangle((0, z * H // 3, W, (z + 1) * H // 3), fill=255)
            m = ImageChops.multiply(cells, band)
            self.art_masks.append((m, m.filter(ImageFilter.GaussianBlur(5 * sc))))
        cw = round(320 * sc)
        c.config(width=cw, height=round((ART_Y + mouse_art.SIZE[1] + 10) * sc))
        ox, oy = (cw - W) // 2, round(ART_Y * sc)
        self.art_cols, self.art_tk = None, None
        self.art_id = c.create_image(ox, oy, anchor="nw")
        A = {k: (round(x * sc) + ox, round(y * sc) + oy) for k, (x, y) in mouse_art.ANCHORS.items()}
        lx0, lx1, r, bw, bh = round(22 * sc), cw - round(22 * sc), max(2, round(3 * sc)), round(15 * sc), round(10 * sc)
        labels = {"B3": (A["B3"][0], round(16 * sc)), "B1": (lx0, A["B1"][1]), "B2": (lx1, A["B2"][1]),
                  "B6": (lx1, A["B6"][1]), "B5": (lx0, A["B5"][1]), "B4": (lx0, A["B4"][1])}
        self._tag_img = ui_theme.rounded(2 * bw, 2 * bh, max(3, round(6 * sc)), BTN, BG, TAGLINE)
        for tag, (lx, ly) in labels.items():
            tx, ty = A[tag]
            c.create_line(lx, ly, tx, ty, fill=TAGLINE)
            c.create_oval(tx - r, ty - r, tx + r, ty + r, fill=FG, outline=BG)
            c.create_image(lx, ly, image=self._tag_img)
            c.create_text(lx, ly, text=tag, fill=FG, font=FS)
        self._render_art(prev or [(0, 0, 0)] * 3)

    def _render_art(self, cols):
        if not self.art_masks: return  # freed while hidden
        cols = [tuple(int(v) for v in col) for col in cols]
        if cols == self.art_cols: return
        self.art_cols, (W, H) = cols, self.art_size
        frame = Image.new("RGB", (W, H), ui_theme.rgb(BG))
        dark = ui_theme.THEME == "dark"
        for (m, glow), col in zip(self.art_masks, cols):
            if max(col) <= 12:
                frame.paste(ui_theme.rgb(CELL_OFF), (0, 0, W, H), m)
            else:
                frame.paste(scale(col, 0.45) if dark else col, (0, 0, W, H), glow)
                frame.paste(col, (0, 0, W, H), m)
        frame.paste(ui_theme.rgb(ART_LINE), (0, 0, W, H), self.art_lines)
        img = frame
        if self.art_tk is not None and (self.art_tk.width(), self.art_tk.height()) == (W, H):
            self.art_tk.paste(img)  # reuse the Tk image: no new photo per frame
        else:
            self.art_tk = ImageTk.PhotoImage(img)
            self.canvas.itemconfig(self.art_id, image=self.art_tk)

    # ---------- populate UI from config
    def _load_into_ui(self):
        if self.gv: return self.gv.load()
        self._loading = True
        for i, mb in enumerate(self.bind_btns): mb.config(text=action_name(self.cfg["binds"][i], self.cfg["macros"]))
        self._render_dpi(); self._render_poll(); self._render_modes(); self._render_toggles()
        self.sleep_s.set(self.cfg["sleep"]); self.dim_s.set(self.cfg["dim"])
        self._fmt_sleep(); self._fmt_dim()
        L = self.cfg["light"]
        for z, sw in enumerate(self.swatches): sw.config(bg=L["colors"][z])
        self.br_s.set(L["brightness"]); self.sp_s.set(L["speed"])
        self.br_lbl.config(text=f"{L['brightness']}%"); self.sp_lbl.config(text=str(L["speed"]))
        self.v_react.set(L["reactive"]); self.react_sw.config(bg=L["reactive_color"])
        self._loading = False

    def _tab(self, key):
        self.current_tab = key
        if self.gv: return self.gv.tab(key)
        for k, b in self.tab_btns.items():
            b.set(sel=(k == key))
        stack_raise({"settings": self.p_settings, "light": self.p_light, "modules": self.p_modules}, key)

    def _render_dpi(self):
        if not self._ui_built: return
        for w in self.dpi_tabs.winfo_children(): w.destroy()
        for i, v in enumerate(self.cfg["dpi"]):
            flatbtn(self.dpi_tabs, 'LV. {0}\n{1} CPI'.format(i + 1, v), lambda i=i: self._sel_dpi(i), sel=(i == self.sel_dpi),
                    padx=6, pady=4, width=8, font=FS).pack(side="left", padx=(0, 4))
        if len(self.cfg["dpi"]) < 5:
            flatbtn(self.dpi_tabs, "+", self._add_dpi, font=FT, padx=10, pady=6).pack(side="left")
        v = self.cfg["dpi"][self.sel_dpi]
        self._loading, old = True, self._loading
        self.dpi_slider.set(v); self.dpi_var.set(str(v))
        self._loading = old
        if len(self.cfg["dpi"]) > 1: self.rm_dpi.pack(anchor="w", padx=10, pady=(0, 10))
        else: self.rm_dpi.pack_forget()

    def _render_poll(self):
        if not self._ui_built: return
        for w in self.poll_row.winfo_children(): w.destroy()
        for hz in (125, 250, 500, 1000):
            flatbtn(self.poll_row, '{0} Hz'.format(hz), lambda hz=hz: self._set_poll(hz), sel=(hz == self.cfg["poll"]),
                    padx=12).pack(side="left", padx=(0, 4), expand=True, fill="x")

    def _render_modes(self):
        if not self._ui_built: return
        for w in self.mode_grid.winfo_children(): w.destroy()
        for n, (k, txt) in enumerate(MODES):
            flatbtn(self.mode_grid, txt, lambda k=k: self._set_mode(k), sel=(k == self.cfg["light"]["mode"])).grid(
                row=n // 3, column=n % 3, sticky="ew", padx=2, pady=2)
        for col in range(3): self.mode_grid.columnconfigure(col, weight=1)

    # ---------- handlers
    def _set_bind(self, i, v):
        self.cfg["binds"][i] = v; self.bind_btns[i].config(text=action_name(v, self.cfg["macros"])); self.changed("buttons")

    def _reset_binds(self):
        self.cfg["binds"] = [s[3] for s in SLOTS]; self._load_into_ui(); self.changed("buttons")

    def _sel_dpi(self, i):
        self.sel_dpi = self.cfg["dpi_active"] = i; self._render_dpi(); self.changed("dpi")

    def _add_dpi(self):
        if len(self.cfg["dpi"]) >= 5: return
        self.cfg["dpi"].append(min(18000, self.cfg["dpi"][-1] + 400)); self._sel_dpi(len(self.cfg["dpi"]) - 1)

    def _rm_dpi(self):
        if len(self.cfg["dpi"]) <= 1: return
        self.cfg["dpi"].pop(self.sel_dpi); self._sel_dpi(max(0, self.sel_dpi - 1))

    def _on_dpi_slider(self, v):
        if self._loading: return
        v = int(float(v)); self.cfg["dpi"][self.sel_dpi] = v; self.dpi_var.set(str(v))
        b = self.dpi_tabs.winfo_children()[self.sel_dpi]; b.config(text='LV. {0}\n{1} CPI'.format(self.sel_dpi + 1, v))
        self.changed("dpi")

    def _on_dpi_entry(self, _=None):
        try: v = max(100, min(18000, round(int(self.dpi_var.get()) / 100) * 100))
        except ValueError: v = self.cfg["dpi"][self.sel_dpi]
        self.cfg["dpi"][self.sel_dpi] = v; self._render_dpi(); self.changed("dpi")

    def _set_poll(self, hz): self.cfg["poll"] = hz; self._render_poll(); self.changed("poll"); self.log('Polling rate: {0} Hz'.format(hz))

    def _fmt_sleep(self):
        v = self.cfg["sleep"]; self.sleep_lbl.config(text='Off' if v == 0 else '{0} min'.format(v))

    def _fmt_dim(self):
        v = self.cfg["dim"]
        self.dim_lbl.config(text='Off' if v == 0 else ('{0} s'.format(v) if v < 60 else '{0:g} min'.format(v / 60)))

    def _on_sleep(self, v):
        if self._loading: return
        self.cfg["sleep"] = int(float(v)); self._fmt_sleep(); self.changed("power")

    def _on_dim(self, v):
        if self._loading: return
        self.cfg["dim"] = int(float(v)); self._fmt_dim(); self.changed("power")

    def _set_mode(self, k):
        self.cfg["light"]["mode"] = k; self._render_modes(); self.changed("light")
        self.log('Lighting mode: ' + dict(MODES)[k].rstrip(" *"))

    def _pick_zone(self, z):
        c = colorchooser.askcolor(self.cfg["light"]["colors"][z], parent=self.root, title='Zone {0}'.format(z + 1))[1]
        if c: self.cfg["light"]["colors"][z] = c; self.swatches[z].config(bg=c); self.changed("light")

    def _pick_all(self):
        c = colorchooser.askcolor(self.cfg["light"]["colors"][0], parent=self.root, title='All zones')[1]
        if c:
            self.cfg["light"]["colors"] = [c] * 3
            for sw in self.swatches: sw.config(bg=c)
            self.changed("light")

    def _on_bright(self, v):
        if self._loading: return
        self.cfg["light"]["brightness"] = int(float(v)); self.br_lbl.config(text=f"{int(float(v))}%"); self.changed("light")

    def _on_speed(self, v):
        if self._loading: return
        self.cfg["light"]["speed"] = int(float(v)); self.sp_lbl.config(text=str(int(float(v)))); self.changed("light")

    def _on_react(self): self.cfg["light"]["reactive"] = self.v_react.get(); self.changed("light")

    def _pick_react(self):
        c = colorchooser.askcolor(self.cfg["light"]["reactive_color"], parent=self.root)[1]
        if c: self.cfg["light"]["reactive_color"] = c; self.react_sw.config(bg=c); self.changed("light")

    def _toggle_autostart(self):
        on = self.v_auto.get()
        try: set_autostart(on)
        except OSError as e:
            self.v_auto.set(self.cfg["autostart"])
            self.log("Could not configure autostart: {0}".format(e), True)
            return
        self.cfg["autostart"] = on; self.persist()

    def _toggle_apply(self): self.cfg["apply_on_connect"] = self.v_apply.get(); self.persist()

    # ---------- apply (live, debounced) and save
    def changed(self, cat):
        self._kick(); self._preview_kick()
        self._pending.add(cat)
        if self._after: self.root.after_cancel(self._after)
        self._after = self.root.after(250, self._flush)

    def _flush(self):
        cats, self._pending, self._after = set(self._pending), set(), None
        self.persist()
        self.enqueue(cats)
        if "dpi" in cats and self.tray:
            try: self.tray.update_menu()
            except Exception: pass

    def save_all(self):
        if not self.persist(): return
        self.enqueue({"dpi", "poll", "power", "buttons", "light"}, True)
        self.save_lbl.config(text='Saving…' if self.mouse.connected() else 'Mouse disconnected — saved to config')

    def _apply(self, cats, save, c):
        with self.mouse.lock:
            if save and c.get("_saver"):
                # write the real settings to mouse memory, then re-apply the temporary saver
                self._apply_locked(cats, True, dict(c, _saver=False))
                return self._apply_locked({"poll", "light"}, False, c)
            return self._apply_locked(cats, save, c)

    def _apply_locked(self, cats, save, c):
        m = self.mouse
        if not m.connected():
            if save: self.post(lambda: self.save_lbl.config(text='Mouse disconnected — saved to config'))
            return
        if m.generic: return self._apply_generic(m, cats, save, c)
        try:
            if "dpi" in cats: m.set_dpi(c["dpi"], min(c["dpi_active"], len(c["dpi"]) - 1))
            if "poll" in cats: m.set_poll(min(c["poll"], 500) if c.get("_saver") else c["poll"])
            if "power" in cats:
                m.set_sleep(1 if c["eco"] and c["sleep"] != 1 else c["sleep"]); m.set_dim(c["dim"])
            if "buttons" in cats: m.set_buttons(c["binds"])
            if "light" in cats:
                L = c["light"]; k = L["brightness"] / 100; dark = c["eco"] or c.get("_saver", False)
                m.set_reactive(scale(hex2rgb(L["reactive_color"]), k) if L["reactive"] and not dark else None)
                if dark:
                    for z in range(3): m.set_zone(z, (0, 0, 0))
                    m.set_default_light(False, False)
                elif L["mode"] == "rainbow_hw":
                    m.set_rainbow(); m.set_default_light(True, L["reactive"])
                else:
                    cols = [(0, 0, 0)] * 3 if L["mode"] == "off" else [scale(hex2rgb(x), k) for x in L["colors"]]
                    for z, col in enumerate(cols): m.set_zone(z, col)
                    m.set_default_light(False, L["reactive"])
            if save:
                m.save()
                self.post(lambda: self.save_lbl.config(text='Saved to mouse'))
            names = {"dpi": "CPI", "poll": 'polling rate', "power": 'timers', "buttons": 'bindings', "light": 'lighting'}
            done = ", ".join(names[k] for k in ("dpi", "poll", "power", "buttons", "light") if k in cats)
            if done: self.log(('Saved to mouse: ' if save else 'Applied: ') + done)
            if save:
                for line in self._describe(c): self.log(line)
        except IOError as e:
            self.log('Mouse connection error ({0}) — reconnecting'.format(e), True)
            self.post("conn")
            if save: self.post(lambda: self.save_lbl.config(text='Could not save to mouse'))

    # ---------- background threads
    def _worker(self):
        while self.running:
            job = self.jobs.get()
            if job is None: break  # quit
            self._apply(*job)

    def _on_hotplug(self):
        self._plugged = True; self._mon_wake.set()

    def _present(self):
        """Is the connected mouse still on the USB bus? (unplugging a wired mouse gives no read error
        until the next battery check, up to half a minute later)"""
        try: return any(d.get("product_id") == self.mouse.pid for d in hid.enumerate(VID, self.mouse.pid))
        except Exception: return True

    def _monitor(self):
        last, was_conn, waiting_logged, last_diag, conn_posted = 0, False, False, "", None
        while self.running:
            if self._plugged:  # a SteelSeries device came or went: is ours still there?
                self._plugged = False
                if self.mouse.connected() and not self._present(): self.mouse.close()
            if was_conn and not self.mouse.connected():
                self.log('Mouse disconnected', True); was_conn = False
            if not self.mouse.connected():
                opened = self._open_any()
                if opened:
                    m = self.mouse
                    self.log('Connected: {0} (PID 0x{1:04X}), '.format(m.product, m.pid)
                             + ('2.4 GHz dongle' if m.wireless else 'USB cable'))
                    last, was_conn, waiting_logged, conn_posted = 0, True, False, True; self.post("conn"); self._fx_wake.set()
                    if self.cfg["apply_on_connect"]: self.post(lambda: self.enqueue({"dpi", "poll", "power", "buttons", "light"}))
                else:
                    if not waiting_logged: self.log('Mouse not found — waiting for connection…'); waiting_logged = True
                    if self.mouse.diag != last_diag:
                        last_diag = self.mouse.diag
                        if last_diag: self.log(last_diag, True)
                    if self.batt != (None, None): self.batt = (None, None); self.post("batt")
                    if conn_posted is not False: conn_posted = False; self.post("conn"); self._fx_wake.set()
                    # With device notifications (Linux inotify, Windows) the listener wakes us on plug-in;
                    # the timeout is only a safety net. Otherwise check every few seconds.
                    hot = bool(self.raw and getattr(self.raw, "hotplug", False) and self.raw.is_alive())
                    self._mon_wake.wait(30 if hot else (2 if self._visible else 4)); self._mon_wake.clear(); continue
            interval = 30 if self.batt[0] is not None else 20  # asleep: movement wakes us earlier (_on_move)
            if time.monotonic() - last >= interval:
                prev = self.batt
                self.batt = self.mouse.battery(); last = time.monotonic()
                sb = self.sb
                if sb:  # forecast first, then UI update — otherwise the UI sees stale data
                    try: sb.update(*self.batt)
                    except Exception as e: self.log('Smart battery: error {0}'.format(e), True)
                self.post("batt")
                if self.batt != prev:
                    lvl, ch = self.batt
                    if lvl is not None or self.mouse.has_battery:
                        self.log('Mouse asleep or powered off' if lvl is None else 'Battery: {0}%'.format(lvl) + (' (charging)' if ch else ""))
                if prev[0] is None and self.batt[0] is not None and self.cfg["apply_on_connect"]:
                    self.log('Mouse awake — restoring lighting')
                    self.post(lambda: self.enqueue({"light"}))  # mouse woke up / powered on
                if self.batt != prev: self._fx_wake.set()
            interval = 30 if self.batt[0] is not None else 20
            self._mon_wake.wait(max(0.5, last + interval - time.monotonic())); self._mon_wake.clear()

    def _effects(self):
        t0, last = time.monotonic(), None
        while self.running:
            L = dict(self.cfg["light"])
            device = self._aerox_on() and self.batt[0] is not None
            if L["mode"] in SOFT and not self._dark() and (device or (self._visible and not self.mouse.generic)):
                cols = [(0, 0, 0)] * 3 if self.moving else effect_frame(L, time.monotonic() - t0)
                self.preview = cols
                if self._aerox_on() and self.batt[0] is not None and cols != last:
                    try:
                        with self.mouse.lock:
                            if self._dark() or self.cfg["light"]["mode"] != L["mode"]: continue
                            # Avoid redundant USB/HID writes for zones whose colors did not change.
                            for z, col in enumerate(cols):
                                if last is None or last[z] != col:
                                    self.mouse.set_zone(z, col, fast=True)
                        last = cols
                    except IOError: last = None
                self.stop_event.wait(1 / max(5, min(30, self.cfg.get("fps", 15))))
            else:  # nothing to animate: sleep until a setting, the connection or visibility changes
                self.preview, last = None, None
                self._fx_wake.wait(); self._fx_wake.clear()

    def _on_move(self):
        """Hot path (up to 1000 Hz): keep it to a timestamp and two cheap checks."""
        self.last_move = time.monotonic()
        if not self.moving and self.cfg["smart_light"]: self._smart_wake.set()
        if self.batt[0] is None and self.mouse.dev is not None: self._mon_wake.set()  # asleep -> check battery now

    def _smart(self):
        """Smart lighting: turn zones off while the mouse moves, restore after a pause.
        Also, once per second, a mouse data summary for the log."""
        next_tick = 0.0
        while self.running:
            self._smart_wake.clear()
            stats = self.cfg["verbose_log"] and self._visible  # the sensor log is only useful on screen
            if stats and time.monotonic() >= next_tick:
                next_tick = time.monotonic() + 1.0
                try:
                    self._sensor_tick()
                    if self.cfg["verbose_log"] and self.mouse.connected():
                        for rep in self.mouse.drain():
                            if rep and (rep[0] & ~WIRELESS_FLAG) in ECHO_CMDS: continue  # late replies to our own commands
                            self.log("HID ← " + " ".join(f"{b:02X}" for b in rep.rstrip(b"\x00")[:16] or b"\x00"))
                except Exception:
                    pass
            L = self.cfg["light"]
            active = self.cfg["smart_light"] and not self._dark() and L["mode"] != "off"
            mv = active and time.monotonic() - self.last_move < self.cfg.get("smart_delay", 0.6)
            if mv != self.moving:
                self.moving = mv
                if L["mode"] not in SOFT and self._aerox_on():
                    if mv:
                        try:
                            with self.mouse.lock:
                                if L["mode"] == "rainbow_hw": self.mouse.set_default_light(False, False)
                                for z in range(3): self.mouse.set_zone(z, (0, 0, 0), fast=True)
                        except IOError: pass
                    else:
                        self.post(lambda: self.enqueue({"light"}))
                self.post(self._preview_kick)
            # Preserve 50 ms responsiveness only while smart lighting is active.
            # Otherwise there is no reason to wake this worker 20 times per second.
            waits = []
            if stats: waits.append(max(0.05, next_tick - time.monotonic()))
            if mv: waits.append(max(0.02, self.last_move + self.cfg.get("smart_delay", 0.6) - time.monotonic()))
            self._smart_wake.wait(min(waits) if waits else None)

    # ---------- modules (directional sensitivity, multi-click, smart battery)
    def _aerox_on(self):
        return self.mouse.connected() and not self.mouse.generic

    def _dark(self):
        return self.cfg["eco"] or getattr(self, "saver", False)

    def _init_modules(self):
        """Only enabled modules are imported."""
        if helpers.module_on("battery"): self._load_battery()
        if helpers.module_on("rclick"):
            import rclick
            self.rc = rclick.RightClickMultiplier(self.log, listener=self.raw)
            if not self.rc.enable(): self.rc = None
        if helpers.module_on("directional"):
            import calibration  # after a reboot the Raw Accel driver loads its own settings — re-apply ours
            threading.Thread(target=calibration.reapply, args=(self.log,), daemon=True).start()

    def _load_battery(self):
        import smartbattery
        self.sb = smartbattery.SmartBattery(self._on_battery_low, self.log, self._notify)
        self.saver = self.sb.enabled and self.sb.low_active

    def _on_battery_low(self, active):  # may be called from the _monitor thread
        self.post(lambda: self._set_saver(active))

    def _set_saver(self, active):
        if active == self.saver: return
        self.saver = active
        self._kick(); self._preview_kick()
        self.enqueue({"poll", "light"})
        self._update_status()

    def _notify(self, text):
        def show():
            try: self.tray.notify(text, APP)
            except Exception: pass
        self.post(show)

    def _mod_is_on(self, name):
        if name == "rclick": return bool(self.rc and self.rc.active)
        if name == "battery": return bool(self.sb and self.sb.enabled)
        return helpers.module_on("directional")

    def _helpers_any(self):
        return any(self._mod_is_on(n) for n in helpers.TRAY_MODULES)

    def _mod_set(self, name, on):
        if name == "battery":
            if on:
                if not self.sb: self._load_battery()
                self.sb.set_enabled(True)
                if self.batt[0] is not None: self.sb.update(*self.batt)
            elif self.sb:
                self.sb.set_enabled(False); self.sb = None  # unload: update() is no longer called
        elif name == "rclick":
            if on:
                if not self.rc:
                    import rclick
                    self.rc = rclick.RightClickMultiplier(self.log, listener=self.raw)
                if not self.rc.enable(): self.rc = None
            else:
                if not self.rc:
                    import rclick
                    self.rc = rclick.RightClickMultiplier(self.log, listener=self.raw)
                self.rc.disable(); self.rc = None
        else:
            import calibration
            def work():
                calibration.set_enabled(on, self.log)
                self.post(self._render_modules)
                if self.tray:
                    try: self.tray.update_menu()
                    except Exception: pass
            threading.Thread(target=work, daemon=True).start()
        self._update_input()
        self._render_modules()
        if self.tray:
            try: self.tray.update_menu()
            except Exception: pass

    def _mod_flip(self, name):
        self._mod_set(name, not self._mod_is_on(name))

    def _helpers_toggle(self):
        on = [n for n in helpers.TRAY_MODULES if self._mod_is_on(n)]
        try:
            if on:
                helpers.remember(on)
                for n in on: self._mod_set(n, False)
                self.log('Multi-click & directional sens: OFF')
            else:
                names = helpers.recall() or list(helpers.TRAY_MODULES)  # nothing to restore — enable both
                for n in names: self._mod_set(n, True)
                helpers.remember(None)
                self.log('Multi-click & directional sens: ON')
        except OSError as e:
            self.log('Could not save config: {0}'.format(e), True)

    def _build_modules(self, p):
        self.mtgl, self.minfo = {}, {}
        dp = panel(p, 'DIRECTIONAL SENSITIVITY (RAW ACCEL)'); dp.pack(fill="x")
        self._mod_row(dp, "directional", 'Directional sensitivity',
                      'Calibrated multipliers via the Raw Accel driver. Off — your own Raw Accel settings.')
        self.minfo["dir_prof"] = tk.Label(dp, bg=PANEL, fg=FG, font=FB, anchor="w")
        self.minfo["dir_prof"].pack(fill="x", padx=14)
        self.minfo["dir_ra"] = tk.Label(dp, bg=PANEL, fg=DIM, font=FS, anchor="w", justify="left", wraplength=380)
        self.minfo["dir_ra"].pack(fill="x", padx=14, pady=(2, 0))
        br = tk.Frame(dp, bg=PANEL); br.pack(fill="x", padx=14, pady=(8, 10))
        flatbtn(br, 'CALIBRATE', self._calibrate).pack(side="left", expand=True, fill="x", padx=(0, 4))
        flatbtn(br, 'RAW ACCEL FOLDER', self._pick_rawaccel).pack(side="left", expand=True, fill="x")

        rp = panel(p, 'MULTI-CLICK'); rp.pack(fill="x", pady=8)
        self._mod_row(rp, "rclick", 'Left / right multi-click',
                      'A press shorter than the tap threshold = several clicks; longer = normal hold.')
        self.rcw, self._rc_loading, self._rc_after = {}, False, None
        for button, name in (("left", 'Left click'), ("right", 'Right click')):
            row = tk.Frame(rp, bg=PANEL); row.pack(fill="x", padx=14, pady=(4, 0))
            b = Switch(row, lambda bt=button: self._rc_btn_flip(bt), small=True); b.pack(side="left")
            tk.Label(row, text=name, bg=PANEL, fg=FG, font=F).pack(side="left", padx=(8, 0))
            val = tk.Label(row, bg=PANEL, fg=FG, font=FB); val.pack(side="right")
            sl = slider(rp, 2, 6, 1, lambda v, bt=button: self._on_rc_count(bt, v)); sl.pack(fill="x", padx=14, pady=(2, 0))
            self.rcw[button] = (b, val, sl)
        tr_row = tk.Frame(rp, bg=PANEL); tr_row.pack(fill="x", padx=14, pady=(8, 0))
        tk.Label(tr_row, text='Tap threshold', bg=PANEL, fg=FG, font=F).pack(side="left")
        tap_val = tk.Label(tr_row, bg=PANEL, fg=FG, font=FB); tap_val.pack(side="right")
        tap_sl = slider(rp, 60, 400, 10, self._on_rc_tap); tap_sl.pack(fill="x", padx=14, pady=(2, 10))
        self.rcw["tap"] = (None, tap_val, tap_sl)

        bp = panel(p, 'SMART BATTERY'); bp.pack(fill="x")
        self._mod_row(bp, "battery", 'Smart battery',
                      'Below 25% — notification, 500 Hz and lighting off. Charging or ≥30% restores everything.')
        self.minfo["bat"] = tk.Label(bp, bg=PANEL, fg=FG, font=FB, anchor="w")
        self.minfo["bat"].pack(fill="x", padx=14, pady=(0, 10))
        self._render_modules()

    def _mod_row(self, parent, name, title, desc):
        row = tk.Frame(parent, bg=PANEL); row.pack(fill="x", padx=14, pady=(4, 0))
        b = Switch(row, lambda: self._mod_flip(name)); b.pack(side="right")
        tk.Label(row, text=title, bg=PANEL, fg=FG, font=FB).pack(side="left")
        tk.Label(parent, text=desc, bg=PANEL, fg=DIM, font=FS, wraplength=300, justify="left").pack(anchor="w", padx=14, pady=(0, 8))
        self.mtgl[name] = b

    def _render_modules(self):
        try:
            if not self.mtgl["battery"].winfo_exists(): return
        except (AttributeError, KeyError, tk.TclError):
            return
        for name, b in self.mtgl.items():
            on = self._mod_is_on(name)
            b.set(on)
        prof = helpers.read_json("directional.json").get("sectors")
        if isinstance(prof, list) and len(prof) == 8:
            m = {s.get("angle"): s.get("mult", 1.0) for s in prof if isinstance(s, dict)}
            txt = "→ {0:.3f}   ↑ {1:.3f}   ← {2:.3f}   ↓ {3:.3f}".format(m.get(0, 1), m.get(90, 1), m.get(180, 1), m.get(270, 1))
        else: txt = 'Not calibrated yet'
        self.minfo["dir_prof"].config(text=txt)
        ra = helpers.read_json("directional_state.json").get("rawaccel_dir")
        self.minfo["dir_ra"].config(text="Raw Accel: " + (ra if isinstance(ra, str) and ra else 'folder not set'))
        import rclick
        rc = rclick.load_cfg() if not self.rc else self.rc.cfg
        self._rc_loading = True
        for button in ("left", "right"):
            b, val, sl = self.rcw[button]
            on = rc[f"{button}_on"]
            b.set(on)
            val.config(text=f"×{rc[button]}", fg=FG if on else DIM)
            sl.set(rc[button])
        _, tap_val, tap_sl = self.rcw["tap"]
        tap_val.config(text='{0} ms'.format(rc["tap_ms"])); tap_sl.set(rc["tap_ms"])
        self._rc_loading = False
        if self.sb and self.sb.enabled:
            fc = self.sb.forecast_text() or 'collecting data'
            txt = ('Saver active · {0}' if self.saver else 'Forecast: {0}').format(fc)
        else: txt = 'Forecast: {0}'.format("—")
        self.minfo["bat"].config(text=txt)

    def _rc_obj(self):
        """The running multi-click instance, or a settings-only "editor" when the module is off (no hook installed)."""
        if self.rc: return self.rc
        import rclick
        if not getattr(self, "_rc_edit", None): self._rc_edit = rclick.RightClickMultiplier(self.log, listener=self.raw)
        self._rc_edit.cfg = rclick.load_cfg()
        return self._rc_edit

    def _rc_changed(self):
        """Log once after the slider is released (debounced)."""
        if self._rc_after: self.root.after_cancel(self._rc_after)
        def done():
            import rclick
            self._rc_after = None
            c = self._rc_obj().cfg
            self.log('Multi-click: {0}, tap threshold {1} ms'.format(rclick.counts_text(c), c["tap_ms"]))
        self._rc_after = self.root.after(600, done)

    def _rc_btn_flip(self, button):
        rc = self._rc_obj()
        rc.set_button(button, not rc.cfg[f"{button}_on"])
        self._render_modules(); self._rc_changed()

    def _on_rc_count(self, button, v):
        if self._rc_loading: return
        n = int(float(v))
        rc = self._rc_obj()
        if rc.cfg[button] == n: return
        rc.set_count(button, n)
        self.rcw[button][1].config(text=f"×{n}"); self._rc_changed()

    def _on_rc_tap(self, v):
        if self._rc_loading: return
        ms = int(float(v))
        rc = self._rc_obj()
        if rc.cfg["tap_ms"] == ms: return
        rc.set_tap(ms)
        self.rcw["tap"][1].config(text='{0} ms'.format(ms)); self._rc_changed()

    def _calibrate(self):
        import calibration
        calibration.open_calibration(self.root, on_done=self._calibrated, log=self.log)

    def _calibrated(self, profile):
        self._render_modules()
        if helpers.module_on("directional"):  # already enabled — apply the new calibration
            self._mod_set("directional", True)

    def _pick_rawaccel(self):
        """Search for Raw Accel automatically (Downloads, Desktop, Program Files…); if not found, ask for the folder."""
        import calibration
        self.log('Raw Accel: searching for the folder…')
        def work():
            found = calibration.find_rawaccel()
            self.post(lambda: self._rawaccel_found(found))
        threading.Thread(target=work, daemon=True).start()

    def _rawaccel_found(self, found):
        import calibration
        if found:
            calibration.set_rawaccel_dir(found, self.log)
        else:
            self.log('Raw Accel: not found automatically — choose the folder manually')
            path = filedialog.askdirectory(parent=self.root, title='Raw Accel folder (with writer.exe)')
            if path: calibration.set_rawaccel_dir(os.path.normpath(path), self.log)
        self._render_modules()

    # ---------- macros
    def _macro_by_slot(self, slot):
        for m in self.cfg["macros"]:
            if m["slot"] == slot: return dict(m)
        return None

    def open_editor(self):
        if not winput:
            self.save_lbl.config(text='Macros require Windows'); return
        if self.editor and self.editor.win.winfo_exists():
            self.editor.win.lift(); self.editor.win.focus_force(); return
        self.editor = MacroEditor(self)

    # ---------- log
    LOG_FILE = os.path.join(CFG_DIR, "log.txt")

    def log(self, text, warn=False):
        """Thread-safe: the line goes to the log window and to %APPDATA%\\AeroxLite\\log.txt."""
        line = (time.strftime("%H:%M:%S"), text, warn)
        self.ui_q.put(("log", line)); self._wake()
        self.logger.info(text)

    def _append_log(self, line, keep=True):
        if keep: self._log_buf.append(line)  # replayed into the window when it is first built
        if not self.log_text: return
        t, text, warn = line
        lt = self.log_text
        lt.config(state="normal")
        lt.insert("end", t + "  ", "t"); lt.insert("end", text + "\n", "w" if warn else ())
        if int(lt.index("end-1c").split(".")[0]) > 400: lt.delete("1.0", "100.0")
        lt.config(state="disabled"); lt.see("end")
        recent = list(self._log_buf)[-2:][::-1]
        for lbl, item in zip(self.act_lbls, recent + [None] * (2 - len(recent))):
            msg = "" if item is None else item[1] if len(item[1]) <= 42 else item[1][:41] + "\u2026"
            lbl.config(text="" if item is None else "{0} \u00b7 {1}".format(item[0][:5], msg))

    def _render_verbose(self):
        if not self._ui_built: return
        self.verb_lbl.config(text='mouse data: ' + ('on' if self.cfg["verbose_log"] else 'off'))

    def _toggle_verbose(self):
        self.cfg["verbose_log"] = not self.cfg["verbose_log"]; self.persist(); self._render_verbose()
        self._update_input(); self._kick()
        if self.raw: self.raw.take_motion()
        self.log('Mouse data logging: ' + ('on' if self.cfg["verbose_log"] else 'off'))

    def _describe(self, c=None):
        c = c if c is not None else self.cfg
        L = c["light"]
        dpi = ", ".join(f"[{v}]" if i == c["dpi_active"] else str(v) for i, v in enumerate(c["dpi"]))
        binds = "; ".join(f"{s[1] or s[0]}={action_name(c['binds'][i], c['macros'])}"
                          for i, s in enumerate(SLOTS) if c["binds"][i] != s[3])
        mode = dict(MODES)[L["mode"]].rstrip(" *")
        light = 'off (eco mode)' if c["eco"] else (
            '{0}, zones {1}, brightness {2}%'.format(mode, ' '.join(L['colors']), L['brightness'])
            + (f", reactive {L['reactive_color']}" if L["reactive"] else ""))
        return [f"  CPI: {dpi}", '  Polling: {0} Hz'.format(c['poll']),
                '  Sleep: {0}, dim: {1}'.format('off' if not c['sleep'] else str(c['sleep']) + ' min', 'off' if not c['dim'] else str(c['dim']) + ' s'),
                '  Bindings: {0}'.format(binds or 'default'), '  Lighting: {0}'.format(light)]

    def _sensor_tick(self):
        """Once per second: sensor summary + buttons. Called from a background thread."""
        r = self.raw
        if not r or not r.stats_on: return
        while r.events:
            kind, a, b = r.events.popleft()
            if kind == "btn": self.log('Button: {0}'.format(a) + (' ({0} ms)'.format(b) if b is not None else ""))
            else: self.log('Mouse key: {0}'.format(winput.VK_NAMES.get(a, hex(a)).upper()))
        n, dx, dy, w, dt, pos = r.take_motion()
        if w: self.log('Scroll: ' + ('up ×{0}'.format(w) if w > 0 else 'down ×{0}'.format(-w)))
        if n:
            dpi = self.cfg["dpi"][min(self.cfg["dpi_active"], len(self.cfg["dpi"]) - 1)]
            hz = '{0} Hz'.format(round(n / dt)) if dt > 0.2 else "—"
            cms = math.hypot(dx, dy) / dpi * 2.54 / max(dt, 0.001)
            self.log('Sensor: Δ({0:+}, {1:+})  pos({2}, {3})  {4}  ~{5:.0f} cm/s'.format(dx, dy, pos[0], pos[1], hz, cms))

    def _clear_log(self):
        self.log_text.config(state="normal"); self.log_text.delete("1.0", "end"); self.log_text.config(state="disabled")

    def _macro_key(self, vk, down):
        if down and winput.VK_F13 <= vk <= winput.VK_F13 + 11 and vk - winput.VK_F13 not in self.macros.held:
            m = self._macro_by_slot(vk - winput.VK_F13)
            if m: self.log('Macro “{0}” ({1})'.format(m['name'], m['mode']))
        self.macros.on_key(vk, down)

    # ---------- thread-to-UI bridge
    def post(self, msg):
        self.ui_q.put(msg); self._wake()

    def _wake(self):
        """Wake the Tk loop from any thread (sub-millisecond) instead of polling the queue."""
        if self._wake_pending: return
        self._wake_pending = True
        try: self.root.event_generate("<<AxWake>>", when="tail")
        except Exception: self._wake_pending = False  # window not created yet, or already closed

    def _kick(self):
        """Something changed: let the sleeping worker threads re-evaluate."""
        self._fx_wake.set(); self._smart_wake.set(); self._mon_wake.set()

    def _set_visible(self, visible):
        if visible == self._visible: return
        self._visible = visible
        self._kick(); self._update_input()
        if self._ui_built:
            if visible:
                if self.gv: self.gv.draw_art()
                elif self.art_masks is None: self._draw_mouse()  # freed while hidden
                self._preview_kick(); self._update_status()
                self._mascot_fit_soon()
            else:  # the picture buffers (1-5 MB) are not needed in the tray
                self._mascot_update()  # stops and frees the animation frames
                self.art_masks = self.art_lines = self.art_tk = None; self._art_scale = None
                if self.gv: self.gv.free_art()
                else: self.canvas.itemconfig(self.art_id, image="")

    def _focus_check_soon(self):
        if not self._focus_after: self._focus_after = self.root.after_idle(self._focus_check)

    def _focus_check(self):
        self._focus_after = None
        try: active = self.root.focus_get() is not None
        except (KeyError, tk.TclError): active = True  # focus in a menu or dialog of ours
        self._set_active(active)

    def _set_active(self, active):
        if active != self._active:
            self._active = active
            if self._ui_built: self._mascot_update()

    def _update_input(self):
        """Ask the listener only for the input an enabled feature needs right now."""
        if not self.raw: return
        stats = self.cfg["verbose_log"] and self._visible
        self.raw.stats_on = stats
        self.raw.configure(motion=self.cfg["smart_light"] or stats,
                           keys=bool(self.cfg["macros"]) or stats,
                           buttons=bool(self.rc and self.rc.active) or stats)

    def _poll_ui(self, event=None):
        self._wake_pending = False
        try:
            for _ in range(200):
                msg = self.ui_q.get_nowait()
                if callable(msg): msg()
                elif isinstance(msg, tuple) and msg[0] == "log": self._append_log(msg[1])
                elif msg in ("conn", "batt"): self._update_status()
        except queue.Empty: pass
        else: self._wake()  # more left: continue on the next turn of the event loop
        if event is None: self.root.after(5000, self._poll_ui)  # safety net only

    def _update_status(self):
        lvl, ch = self.batt
        fc = ""
        if not self.mouse.connected():
            txt, mode = 'mouse not found', 'Mouse disconnected.'
        else:
            mode = 'Connection: ' + ('2.4 GHz (dongle)' if self.mouse.wireless else 'USB cable')
            if self.mouse.generic: mode = self.mouse.product + '\n' + mode
            b = 'mouse asleep / off' if lvl is None else f"{lvl}%" + (' · charging' if ch else "")
            fc = self.sb.forecast_text() if self.sb and self.sb.enabled and lvl is not None and not ch else ""
            if fc: b += " · " + fc
            if self.saver: mode += "\n" + 'Battery saver: 500 Hz, lighting off.'
            txt = ('● 2.4 GHz · ' if self.mouse.wireless else "● USB · ") + b
        if self._ui_built:
            conn = self.mouse.connected()
            self.conn_lbl.config(text=('2.4 GHz' if self.mouse.wireless else 'USB') if conn else 'no mouse',
                                 fg=FG if conn else DIM)
            self.conn_dot.config(image=ui_theme.dot_image(GOOD if conn else DIM))
            self.batt_icon.config(image=ui_theme.battery_image(lvl if conn else None, bool(ch)))
            self.batt_lbl.config(text="{0}%".format(lvl) if conn and lvl is not None else "\u2014")
            self.batt_sub.config(text='charging' if conn and ch else (fc or ('asleep' if conn and lvl is None and self.mouse.has_battery else '')))
            if self.mouse.generic and not self.mouse.has_battery:  # wired mouse: no battery to show
                self.batt_lbl.config(text='Wired' if conn else "\u2014"); self.batt_sub.config(text='always on' if conn else '')
                if conn: self.batt_icon.config(image="")
            if self.gv: self.gv.update_status()
            self.mode_lbl.config(text=mode)
        if self.tray:
            state = (lvl, ch, self.mouse.connected())
            if state != getattr(self, "_tray_state", None):
                self.tray.icon = tray_image(lvl, ch); self._tray_state = state
            self.tray.title = f"{APP} — " + ('no mouse' if not self.mouse.connected() else
                                            ('battery unknown' if lvl is None else f"{lvl}%{' (charging)' if ch else ''}"))
            if self.sb and self.sb.enabled and lvl is not None and not ch: self.tray.title += " · " + self.sb.forecast_text()
            if lvl is not None and lvl <= 15 and not ch and not self._low_notified:
                self._low_notified = True
                try: self.tray.notify('Mouse battery {0}%'.format(lvl), APP)
                except Exception: pass
            if lvl is not None and (ch or lvl > 20): self._low_notified = False
        self._render_modules()

    def _preview_kick(self):
        if self._preview_after is None and self._visible:
            self._preview_after = self.root.after_idle(self._preview_tick)

    def _preview_tick(self):
        self._preview_after = None
        if not self._visible or self.mouse.generic: return
        L = self.cfg["light"]
        if self.preview: cols = self.preview
        elif L["mode"] == "off" or self._dark() or self.moving: cols = [(0, 0, 0)] * 3
        elif L["mode"] == "rainbow_hw": cols = [hsv(time.monotonic() * 0.15 + i * 0.12) for i in range(3)]
        else: cols = [scale(hex2rgb(x), L["brightness"] / 100) for x in L["colors"]]
        cols = [tuple(int(v) for v in c) for c in cols]
        steady = not self.preview and not (L["mode"] in SOFT + ("rainbow_hw",) and not self._dark())
        if steady and ui_theme.ANIMATE and self.art_cols and cols != self.art_cols:
            # a new steady colour: fade to it (~160 ms) instead of jumping
            if not self._fade or self._fade[2] != cols: self._fade = (list(self.art_cols), time.monotonic(), cols)
            frm, t0, to = self._fade
            f = min(1.0, (time.monotonic() - t0) / 0.16)
            self._render_art([tuple(round(a + (b - a) * f) for a, b in zip(x, y)) for x, y in zip(frm, to)])
            if f < 1: self._preview_after = self.root.after(16, self._preview_tick)
            else: self._fade = None
            return
        self._fade = None
        self._render_art(cols)
        if L["mode"] in SOFT + ("rainbow_hw",) and not self._dark():  # animated: next frame
            self._preview_after = self.root.after(100, self._preview_tick)

    # ---------- tray
    def _make_tray(self):
        def dpi_items():
            items = []
            for i, v in enumerate(self.cfg["dpi"]):
                items.append(pystray.MenuItem(f"{v} CPI", self._tray_dpi_action(i),
                                              checked=lambda it, i=i: self.cfg["dpi_active"] == i, radio=True))
            return items
        menu = pystray.Menu(
            pystray.MenuItem('Open', lambda: self.post(self.show), default=True),
            pystray.MenuItem("CPI", pystray.Menu(dpi_items)),
            pystray.MenuItem('High efficiency mode', lambda: self.post(lambda: self._flip("eco")),
                             checked=lambda it: self.cfg["eco"]),
            pystray.MenuItem('Smart lighting', lambda: self.post(lambda: self._flip("smart_light")),
                             checked=lambda it: self.cfg["smart_light"]),
            pystray.MenuItem('Multi-click & directional sens', lambda: self.post(self._helpers_toggle),
                             checked=lambda it: self._helpers_any()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Quit', lambda: self.post(self.quit)))
        if self.tray:
            self.tray.menu = menu; self.tray.update_menu()
        else:
            self.tray = pystray.Icon("AeroxLite", tray_image(None, False), APP, menu)
            self.tray.run_detached()

    def _tray_dpi_action(self, i):
        return lambda: self.post(lambda: self._sel_dpi(i))

    def show(self):
        self._ensure_ui()
        self.root.deiconify(); self.root.lift(); self.root.focus_force(); self._set_visible(True)
    def hide(self):
        self.root.withdraw(); self._set_visible(False)

    def quit(self):
        if self._after:
            self.root.after_cancel(self._after); self._after = None
        self.persist()
        self.running = False
        self.stop_event.set(); self._kick(); self.jobs.put(None)
        if self.raw:
            self.raw.stop(); self.raw.join(timeout=1)
        for thread in self.threads: thread.join(timeout=1.5)
        if self.macros: self.macros.stop_all()
        try: self.tray.stop()
        except Exception: pass
        if self.rc: self.rc.shutdown()  # remove the multi-click hook but remember the module is enabled
        if self.sb: self.sb.flush()
        if self.cfg["light"]["mode"] in SOFT and not self.saver and self._aerox_on():  # restore the static fallback
            try:
                k = self.cfg["light"]["brightness"] / 100
                for z, x in enumerate(self.cfg["light"]["colors"]): self.mouse.set_zone(z, scale(hex2rgb(x), k))
            except IOError: pass
        self.mouse.close()
        for handler in list(self.logger.handlers):
            handler.close(); self.logger.removeHandler(handler)
        self.root.destroy()


class MacroEditor:
    MODES = [("once", "Once"), ("hold", "While held"), ("toggle", "Toggle")]
    HELP = ("One line per action:\n\n"
            "ctrl+c        key combination\n"
            "enter         single key\n"
            "down shift    hold key\n"
            "up shift      release key\n"
            "wait 50       delay, ms\n"
            "text Hello    type text\n"
            "click left    left/right/middle\n"
            "# ...         comment\n\n"
            "Keys: a–z, 0–9, f1–f24,\n"
            "enter esc tab space backspace\n"
            "delete insert home end pgup\n"
            "pgdn up down left right caps\n"
            "ctrl shift alt win printscreen\n"
            "minus equals comma period\n"
            "slash tilde volup voldown\n"
            "mute play next prev")

    def __init__(self, app):
        self.app, self.cur, self.mode = app, None, "once"
        w = self.win = tk.Toplevel(app.root)
        w.title('Macro editor'); w.configure(bg=BG); sc = getattr(app, "ui_scale", 1.0) * getattr(app, "px_k", 1.0)
        w.geometry("{0}x{1}".format(round(900 * sc), round(560 * sc))); w.minsize(round(820 * sc), round(480 * sc))
        style_titlebar(w)
        left = panel(w, 'MACROS'); left.pack(side="left", fill="y", padx=(14, 8), pady=14)
        self.lb = tk.Listbox(left, bg=BTN, fg=FG, selectbackground=FG, selectforeground=BG, relief="flat",
                             highlightthickness=0, font=F, width=24, activestyle="none", exportselection=False)
        self.lb.pack(fill="both", expand=True, padx=10)
        self.lb.bind("<<ListboxSelect>>", lambda e: self._load())
        flatbtn(left, '+ NEW', self._new).pack(fill="x", padx=10, pady=(8, 4))
        flatbtn(left, 'DELETE', self._delete).pack(fill="x", padx=10, pady=(0, 10))

        right = panel(w, 'MACRO'); right.pack(side="left", fill="both", expand=True, padx=(0, 14), pady=14)
        r = tk.Frame(right, bg=PANEL); r.pack(fill="x", padx=10)
        tk.Label(r, text='Name', bg=PANEL, fg=FG, font=F).pack(side="left")
        self.name = tk.StringVar()
        tk.Entry(r, textvariable=self.name, bg=BTN, fg=FG, insertbackground=FG, relief="flat", font=FB).pack(
            side="left", fill="x", expand=True, padx=(10, 0), ipady=3)
        self.mode_row = tk.Frame(right, bg=PANEL); self.mode_row.pack(fill="x", padx=10, pady=8)
        body = tk.Frame(right, bg=PANEL); body.pack(fill="both", expand=True, padx=10)
        self.text = tk.Text(body, bg=BTN, fg=FG, insertbackground=FG, relief="flat", font=FM2,
                            width=34, undo=True, padx=8, pady=6)
        self.text.pack(side="left", fill="both", expand=True)
        tk.Label(body, text=self.HELP, bg=PANEL, fg=DIM, font=FM, justify="left").pack(
            side="left", anchor="n", padx=(10, 0))
        bot = tk.Frame(right, bg=PANEL); bot.pack(fill="x", padx=10, pady=10)
        self.msg = tk.Label(bot, text="", bg=PANEL, fg=DIM, font=FS, justify="left",
                            wraplength=round(420 * getattr(app, "ui_scale", 1.0) * getattr(app, "px_k", 1.0)))
        self.msg.pack(side="left")
        flatbtn(bot, 'SAVE', self._save, sel=True).pack(side="right")
        flatbtn(bot, 'TEST (in 3 s)', self._test).pack(side="right", padx=6)
        self._refresh(); self._set_enabled(False)
        if app.cfg["macros"]: self._select(0)

    def _items(self): return sorted(self.app.cfg["macros"], key=lambda m: m["slot"])

    def _refresh(self):
        self.lb.delete(0, "end")
        for m in self._items(): self.lb.insert("end", f"  {m['name']}")

    def _select(self, idx):
        self.lb.selection_clear(0, "end"); self.lb.selection_set(idx); self._load()

    def _set_enabled(self, on):
        self.text.config(state="normal" if on else "disabled")

    def _render_modes(self):
        for c in self.mode_row.winfo_children(): c.destroy()
        tk.Label(self.mode_row, text='Repeat', bg=PANEL, fg=FG, font=F).pack(side="left", padx=(0, 10))
        for k, t in self.MODES:
            flatbtn(self.mode_row, t, lambda k=k: self._set_mode(k), sel=(k == self.mode)).pack(side="left", padx=(0, 4))

    def _set_mode(self, k): self.mode = k; self._render_modes()

    def _load(self):
        sel = self.lb.curselection()
        if not sel: return
        m = self._items()[sel[0]]; self.cur = m["slot"]
        self.name.set(m["name"]); self.mode = m["mode"]; self._render_modes()
        self._set_enabled(True); self.text.delete("1.0", "end"); self.text.insert("1.0", m["script"])
        self.msg.config(text="")

    def _new(self):
        used = {m["slot"] for m in self.app.cfg["macros"]}
        free = [s for s in range(MAX_MACROS) if s not in used]
        if not free: self.msg.config(text='Maximum {0} macros.'.format(MAX_MACROS)); return
        s = free[0]
        self.app.cfg["macros"].append({"slot": s, "name": 'Macro {0}'.format(s + 1), "mode": "once",
                                       "script": "ctrl+c\nwait 50\nctrl+v"})
        self.app.persist(); self._refresh(); self.app._rebuild_bind_menus()
        self._select([m["slot"] for m in self._items()].index(s))

    def _delete(self):
        if self.cur is None: return
        if self.app.macros: self.app.macros.stop_all()
        a = self.app
        a.cfg["macros"] = [m for m in a.cfg["macros"] if m["slot"] != self.cur]
        for i, v in enumerate(a.cfg["binds"]):
            if v == f"macro:{self.cur}": a.cfg["binds"][i] = SLOTS[i][3]; a.changed("buttons")
        self.cur = None; a.persist(); self._refresh(); a._rebuild_bind_menus()
        self.name.set(""); self.text.delete("1.0", "end"); self._set_enabled(False)
        if a.cfg["macros"]: self._select(0)

    def _script(self): return self.text.get("1.0", "end").rstrip()

    def _save(self):
        if self.cur is None: return
        if self.app.macros: self.app.macros.stop_all()
        try: winput.parse(self._script())
        except ValueError as e: self.msg.config(text='Error: ' + str(e)); return
        m = self.app._macro_by_slot(self.cur)
        m.update(name=self.name.get().strip() or 'Macro {0}'.format(self.cur + 1), mode=self.mode, script=self._script())
        self.app.persist(); self._refresh(); self.app._rebuild_bind_menus()
        self._select([x["slot"] for x in self._items()].index(self.cur))
        self.msg.config(text='Saved. Assign the macro to a button in Actions → Macros. Macros require the app running (in the tray).')

    def _test(self):
        try: ops = winput.parse(self._script())
        except ValueError as e: self.msg.config(text='Error: ' + str(e)); return
        self.msg.config(text='The macro runs in 3 seconds — switch to the target window.')
        def test():
            if not self.app.stop_event.wait(3): winput.run(ops, self.app.stop_event)
        thread = threading.Thread(target=test, daemon=True)
        self.app.threads.append(thread); thread.start()


def self_test():
    """--self-test: every module and native library loaded (imports run at module load), plus the image
    code the app needs at run time (tray icon font, PNG artwork, filters). No window."""
    tray_image(85, True)
    art = Image.open(io.BytesIO(base64.b64decode(mouse_art.CELLS))).convert("L")
    ImageChops.lighter(art.filter(ImageFilter.GaussianBlur(3)).convert("RGB"), art.convert("RGB"))
    models = len(generic.profiles(hid))  # rivalcfg device descriptions (other SteelSeries mice)
    assert models > 50, models
    import model_art  # pictures of the other mice
    for data in model_art.ART.values(): Image.open(io.BytesIO(base64.b64decode("".join(data)))).load()
    import mascot_art  # the panel animation
    for _, _, data in mascot_art.MASCOT.values(): Image.open(io.BytesIO(base64.b64decode("".join(data)))).load()
    print("Aerox Lite self-test: OK ({m} mouse models; HID backend: {0}, raw input: {1})".format(hid.__name__, "ok" if winput else "unavailable", m=models))


def _enable_crash_log():
    """On a hard crash (segfault, abort) write the Python stack of every thread to crash.log in the
    app folder. Costs nothing while the app runs normally."""
    try:
        import faulthandler
        os.makedirs(CFG_DIR, exist_ok=True)
        f = open(os.path.join(CFG_DIR, "crash.log"), "a", encoding="utf-8")
        f.write("\n--- {0} start\n".format(time.strftime("%Y-%m-%d %H:%M:%S"))); f.flush()
        faulthandler.enable(file=f, all_threads=True)
        globals()["_crash_file"] = f   # keep it open for the life of the process
    except Exception:
        pass


def main():
    if "--self-test" in sys.argv:
        return self_test()
    if "--calibrate" in sys.argv:  # separate calibration process, before the single-instance mutex
        import calibration
        calibration.cli()
        return
    _enable_crash_log()
    mutex = None
    kernel = None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        mutex = kernel.CreateMutexW(None, False, r"Local\AeroxLite.Controller")
        if not mutex: raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            kernel.CloseHandle(mutex)
            return
        try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception: pass
    try: App(hidden="--tray" in sys.argv).root.mainloop()
    finally:
        if mutex: kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
