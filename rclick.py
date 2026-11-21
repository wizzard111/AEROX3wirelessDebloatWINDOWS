"""
rclick.py — left/right multi-click for Aerox Lite.
A short button press -> N clicks (×2…×6, each button has its own N and toggle), like drag-clicking.
The tap threshold (tap_ms) is adjustable: shorter press = multi-click, longer = hold.
Holding works as usual (mining, bow, shield, eating in Minecraft).

A low-level mouse hook (WH_MOUSE_LL) passes the physical press through immediately (the first click
has no delay). If the button is released faster than tap_ms, it sends N-1 more clicks via SendInput
from a separate thread. Injected clicks (ours and others', including macros) are ignored by the hook.
The hook is installed only while the feature is on — off means zero impact on input.
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
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    winmm = ctypes.WinDLL("winmm")
    LRESULT = ctypes.c_ssize_t
    ULONG_PTR = ctypes.c_size_t
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
    WH_MOUSE_LL, WM_QUIT = 14, 0x0012
    WM_BUTTONS = {0x0201: ("left", True), 0x0202: ("left", False), 0x0204: ("right", True), 0x0205: ("right", False)}
    LLMHF_INJECTED, LLMHF_LOWER_IL_INJECTED = 0x1, 0x2
    INPUT_MOUSE = 0
    SEND_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010)}  # DOWN, UP

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD),
                    ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

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

    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
    user32.SetWindowsHookExW.restype = wt.HHOOK
    user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
    user32.CallNextHookEx.restype = LRESULT
    user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wt.HINSTANCE
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.GetCurrentThreadId.restype = wt.DWORD

    def _send(flags):
        i = INPUT(INPUT_MOUSE, _IU(mi=MOUSEINPUT(0, 0, 0, flags, 0, MAGIC)))
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))



class RightClickMultiplier:
    def __init__(self, log=print):
        self.log = lambda text, warn=False: log(text, warn)
        self.cfg = load_cfg()
        self._jobs = queue.Queue()
        self._hook_tid = None
        self._hook = None
        self._proc = None
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
        return self._hook_tid is not None

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
        if not self.active:
            ready = threading.Event()
            threading.Thread(target=self._hook_loop, args=(ready,), daemon=True).start()
            ready.wait(2)
            if not self.active:
                self.log("Multi-click: could not install the hook", True)
                return False
            if self._worker is None:
                self._worker = threading.Thread(target=self._click_loop, daemon=True)
                self._worker.start()
            winmm.timeBeginPeriod(1)   # precise pauses between clicks
        self.cfg["enabled"] = True
        self.save()
        self.log("Multi-click: ON ({0}; {1})".format(counts_text(self.cfg), "everywhere"))
        return True

    def _unhook(self):
        if not self.active:
            return
        user32.PostThreadMessageW(self._hook_tid, WM_QUIT, 0, 0)
        for _ in range(50):
            if not self.active:
                break
            time.sleep(0.01)
        winmm.timeEndPeriod(1)

    def disable(self):
        """Full disable: the hook is removed, input goes straight through."""
        self._unhook()
        self.cfg["enabled"] = False
        self.save()
        self.log("Multi-click: OFF")

    def shutdown(self):
        """App exit: remove the hook but remember the module is enabled."""
        self._unhook()

    # ---------- hook
    def _hook_loop(self, ready):
        self._proc = HOOKPROC(self._on_mouse)   # keep a reference, otherwise GC
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        if not self._hook:
            ready.set()
            return
        self._hook_tid = kernel32.GetCurrentThreadId()
        ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        self._hook_tid = None

    def _on_mouse(self, code, wp, lp):
        # as fast as possible: everything except left/right goes straight on; input is never swallowed
        ev = WM_BUTTONS.get(wp) if code == 0 else None
        if ev and self.cfg[f"{ev[0]}_on"]:
            button, down = ev
            info = ctypes.cast(lp, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            injected = info.flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED)
            if not injected and info.dwExtraInfo != MAGIC:
                if down:
                    self._down_t[button] = time.perf_counter()
                elif self._down_t[button] is not None:
                    n = is_tap((time.perf_counter() - self._down_t[button]) * 1000, self.cfg, button)
                    self._down_t[button] = None
                    if n:
                        self._jobs.put((button, n))
        return user32.CallNextHookEx(None, code, wp, lp)

    def _click_loop(self):
        while True:
            button, n = self._jobs.get()
            down, up = SEND_FLAGS[button]
            hold, gap = self.cfg["hold_ms"] / 1000, self.cfg["gap_ms"] / 1000
            time.sleep(gap)                       # pause after the real click
            for i in range(n):
                _send(down)
                time.sleep(hold)
                _send(up)
                if i < n - 1:
                    time.sleep(gap)
