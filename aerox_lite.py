"""
Aerox Lite — a lightweight SteelSeries GG replacement for the Aerox 3 Wireless (2020/2022, Snow/Ghost).
The protocol comes from the open-source rivalcfg project (reverse engineering).
Tray with battery level, CPI, polling rate, timers, bindings, lighting (including software effects).

IMPORTANT: close SteelSeries GG / SteelSeries Engine before starting (and remove it from autostart) —
GG is the most common reason the lighting gets overwritten and looks "unstable".
"""
import os, sys, json, time, math, threading, queue, colorsys, subprocess
from collections import deque
import copy, logging
from logging.handlers import RotatingFileHandler
from config_store import normalize, atomic_save
import tkinter as tk
from tkinter import colorchooser, filedialog

import hid
import pystray
import io, base64
from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageChops, ImageFilter

import mouse_art
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

CFG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AeroxLite")
CFG_PATH = os.path.join(CFG_DIR, "config.json")

# TrueMove Air sensor CPI table: 100..18000 in steps of 100 -> byte
DPI_CODES = [0, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 16, 17, 18, 19, 20, 22, 23, 24, 25, 26, 27, 29, 30, 31, 32, 33, 35, 37, 38, 39, 40, 41, 42, 44, 45, 46, 47, 48, 50, 51, 52, 53, 54, 56, 57, 58, 59, 60, 62, 63, 64, 65, 66, 68, 69, 70, 71, 72, 74, 75, 76, 77, 78, 80, 81, 82, 83, 84, 86, 87, 88, 89, 90, 92, 93, 94, 95, 96, 98, 99, 100, 101, 102, 104, 105, 106, 107, 108, 110, 111, 112, 113, 114, 116, 117, 118, 119, 120, 122, 123, 124, 125, 126, 128, 129, 130, 131, 132, 134, 135, 136, 137, 138, 140, 141, 142, 143, 144, 146, 147, 148, 149, 150, 152, 153, 154, 155, 156, 158, 159, 160, 161, 162, 164, 165, 166, 167, 168, 170, 171, 172, 173, 174, 176, 177, 178, 179, 180, 181, 182, 183, 184, 185, 186, 187, 188, 189, 191, 192, 194, 195, 196, 197, 198, 199, 201, 202, 203, 204, 205, 207, 208, 209, 210, 211, 213, 214]
ECHO_CMDS = {0x11, 0x21, 0x22, 0x23, 0x26, 0x27, 0x29, 0x2A, 0x2B, 0x2D, 0x92}
POLL = {125: 0x03, 250: 0x02, 500: 0x01, 1000: 0x00}

# ---- Bindings ----
SLOTS = [  # (label, diagram tag, packet offset, default)
    ("Button 1", "B1", 0x00, "button1"), ("Button 2", "B2", 0x05, "button2"),
    ("Button 3", "B3", 0x0A, "button3"), ("Button 4", "B4", 0x0F, "button4"),
    ("Button 5", "B5", 0x14, "button5"), ("Button 6", "B6", 0x19, "dpi"),
    ("Scroll up", "", 0x1E, "scrollup"), ("Scroll down", "", 0x23, "scrolldown"),
]
SPECIAL = {"button1": 0x01, "button2": 0x02, "button3": 0x03, "button4": 0x04, "button5": 0x05,
           "button6": 0x06, "scrollup": 0x31, "scrolldown": 0x32, "dpi": 0x30, "disabled": 0x00}
SPECIAL_NAMES = [("Button 1", "button1"), ("Button 2", "button2"), ("Button 3", "button3"),
                 ("Button 4", "button4"), ("Button 5", "button5"), ("Cycle CPI", "dpi"),
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


# ---------------------------------------------------------------- Device
class Mouse:
    def __init__(self):
        self.dev, self.wireless, self.lock = None, False, threading.RLock()
        self.pid, self.product = 0, ""
        self.unsolicited = deque(maxlen=50)  # reports the mouse sent on its own

    def connected(self): return self.dev is not None

    def open(self):
        with self.lock:
            if self.dev: return True
            cands = []
            for d in hid.enumerate(VID, 0):
                if d.get("interface_number") != IFACE: continue
                pid, prod = d["product_id"], (d.get("product_string") or "").lower()
                if pid in KNOWN_PIDS: cands.append((1 if KNOWN_PIDS[pid] else 0, d, KNOWN_PIDS[pid]))
                elif "aerox 3" in prod: cands.append((2, d, None))
            for _, d, wl in sorted(cands, key=lambda c: c[0]):  # cable takes priority over dongle
                try:
                    h = hid.device(); h.open_path(d["path"])
                except (OSError, IOError):
                    continue
                self.dev, self.pid, self.product = h, d["product_id"], d.get("product_string") or "Aerox 3"
                self.wireless = wl if wl is not None else not self._probe_wired()
                return True
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


# ---------------------------------------------------------------- Config
DEFAULT = {
    "dpi": [200, 400, 1200, 2400, 3200], "dpi_active": 1, "poll": 1000,
    "sleep": 5, "dim": 30, "binds": [s[3] for s in SLOTS],
    "light": {"mode": "static", "colors": ["#ffffff", "#ffffff", "#ffffff"], "brightness": 100,
              "speed": 40, "reactive": False, "reactive_color": "#ffffff"},
    "apply_on_connect": True, "autostart": False, "fps": 15,
    "eco": False, "smart_light": False, "smart_delay": 0.6, "verbose_log": True,
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
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True, creationflags=0x08000000, timeout=3).stdout.lower()
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
BG, PANEL, LINE, BTN, HOV, FG, DIM = "#000000", "#0b0b0b", "#262626", "#161616", "#2a2a2a", "#ffffff", "#8c8c8c"
F, FB, FS, FT = ("Segoe UI", 9), ("Segoe UI Semibold", 9), ("Segoe UI", 8), ("Segoe UI Semibold", 11)


def flatbtn(parent, text, cmd, sel=False, **kw):
    b = tk.Label(parent, text=text, bg=FG if sel else BTN, fg=BG if sel else FG, font=kw.pop("font", FB),
                 padx=kw.pop("padx", 10), pady=kw.pop("pady", 5), cursor="hand2", **kw)
    b.bind("<Button-1>", lambda e: cmd())
    if not sel:
        b.bind("<Enter>", lambda e: b.config(bg=HOV)); b.bind("<Leave>", lambda e: b.config(bg=BTN))
    return b


def panel(parent, title=None):
    f = tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
    if title: tk.Label(f, text=title, bg=PANEL, fg=DIM, font=FS).pack(anchor="w", padx=10, pady=(8, 4))
    return f


def slider(parent, frm, to, res, cmd):
    return tk.Scale(parent, from_=frm, to=to, resolution=res, orient="horizontal", showvalue=0,
                    bg=PANEL, fg=FG, troughcolor="#2e2e2e", activebackground=FG, highlightthickness=0,
                    bd=0, sliderrelief="flat", sliderlength=14, width=8, command=cmd)


class App:
    def __init__(self, hidden):
        self.cfg, self.mouse = load_cfg(), Mouse()
        self.stop_event = threading.Event()
        self.threads = []
        self.ui_q, self.jobs = queue.Queue(), queue.Queue()
        self.logger = logging.getLogger("AeroxLite")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        try:
            os.makedirs(CFG_DIR, exist_ok=True)
            handler = RotatingFileHandler(self.LOG_FILE, maxBytes=512 * 1024, backupCount=1, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            self.logger.addHandler(handler)
        except OSError: pass
        self.batt, self.preview, self.running, self.tray = (None, None), None, True, None
        self.sel_dpi = min(self.cfg["dpi_active"], len(self.cfg["dpi"]) - 1)
        self._pending, self._after, self._loading, self._low_notified = set(), None, False, False
        self.last_move, self.moving, self.editor = 0.0, False, None
        self.log_text, self.raw = None, None
        self.macros = winput.MacroRunner(self._macro_by_slot) if winput else None

        if self.macros: self.macros.on_error = lambda e: self.log(str(e), True)
        self.saver, self.sb, self.rc = False, None, None  # battery saver, modules
        self._init_modules()
        self.root = tk.Tk()
        self.root.title(APP); self.root.configure(bg=BG); self.root.geometry("1180x690"); self.root.minsize(1100, 650)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self._build()
        style_titlebar(self.root)
        self.log('Aerox Lite started')
        if hidden: self.root.withdraw()

        for target in (self._worker, self._monitor, self._effects, self._smart):
            thread = threading.Thread(target=target, daemon=True)
            self.threads.append(thread); thread.start()
        if winput:
            try:
                self.raw = winput.RawInput(self._on_move, self._macro_key, on_error=lambda e: self.log("Raw input unavailable: {0}".format(e), True))
                self.raw.stats_on = self.cfg["verbose_log"]; self.raw.start()
            except Exception as e: self.log('Raw input unavailable: {0}'.format(e))
        self._make_tray()
        self.root.after(100, self._poll_ui)
        self.root.after(60, self._preview_tick)
        if gg_running():
            self.warn.config(text='⚠ SteelSeries GG is running — close it to prevent settings conflicts')
            self.log('Warning: SteelSeries GG is running')

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
        top = tk.Frame(self.root, bg=BG); top.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(top, text="AEROX 3 WIRELESS", bg=BG, fg=FG, font=("Segoe UI Semibold", 13)).pack(side="left")
        self.status = tk.Label(top, text='searching for mouse…', bg=BG, fg=DIM, font=F); self.status.pack(side="right")
        self.warn = tk.Label(self.root, text="", bg=BG, fg=FG, font=FS); self.warn.pack(fill="x", padx=14)
        tk.Frame(self.root, bg=LINE, height=1).pack(fill="x", padx=14, pady=(2, 8))

        body = tk.Frame(self.root, bg=BG); body.pack(fill="both", expand=True, padx=14)
        body.columnconfigure(1, weight=1); body.rowconfigure(0, weight=1)

        # ---- Actions (left)
        left = panel(body, 'ACTIONS'); left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        self.bind_btns = []
        for i, (name, tag, _, _) in enumerate(SLOTS):
            row = tk.Frame(left, bg=PANEL); row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=name + (f"  {tag}" if tag else ""), bg=PANEL, fg=DIM, font=F, width=17, anchor="e").pack(side="left")
            mb = tk.Menubutton(row, text="", bg=BTN, fg=FG, activebackground=HOV, activeforeground=FG,
                               relief="flat", font=FB, anchor="w", width=17, padx=8, pady=3, cursor="hand2")
            mb["menu"] = self._bind_menu(mb, i); mb.pack(side="left", padx=(6, 0))
            self.bind_btns.append(mb)
        flatbtn(left, 'RESET BINDINGS', self._reset_binds).pack(fill="x", padx=10, pady=(10, 4))
        mr = tk.Frame(left, bg=PANEL); mr.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(mr, text='Macro editor', bg=PANEL, fg=DIM, font=F, width=17, anchor="e").pack(side="left")
        flatbtn(mr, 'OPEN', self.open_editor, width=14).pack(side="left", padx=(6, 0))
        self.mode_lbl = tk.Label(left, text="", bg=PANEL, fg=DIM, font=FS, justify="left", wraplength=290)
        self.mode_lbl.pack(anchor="w", padx=10, pady=(12, 6))
        lh = tk.Frame(left, bg=PANEL); lh.pack(fill="x", padx=10)
        tk.Label(lh, text='LOG', bg=PANEL, fg=DIM, font=FS).pack(side="left")
        clr = tk.Label(lh, text='clear', bg=PANEL, fg=DIM, font=("Segoe UI", 8, "underline"), cursor="hand2")
        clr.bind("<Button-1>", lambda e: self._clear_log()); clr.pack(side="right")
        self.verb_lbl = tk.Label(lh, bg=PANEL, fg=DIM, font=("Segoe UI", 8, "underline"), cursor="hand2")
        self.verb_lbl.bind("<Button-1>", lambda e: self._toggle_verbose()); self.verb_lbl.pack(side="right", padx=(0, 10))
        self._render_verbose()
        lw = tk.Frame(left, bg=LINE, padx=1, pady=1); lw.pack(fill="both", expand=True, padx=10, pady=(3, 10))
        self.log_text = tk.Text(lw, bg="#050505", fg="#bdbdbd", font=("Consolas", 8), relief="flat", wrap="word",
                                height=8, width=40, padx=6, pady=4, state="disabled", cursor="arrow",
                                highlightthickness=0, selectbackground="#444")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_config("t", foreground="#5f5f5f")
        self.log_text.tag_config("w", foreground=FG)

        # ---- Center: tabs + mouse diagram
        center = tk.Frame(body, bg=BG); center.grid(row=0, column=1, sticky="n")
        tabs = tk.Frame(center, bg=BG); tabs.pack(pady=(0, 6))
        self.tab_btns = {}
        for key, txt in (("settings", 'Settings'), ("light", 'Lighting'), ("modules", 'Modules')):
            b = tk.Label(tabs, text=txt, font=FT, padx=16, pady=8, cursor="hand2")
            b.bind("<Button-1>", lambda e, k=key: self._tab(k)); b.pack(side="left")
            self.tab_btns[key] = b
        self.canvas = tk.Canvas(center, width=320, height=ART_Y + mouse_art.SIZE[1] + 10, bg=BG, highlightthickness=0); self.canvas.pack()
        self._draw_mouse()

        # ---- Right side
        self.right = tk.Frame(body, bg=BG, width=420); self.right.grid(row=0, column=2, sticky="ns")
        self.p_settings = tk.Frame(self.right, bg=BG); self.p_light = tk.Frame(self.right, bg=BG)
        self.p_modules = tk.Frame(self.right, bg=BG)
        self._build_settings(self.p_settings); self._build_light(self.p_light); self._build_modules(self.p_modules)

        # ---- Bottom
        bot = tk.Frame(self.root, bg=BG); bot.pack(fill="x", side="bottom", padx=14, pady=10)
        self.v_auto = tk.BooleanVar(value=self.cfg["autostart"]); self.v_apply = tk.BooleanVar(value=self.cfg["apply_on_connect"])
        for var, txt, cmd in ((self.v_auto, 'Start with Windows', self._toggle_autostart),
                              (self.v_apply, 'Apply settings on connect', self._toggle_apply)):
            tk.Checkbutton(bot, text=txt, variable=var, command=cmd, bg=BG, fg=FG, selectcolor=BG,
                           activebackground=BG, activeforeground=FG, font=F, bd=0, highlightthickness=0).pack(side="left", padx=(0, 16))
        self.save_btn = flatbtn(bot, 'SAVE TO MOUSE', self.save_all, sel=True, padx=18, pady=7)
        self.save_btn.pack(side="right")
        self.save_lbl = tk.Label(bot, text="", bg=BG, fg=DIM, font=F); self.save_lbl.pack(side="right", padx=12)

        self._load_into_ui(); self._tab("settings")

    def _bind_menu(self, mb, i):
        m = tk.Menu(mb, tearoff=0, bg="#111", fg=FG, activebackground=FG, activeforeground=BG, font=F)
        for n, v in SPECIAL_NAMES: m.add_command(label=n, command=lambda v=v: self._set_bind(i, v))
        m.add_separator()
        groups = (('Letters', list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")), ('Numbers', list("1234567890")),
                  ("F1–F12", [f"F{k}" for k in range(1, 13)]),
                  ('Navigation', ["Enter", "Esc", "Backspace", "Tab", "Space", "PrintScreen", "Insert", "Delete",
                                 "Home", "End", "PageUp", "PageDown", "Up", "Down", "Left", "Right"]),
                  ('Modifiers', ["LCtrl", "LShift", "LAlt", "Win"]))
        kb = tk.Menu(m, tearoff=0, bg="#111", fg=FG, activebackground=FG, activeforeground=BG, font=F)
        for gname, keys in groups:
            sub = tk.Menu(kb, tearoff=0, bg="#111", fg=FG, activebackground=FG, activeforeground=BG, font=F)
            for k in keys: sub.add_command(label=k, command=lambda k=k: self._set_bind(i, "key:" + k))
            kb.add_cascade(label=gname, menu=sub)
        m.add_cascade(label='Keyboard', menu=kb)
        mm = tk.Menu(m, tearoff=0, bg="#111", fg=FG, activebackground=FG, activeforeground=BG, font=F)
        for k, (n, _) in MEDIA.items(): mm.add_command(label=n, command=lambda k=k: self._set_bind(i, "media:" + k))
        m.add_cascade(label='Media', menu=mm)
        mc = tk.Menu(m, tearoff=0, bg="#111", fg=FG, activebackground=FG, activeforeground=BG, font=F)
        for mac in sorted(self.cfg["macros"], key=lambda x: x["slot"]):
            mc.add_command(label=mac["name"], command=lambda sl=mac["slot"]: self._set_bind(i, f"macro:{sl}"))
        if not self.cfg["macros"]: mc.add_command(label='(no macros — open editor)', state="disabled")
        m.add_cascade(label='Macros', menu=mc)
        return m

    def _rebuild_bind_menus(self):
        for i, mb in enumerate(self.bind_btns):
            mb["menu"] = self._bind_menu(mb, i)
            mb.config(text=action_name(self.cfg["binds"][i], self.cfg["macros"]))

    def _build_settings(self, p):
        # CPI
        dp = panel(p, 'SENSITIVITY LEVELS (CPI)'); dp.pack(fill="x")
        self.dpi_tabs = tk.Frame(dp, bg=PANEL); self.dpi_tabs.pack(fill="x", padx=10)
        r = tk.Frame(dp, bg=PANEL); r.pack(fill="x", padx=10, pady=(8, 0))
        self.dpi_slider = slider(r, 100, 18000, 100, self._on_dpi_slider); self.dpi_slider.pack(side="left", fill="x", expand=True)
        self.dpi_var = tk.StringVar()
        e = tk.Entry(r, textvariable=self.dpi_var, width=7, bg=BTN, fg=FG, insertbackground=FG, relief="flat", font=FB, justify="center")
        e.pack(side="left", padx=(10, 0), ipady=3); e.bind("<Return>", self._on_dpi_entry); e.bind("<FocusOut>", self._on_dpi_entry)
        r2 = tk.Frame(dp, bg=PANEL); r2.pack(fill="x", padx=10, pady=(2, 4))
        tk.Label(r2, text="100", bg=PANEL, fg=DIM, font=FS).pack(side="left")
        tk.Label(r2, text="18000", bg=PANEL, fg=DIM, font=FS).pack(side="right", padx=(0, 70))
        self.rm_dpi = tk.Label(dp, text='Remove level', bg=PANEL, fg=FG, font=("Segoe UI", 8, "underline"), cursor="hand2")
        self.rm_dpi.bind("<Button-1>", lambda e: self._rm_dpi()); self.rm_dpi.pack(anchor="w", padx=10, pady=(0, 10))

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
        self.poll_row = tk.Frame(pp, bg=PANEL); self.poll_row.pack(fill="x", padx=10, pady=(0, 10))

    def _toggle_row(self, parent, key, title, desc):
        row = tk.Frame(parent, bg=PANEL); row.pack(fill="x", padx=10, pady=(2, 0))
        b = tk.Label(row, font=FB, width=6, pady=3, cursor="hand2")
        b.bind("<Button-1>", lambda e: self._flip(key)); b.pack(side="left")
        tk.Label(row, text=title, bg=PANEL, fg=FG, font=F).pack(side="left", padx=(8, 0))
        tk.Label(parent, text=desc, bg=PANEL, fg=DIM, font=FS, wraplength=380, justify="left").pack(anchor="w", padx=10, pady=(2, 8))
        self.tgl[key] = b

    def _render_toggles(self):
        for key, b in self.tgl.items():
            on = self.cfg[key]
            b.config(text='ON' if on else 'OFF', bg=FG if on else BTN, fg=BG if on else FG)

    def _flip(self, key):
        self.cfg[key] = not self.cfg[key]; self._render_toggles()
        self.log({"eco": 'High efficiency mode', "smart_light": 'Smart lighting mode'}[key]
                 + (': on' if self.cfg[key] else ': off'))
        if self.tray:
            try: self.tray.update_menu()
            except Exception: pass
        if key == "eco": self.changed("power")
        self.changed("light")

    def _labeled_slider(self, parent, title, frm, to, res, cmd):
        h = tk.Frame(parent, bg=PANEL); h.pack(fill="x", padx=10)
        tk.Label(h, text=title, bg=PANEL, fg=FG, font=F).pack(side="left")
        val = tk.Label(h, text="", bg=PANEL, fg=FG, font=FB); val.pack(side="right")
        s = slider(parent, frm, to, res, cmd); s.pack(fill="x", padx=10, pady=(2, 10))
        return val, s

    def _build_light(self, p):
        mp = panel(p, 'LIGHTING MODE'); mp.pack(fill="x")
        self.mode_grid = tk.Frame(mp, bg=PANEL); self.mode_grid.pack(fill="x", padx=10, pady=(0, 10))

        zp = panel(p, 'ZONES'); zp.pack(fill="x", pady=8)
        self.swatches = []
        for z, name in enumerate(('Zone 1 — front', 'Zone 2 — middle', 'Zone 3 — rear')):
            row = tk.Frame(zp, bg=PANEL); row.pack(fill="x", padx=10, pady=3)
            tk.Label(row, text=name, bg=PANEL, fg=FG, font=F, width=18, anchor="w").pack(side="left")
            sw = tk.Label(row, text="", width=6, bg="#fff", cursor="hand2", highlightbackground=FG, highlightthickness=1)
            sw.bind("<Button-1>", lambda e, z=z: self._pick_zone(z)); sw.pack(side="left")
            self.swatches.append(sw)
        flatbtn(zp, 'ONE COLOR FOR ALL ZONES', self._pick_all).pack(fill="x", padx=10, pady=(6, 10))

        op = panel(p, 'OPTIONS'); op.pack(fill="x")
        self.br_lbl, self.br_s = self._labeled_slider(op, 'Brightness', 0, 100, 1, self._on_bright)
        self.sp_lbl, self.sp_s = self._labeled_slider(op, 'Effect speed', 1, 100, 1, self._on_speed)
        rr = tk.Frame(op, bg=PANEL); rr.pack(fill="x", padx=10, pady=(0, 10))
        self.v_react = tk.BooleanVar()
        tk.Checkbutton(rr, text='Flash on click (reactive)', variable=self.v_react, command=self._on_react,
                       bg=PANEL, fg=FG, selectcolor=PANEL, activebackground=PANEL, activeforeground=FG, font=F,
                       bd=0, highlightthickness=0).pack(side="left")
        self.react_sw = tk.Label(rr, text="", width=4, bg="#fff", cursor="hand2", highlightbackground=FG, highlightthickness=1)
        self.react_sw.bind("<Button-1>", lambda e: self._pick_react()); self.react_sw.pack(side="right")
        tk.Label(p, text='* Software effect: requires the app running (in the tray).\nStatic color and hardware rainbow work without the app after saving.',
                 bg=BG, fg=DIM, font=FS, justify="left").pack(anchor="w", pady=8)

    def _draw_mouse(self):
        """Mouse diagram (mouse_art.py): outline + shell holes tinted with the zone colors."""
        c = self.canvas
        lines = Image.open(io.BytesIO(base64.b64decode(mouse_art.LINES))).convert("L")
        cells = Image.open(io.BytesIO(base64.b64decode(mouse_art.CELLS))).convert("L")
        W, H = cells.size
        self.art_size, self.art_lines, self.art_masks = (W, H), Image.merge("RGB", (lines,) * 3), []
        for z in range(3):  # zones top to bottom: front / middle / rear
            band = Image.new("L", (W, H), 0)
            ImageDraw.Draw(band).rectangle((0, z * H // 3, W, (z + 1) * H // 3), fill=255)
            m = ImageChops.multiply(cells, band)
            self.art_masks.append((m, m.filter(ImageFilter.GaussianBlur(5))))
        ox, oy = (320 - W) // 2, ART_Y
        self.art_cols, self.art_tk = None, None
        self.art_id = c.create_image(ox, oy, anchor="nw")
        A = {k: (x + ox, y + oy) for k, (x, y) in mouse_art.ANCHORS.items()}
        labels = {"B3": (A["B3"][0], 16), "B1": (22, A["B1"][1]), "B2": (298, A["B2"][1]),
                  "B6": (298, A["B6"][1]), "B5": (22, A["B5"][1]), "B4": (22, A["B4"][1])}
        for tag, (lx, ly) in labels.items():
            tx, ty = A[tag]
            c.create_line(lx, ly, tx, ty, fill=DIM)
            c.create_oval(tx - 3, ty - 3, tx + 3, ty + 3, fill=FG, outline=BG)
            c.create_rectangle(lx - 15, ly - 10, lx + 15, ly + 10, fill=BG, outline=FG)
            c.create_text(lx, ly, text=tag, fill=FG, font=FB)
        self._render_art([(0, 0, 0)] * 3)

    def _render_art(self, cols):
        cols = [tuple(int(v) for v in col) for col in cols]
        if cols == self.art_cols: return
        self.art_cols, (W, H) = cols, self.art_size
        frame = Image.new("RGB", (W, H), (0, 0, 0))
        for (m, glow), col in zip(self.art_masks, cols):
            if max(col) <= 12:
                frame.paste((24, 24, 24), (0, 0, W, H), m)
            else:
                frame.paste(scale(col, 0.45), (0, 0, W, H), glow)
                frame.paste(col, (0, 0, W, H), m)
        self.art_tk = ImageTk.PhotoImage(ImageChops.lighter(frame, self.art_lines))
        self.canvas.itemconfig(self.art_id, image=self.art_tk)

    # ---------- populate UI from config
    def _load_into_ui(self):
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
        for k, b in self.tab_btns.items():
            b.config(bg=FG if k == key else BTN, fg=BG if k == key else FG)
        for pane in (self.p_settings, self.p_light, self.p_modules): pane.pack_forget()
        {"settings": self.p_settings, "light": self.p_light, "modules": self.p_modules}[key].pack(fill="both")

    def _render_dpi(self):
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
        for w in self.poll_row.winfo_children(): w.destroy()
        for hz in (125, 250, 500, 1000):
            flatbtn(self.poll_row, '{0} Hz'.format(hz), lambda hz=hz: self._set_poll(hz), sel=(hz == self.cfg["poll"]),
                    padx=12).pack(side="left", padx=(0, 4), expand=True, fill="x")

    def _render_modes(self):
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
            try: cats, save, snapshot = self.jobs.get(timeout=0.5)
            except queue.Empty: continue
            self._apply(cats, save, snapshot)

    def _monitor(self):
        last, was_conn, waiting_logged = 0, False, False
        while self.running:
            if was_conn and not self.mouse.connected():
                self.log('Mouse disconnected', True); was_conn = False
            if not self.mouse.connected():
                try: opened = self.mouse.open()
                except (OSError, IOError) as e:
                    opened = False; self.log(f"HID: {e}", True)
                if opened:
                    m = self.mouse
                    self.log('Connected: {0} (PID 0x{1:04X}), '.format(m.product, m.pid)
                             + ('2.4 GHz dongle' if m.wireless else 'USB cable'))
                    last, was_conn, waiting_logged = 0, True, False; self.post("conn")
                    if self.cfg["apply_on_connect"]: self.post(lambda: self.enqueue({"dpi", "poll", "power", "buttons", "light"}))
                else:
                    if not waiting_logged: self.log('Mouse not found — waiting for connection…'); waiting_logged = True
                    if self.batt != (None, None): self.batt = (None, None); self.post("batt")
                    self.post("conn"); self.stop_event.wait(2); continue
            if time.monotonic() - last > (30 if self.batt[0] is not None else 5):
                prev = self.batt
                self.batt = self.mouse.battery(); last = time.monotonic()
                sb = self.sb
                if sb:  # forecast first, then UI update — otherwise the UI sees stale data
                    try: sb.update(*self.batt)
                    except Exception as e: self.log('Smart battery: error {0}'.format(e), True)
                self.post("batt")
                if self.batt != prev:
                    lvl, ch = self.batt
                    self.log('Mouse asleep or powered off' if lvl is None else 'Battery: {0}%'.format(lvl) + (' (charging)' if ch else ""))
                if prev[0] is None and self.batt[0] is not None and self.cfg["apply_on_connect"]:
                    self.log('Mouse awake — restoring lighting')
                    self.post(lambda: self.enqueue({"light"}))  # mouse woke up / powered on
            self.stop_event.wait(1)

    def _effects(self):
        t0, last = time.monotonic(), None
        while self.running:
            L = copy.deepcopy(self.cfg["light"])
            if L["mode"] in SOFT and not self._dark():
                cols = [(0, 0, 0)] * 3 if self.moving else effect_frame(L, time.monotonic() - t0)
                self.preview = cols
                if self.mouse.connected() and self.batt[0] is not None and cols != last:
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
            else:
                self.preview, last = None, None; self.stop_event.wait(0.2)

    def _on_move(self): self.last_move = time.monotonic()

    def _smart(self):
        """Smart lighting: turn zones off while the mouse moves, restore after a pause.
        Also, once per second, a mouse data summary for the log."""
        next_tick = 0.0
        while self.running:
            if time.monotonic() >= next_tick:
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
                if L["mode"] not in SOFT and self.mouse.connected():
                    if mv:
                        try:
                            with self.mouse.lock:
                                if L["mode"] == "rainbow_hw": self.mouse.set_default_light(False, False)
                                for z in range(3): self.mouse.set_zone(z, (0, 0, 0), fast=True)
                        except IOError: pass
                    else:
                        self.post(lambda: self.enqueue({"light"}))
            # Preserve 50 ms responsiveness only while smart lighting is active.
            # Otherwise there is no reason to wake this worker 20 times per second.
            self.stop_event.wait(0.05 if active else 0.25)

    # ---------- modules (directional sensitivity, multi-click, smart battery)
    def _dark(self):
        return self.cfg["eco"] or getattr(self, "saver", False)

    def _init_modules(self):
        """Only enabled modules are imported."""
        if helpers.module_on("battery"): self._load_battery()
        if helpers.module_on("rclick"):
            import rclick
            self.rc = rclick.RightClickMultiplier(self.log)
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
                    self.rc = rclick.RightClickMultiplier(self.log)
                if not self.rc.enable(): self.rc = None
            else:
                if not self.rc:
                    import rclick
                    self.rc = rclick.RightClickMultiplier(self.log)
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
        self.minfo["dir_prof"].pack(fill="x", padx=10)
        self.minfo["dir_ra"] = tk.Label(dp, bg=PANEL, fg=DIM, font=FS, anchor="w", justify="left", wraplength=380)
        self.minfo["dir_ra"].pack(fill="x", padx=10, pady=(2, 0))
        br = tk.Frame(dp, bg=PANEL); br.pack(fill="x", padx=10, pady=(8, 10))
        flatbtn(br, 'CALIBRATE', self._calibrate).pack(side="left", expand=True, fill="x", padx=(0, 4))
        flatbtn(br, 'RAW ACCEL FOLDER', self._pick_rawaccel).pack(side="left", expand=True, fill="x")

        rp = panel(p, 'MULTI-CLICK'); rp.pack(fill="x", pady=8)
        self._mod_row(rp, "rclick", 'Left / right multi-click',
                      'A press shorter than the tap threshold = several clicks; longer = normal hold.')
        self.rcw, self._rc_loading, self._rc_after = {}, False, None
        for button, name in (("left", 'Left click'), ("right", 'Right click')):
            row = tk.Frame(rp, bg=PANEL); row.pack(fill="x", padx=10, pady=(4, 0))
            b = tk.Label(row, font=FB, width=6, pady=2, cursor="hand2")
            b.bind("<Button-1>", lambda e, bt=button: self._rc_btn_flip(bt)); b.pack(side="left")
            tk.Label(row, text=name, bg=PANEL, fg=FG, font=F).pack(side="left", padx=(8, 0))
            val = tk.Label(row, bg=PANEL, fg=FG, font=FB); val.pack(side="right")
            sl = slider(rp, 2, 6, 1, lambda v, bt=button: self._on_rc_count(bt, v)); sl.pack(fill="x", padx=10, pady=(2, 0))
            self.rcw[button] = (b, val, sl)
        tr_row = tk.Frame(rp, bg=PANEL); tr_row.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(tr_row, text='Tap threshold', bg=PANEL, fg=FG, font=F).pack(side="left")
        tap_val = tk.Label(tr_row, bg=PANEL, fg=FG, font=FB); tap_val.pack(side="right")
        tap_sl = slider(rp, 60, 400, 10, self._on_rc_tap); tap_sl.pack(fill="x", padx=10, pady=(2, 10))
        self.rcw["tap"] = (None, tap_val, tap_sl)

        bp = panel(p, 'SMART BATTERY'); bp.pack(fill="x")
        self._mod_row(bp, "battery", 'Smart battery',
                      'Below 25% — notification, 500 Hz and lighting off. Charging or ≥30% restores everything.')
        self.minfo["bat"] = tk.Label(bp, bg=PANEL, fg=FG, font=FB, anchor="w")
        self.minfo["bat"].pack(fill="x", padx=10, pady=(0, 10))
        self._render_modules()

    def _mod_row(self, parent, name, title, desc):
        row = tk.Frame(parent, bg=PANEL); row.pack(fill="x", padx=10, pady=(2, 0))
        b = tk.Label(row, font=FB, width=6, pady=3, cursor="hand2")
        b.bind("<Button-1>", lambda e: self._mod_flip(name)); b.pack(side="left")
        tk.Label(row, text=title, bg=PANEL, fg=FG, font=F).pack(side="left", padx=(8, 0))
        tk.Label(parent, text=desc, bg=PANEL, fg=DIM, font=FS, wraplength=380, justify="left").pack(anchor="w", padx=10, pady=(2, 6))
        self.mtgl[name] = b

    def _render_modules(self):
        try:
            if not self.mtgl["battery"].winfo_exists(): return
        except (AttributeError, KeyError, tk.TclError):
            return
        for name, b in self.mtgl.items():
            on = self._mod_is_on(name)
            b.config(text='ON' if on else 'OFF', bg=FG if on else BTN, fg=BG if on else FG)
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
            b.config(text='ON' if on else 'OFF', bg=FG if on else BTN, fg=BG if on else FG)
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
        if not getattr(self, "_rc_edit", None): self._rc_edit = rclick.RightClickMultiplier(self.log)
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
        self.ui_q.put(("log", line))
        self.logger.info(text)

    def _append_log(self, line):
        if not self.log_text: return
        t, text, warn = line
        lt = self.log_text
        lt.config(state="normal")
        lt.insert("end", t + "  ", "t"); lt.insert("end", text + "\n", "w" if warn else ())
        if int(lt.index("end-1c").split(".")[0]) > 400: lt.delete("1.0", "100.0")
        lt.config(state="disabled"); lt.see("end")

    def _render_verbose(self):
        self.verb_lbl.config(text='mouse data: ' + ('on' if self.cfg["verbose_log"] else 'off'))

    def _toggle_verbose(self):
        self.cfg["verbose_log"] = not self.cfg["verbose_log"]; self.persist(); self._render_verbose()
        if self.raw: self.raw.stats_on = self.cfg["verbose_log"]; self.raw.take_motion()
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
    def post(self, msg): self.ui_q.put(msg)

    def _poll_ui(self):
        try:
            for _ in range(100):
                msg = self.ui_q.get_nowait()
                if callable(msg): msg()
                elif isinstance(msg, tuple) and msg[0] == "log": self._append_log(msg[1])
                elif msg in ("conn", "batt"): self._update_status()
        except queue.Empty: pass
        self.root.after(100, self._poll_ui)

    def _update_status(self):
        lvl, ch = self.batt
        if not self.mouse.connected():
            txt, mode = 'mouse not found', 'Mouse disconnected.'
        else:
            mode = 'Connection: ' + ('2.4 GHz (dongle)' if self.mouse.wireless else 'USB cable')
            b = 'mouse asleep / off' if lvl is None else f"{lvl}%" + (' · charging' if ch else "")
            fc = self.sb.forecast_text() if self.sb and self.sb.enabled and lvl is not None and not ch else ""
            if fc: b += " · " + fc
            if self.saver: mode += "\n" + 'Battery saver: 500 Hz, lighting off.'
            txt = ('● 2.4 GHz · ' if self.mouse.wireless else "● USB · ") + b
        self.status.config(text=txt, fg=FG if self.mouse.connected() else DIM)
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

    def _preview_tick(self):
        L = self.cfg["light"]
        if self.preview: cols = self.preview
        elif L["mode"] == "off" or self._dark() or self.moving: cols = [(0, 0, 0)] * 3
        elif L["mode"] == "rainbow_hw": cols = [hsv(time.monotonic() * 0.15 + i * 0.12) for i in range(3)]
        else: cols = [scale(hex2rgb(x), L["brightness"] / 100) for x in L["colors"]]
        if self.root.state() != "withdrawn": self._render_art(cols)
        self.root.after(80 if self.root.state() != "withdrawn" else 1000, self._preview_tick)

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

    def show(self): self.root.deiconify(); self.root.lift(); self.root.focus_force()
    def hide(self): self.root.withdraw()

    def quit(self):
        if self._after:
            self.root.after_cancel(self._after); self._after = None
        self.persist()
        self.running = False
        self.stop_event.set()
        if self.raw:
            self.raw.stop(); self.raw.join(timeout=1)
        for thread in self.threads: thread.join(timeout=1.5)
        if self.macros: self.macros.stop_all()
        try: self.tray.stop()
        except Exception: pass
        if self.rc: self.rc.shutdown()  # remove the multi-click hook but remember the module is enabled
        if self.sb: self.sb.flush()
        if self.cfg["light"]["mode"] in SOFT and not self.saver and self.mouse.connected():  # restore the static fallback
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
        w.title('Macro editor'); w.configure(bg=BG); w.geometry("900x560"); w.minsize(820, 480)
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
        self.text = tk.Text(body, bg=BTN, fg=FG, insertbackground=FG, relief="flat", font=("Consolas", 10),
                            width=34, undo=True, padx=8, pady=6)
        self.text.pack(side="left", fill="both", expand=True)
        tk.Label(body, text=self.HELP, bg=PANEL, fg=DIM, font=("Consolas", 8), justify="left").pack(
            side="left", anchor="n", padx=(10, 0))
        bot = tk.Frame(right, bg=PANEL); bot.pack(fill="x", padx=10, pady=10)
        self.msg = tk.Label(bot, text="", bg=PANEL, fg=DIM, font=FS, wraplength=420, justify="left")
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


def main():
    if "--calibrate" in sys.argv:  # separate calibration process, before the single-instance mutex
        import calibration
        calibration.cli()
        return
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
