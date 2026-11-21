"""
rclick.py — left/right multi-click for Aerox Lite.
A short button press -> N clicks (×2…×6, each button has its own N and toggle), like drag-clicking.
The tap threshold (tap_ms) is adjustable: shorter press = multi-click, longer = hold.
Holding works as usual (mining, bow, shield, eating in Minecraft).

Button presses of the SteelSeries mouse come from the app's Raw Input listener (winput.RawInput),
which never delays the cursor (unlike a low-level mouse hook). If a button is released faster than
tap_ms, N-1 more clicks are sent via SendInput from a separate thread; injected clicks have no
device and are not seen by Raw Input. Off = the listener is not even asked for mouse buttons.
"""
import os, json, time, queue, threading


APPDIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AeroxLite")
CFG_PATH = os.path.join(APPDIR, "rclick.json")
DEFAULTS = {
    "enabled": False,
    "left_on": False,    # left button: multi-click enabled
    "right_on": True,    # right button: multi-click enabled
    "left": 3,           # left button: clicks per short press (COUNT_MIN..COUNT_MAX)
    "right": 3,          # right button: same
    "hold_ms": 8,        # how long to hold each injected click
    "gap_ms": 14,        # pause between clicks
    "tap_ms": 150,       # shorter press = tap (multi-click), longer = hold
}
COUNT_MIN, COUNT_MAX = 2, 6
TAP_MIN, TAP_MAX, TAP_STEP = 60, 400, 10
BUTTONS = ("left", "right")
MAGIC = 0xAE0C1C         # tag for our own SendInput events


def load_cfg():
    cfg = dict(DEFAULTS)
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if "count" in data and "right" not in data:  # first-version config (right button only)
                data["right"] = data["count"]
            for b in BUTTONS:  # intermediate format: 0/1 clicks = button disabled
                if f"{b}_on" not in data and isinstance(data.get(b), int) and not isinstance(data.get(b), bool):
                    data[f"{b}_on"] = data[b] > 1
                    if data[b] < COUNT_MIN: data[b] = DEFAULTS[b]
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    try:
        for k, lo, hi in (("left", COUNT_MIN, COUNT_MAX), ("right", COUNT_MIN, COUNT_MAX), ("hold_ms", 1, 100),
                          ("gap_ms", 1, 200), ("tap_ms", TAP_MIN, TAP_MAX)):
            cfg[k] = max(lo, min(hi, int(cfg[k])))
    except (TypeError, ValueError):
        cfg.update({k: DEFAULTS[k] for k in ("left", "right", "hold_ms", "gap_ms", "tap_ms")})
    for k in ("enabled", "left_on", "right_on"):
        cfg[k] = cfg[k] is True
    return cfg


def is_tap(held_ms, cfg, button="right"):
    """Short press -> how many extra clicks to send (0 = hold or button disabled)."""
    n = cfg[button]
    return n - 1 if cfg[f"{button}_on"] and held_ms < cfg["tap_ms"] and n > 1 else 0


def counts_text(cfg):
    off = "off"
    return "left {0}, right {1}".format(*(f"×{cfg[b]}" if cfg[f"{b}_on"] else off for b in BUTTONS))


if os.name == "nt":
    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    winmm = ctypes.WinDLL("winmm")
    ULONG_PTR = ctypes.c_size_t
    INPUT_MOUSE = 0
    SEND_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010)}  # DOWN, UP

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                    ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                    ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _IU(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wt.DWORD), ("u", _IU)]

    user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

    def _send(flags):
        i = INPUT(INPUT_MOUSE, _IU(mi=MOUSEINPUT(0, 0, 0, flags, 0, MAGIC)))
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


class RightClickMultiplier:
    def __init__(self, log=print, listener=None):
        self.log = lambda text, warn=False: log(text, warn)
        self.cfg = load_cfg()
        self._jobs = queue.Queue()
        self._listener = listener  # winput.RawInput of the app
        self._attached = False
        self._worker = None
        self._down_t = {"left": None, "right": None}

    def save(self):
        os.makedirs(APPDIR, exist_ok=True)
        tmp = CFG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CFG_PATH)

    @property
    def active(self):
        return self._attached

    def set_count(self, button, n):
        self.cfg[button] = max(COUNT_MIN, min(COUNT_MAX, int(n)))
        self.save()

    def set_button(self, button, on):
        self.cfg[f"{button}_on"] = bool(on)
        self.save()

    def set_tap(self, ms):
        self.cfg["tap_ms"] = max(TAP_MIN, min(TAP_MAX, int(ms)))
        self.save()

    # ---------- on / off
    def enable(self):
        if os.name != "nt":
            self.log("Multi-click requires Windows", True)
            return False
        if self._listener is None:
            self.log("Multi-click: Raw Input is unavailable", True)
            return False
        if not self._attached:
            self._listener.set_button_handler(self._on_button)
            self._attached = True
            if self._worker is None:
                self._worker = threading.Thread(target=self._click_loop, daemon=True)
                self._worker.start()
        self.cfg["enabled"] = True
        self.save()
        self.log("Multi-click: ON ({0}; {1})".format(counts_text(self.cfg), "everywhere"))
        return True

    def _unhook(self):
        if self._attached:
            self._listener.set_button_handler(None)
            self._attached = False

    def disable(self):
        """Full disable: the listener stops reporting buttons."""
        self._unhook()
        self.cfg["enabled"] = False
        self.save()
        self.log("Multi-click: OFF")

    def shutdown(self):
        """App exit: detach but remember the module is enabled."""
        self._unhook()

    # ---------- buttons (Raw Input thread)
    def _on_button(self, button, down, t=None):
        if not self.cfg.get(f"{button}_on"): return
        now = time.perf_counter()
        if down:
            self._down_t[button] = now
        elif self._down_t[button] is not None:
            n = is_tap((now - self._down_t[button]) * 1000, self.cfg, button)
            self._down_t[button] = None
            if n:
                self._jobs.put((button, n))

    def _click_loop(self):
        while True:
            button, n = self._jobs.get()
            down, up = SEND_FLAGS[button]
            hold, gap = self.cfg["hold_ms"] / 1000, self.cfg["gap_ms"] / 1000
            winmm.timeBeginPeriod(1)   # precise pauses, only for the duration of a burst
            try:
                time.sleep(gap)                       # pause after the real click
                for i in range(n):
                    _send(down)
                    time.sleep(hold)
                    _send(up)
                    if i < n - 1:
                        time.sleep(gap)
            finally:
                winmm.timeEndPeriod(1)
