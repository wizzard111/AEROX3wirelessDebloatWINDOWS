"""
Windows part of Aerox Lite:
  * RawInput — listens to mouse movement (for smart lighting) and the F13–F24 keys
    the mouse sends instead of buttons bound to a macro. No hooks => no cursor latency.
  * parse/run — macro language and playback via SendInput (scan codes, works in games too).
"""
import ctypes, struct, threading, time
from collections import deque
from ctypes import wintypes as W

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", W.HINSTANCE), ("hIcon", W.HICON),
                ("hCursor", W.HANDLE), ("hbrBackground", W.HBRUSH), ("lpszMenuName", W.LPCWSTR),
                ("lpszClassName", W.LPCWSTR)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", W.DWORD), ("Data2", W.WORD), ("Data3", W.WORD), ("Data4", ctypes.c_ubyte * 8)]


class DEV_BROADCAST_DEVICEINTERFACE(ctypes.Structure):
    _fields_ = [("dbcc_size", W.DWORD), ("dbcc_devicetype", W.DWORD), ("dbcc_reserved", W.DWORD),
                ("dbcc_classguid", GUID), ("dbcc_name", ctypes.c_wchar * 1)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", W.USHORT), ("usUsage", W.USHORT), ("dwFlags", W.DWORD), ("hwndTarget", W.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", W.DWORD), ("dwSize", W.DWORD), ("hDevice", W.HANDLE), ("wParam", W.WPARAM)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class _IU(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", W.DWORD), ("u", _IU)]


user32.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = W.ATOM
user32.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
user32.CreateWindowExW.restype = W.HWND
user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), W.UINT, W.UINT]
user32.RegisterRawInputDevices.restype = W.BOOL
user32.GetRawInputData.argtypes = [W.HANDLE, W.UINT, W.LPVOID, ctypes.POINTER(W.UINT), W.UINT]
user32.GetRawInputData.restype = W.UINT
user32.GetMessageW.argtypes = [ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(W.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(W.MSG)]
user32.GetRawInputDeviceInfoW.argtypes = [W.HANDLE, W.UINT, W.LPVOID, ctypes.POINTER(W.UINT)]
user32.GetRawInputDeviceInfoW.restype = W.UINT
user32.MapVirtualKeyW.argtypes = [W.UINT, W.UINT]
user32.MapVirtualKeyW.restype = W.UINT
user32.SendInput.argtypes = [W.UINT, ctypes.c_void_p, ctypes.c_int]
kernel32.GetModuleHandleW.argtypes = [W.LPCWSTR]
kernel32.GetModuleHandleW.restype = W.HMODULE
user32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
user32.PostMessageW.restype = W.BOOL
user32.DestroyWindow.argtypes = [W.HWND]
user32.DestroyWindow.restype = W.BOOL
user32.UnregisterClassW.argtypes = [W.LPCWSTR, W.HINSTANCE]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.RegisterDeviceNotificationW.argtypes = [W.HANDLE, W.LPVOID, W.DWORD]
user32.RegisterDeviceNotificationW.restype = W.HANDLE
user32.UnregisterDeviceNotification.argtypes = [W.HANDLE]

# HID device arrival/removal notifications (no polling for a newly plugged-in mouse)
WM_DEVICECHANGE, DBT_DEVICEARRIVAL, DBT_DEVICEREMOVECOMPLETE, DBT_DEVTYP_DEVICEINTERFACE = 0x0219, 0x8000, 0x8004, 5
GUID_DEVINTERFACE_HID = GUID(0x4D1E55B2, 0xF16F, 0x11CF, (ctypes.c_ubyte * 8)(0x88, 0xCB, 0x00, 0x11, 0x11, 0x00, 0x00, 0x30))
_NAME_OFFSET = DEV_BROADCAST_DEVICEINTERFACE.dbcc_name.offset

WM_INPUT, RID_INPUT, RIDEV_INPUTSINK, HWND_MESSAGE = 0x00FF, 0x10000003, 0x100, -3
RIDEV_REMOVE, RIDEV_DEVNOTIFY, WM_APP_REREGISTER = 0x1, 0x2000, 0x8001
RIDI_DEVICENAME = 0x20000007
VK_F13 = 0x7C
BTN_LEFT, BTN_RIGHT = "left", "right"
_U32, _PTR, _U16, _BTN, _XY = (struct.Struct(f).unpack_from for f in ("I", "P", "H", "Hh", "ii"))


class RawInput(threading.Thread):
    """Listens to Raw Input. Only events from the SteelSeries mouse (VID_1038) pass the filter.
    on_move() — movement; on_key(vk, down) — keys the mouse sends (bindings/macros F13–F24);
    on_button(code, down, t) — left/right button of the SteelSeries mouse (multi-click).
    Only the needed device classes are registered (configure()): no mouse registration means no
    WM_INPUT per cursor move at all. Injected input (SendInput) has no device and is ignored.
    If stats_on: accumulates movement in counters and queues rare events in events.
    """
    BTN = ((0x001, 0x002, "Left click"), (0x004, 0x008, "Right click"), (0x010, 0x020, "Middle click"),
           (0x040, 0x080, "Side back"), (0x100, 0x200, "Side forward"))

    def __init__(self, on_move, on_key, vid="VID_1038", on_error=None):
        super().__init__(daemon=True)
        self.on_move, self.on_key, self.vid = on_move, on_key, vid
        self.on_error = on_error
        self.on_button = None
        self._want = {"motion": True, "keys": True, "buttons": False}
        self._registered = {2: False, 6: False}
        self.hotplug = False      # True once HID arrival/removal notifications are registered
        self.on_hotplug = None    # called when a SteelSeries device is plugged in or removed
        self.hwnd = None
        self.stop_event = threading.Event()
        self.stats_lock = threading.Lock()
        self.stats_on = False
        self.n = self.dx = self.dy = self.wheel = 0
        self.pos = [0, 0]
        self.t_first = self.t_last = 0.0
        self.events = deque(maxlen=300)
        self._devs, self._down = {}, {}
        self.found = False  # whether any SteelSeries event has been seen

    def take_motion(self):
        """Drain accumulated movement (called once per second)."""
        with self.stats_lock:
            n, dx, dy, w, t0, t1 = self.n, self.dx, self.dy, self.wheel, self.t_first, self.t_last
            self.n = self.dx = self.dy = self.wheel = 0
            return n, dx, dy, w, (t1 - t0), tuple(self.pos)

    def stop(self):
        self.stop_event.set()
        if self.hwnd: user32.PostMessageW(self.hwnd, 0x0010, 0, 0)

    def configure(self, motion=None, keys=None, buttons=None):
        for k, v in (("motion", motion), ("keys", keys), ("buttons", buttons)):
            if v is not None: self._want[k] = bool(v)
        if self.hwnd: user32.PostMessageW(self.hwnd, WM_APP_REREGISTER, 0, 0)

    def set_button_handler(self, cb):
        self.on_button = cb
        self.configure()

    def _register(self, hwnd):
        """(Un)register mouse (usage 2) and keyboard (usage 6) to match what is needed. Message thread only."""
        w = self._want
        need = {2: w["motion"] or w["buttons"] or self.on_button is not None or self.stats_on, 6: w["keys"]}
        for usage, on in need.items():
            if on == self._registered[usage]: continue
            dev = RAWINPUTDEVICE(1, usage, RIDEV_INPUTSINK | RIDEV_DEVNOTIFY, hwnd) if on else RAWINPUTDEVICE(1, usage, RIDEV_REMOVE, None)
            if user32.RegisterRawInputDevices(ctypes.byref(dev), 1, ctypes.sizeof(RAWINPUTDEVICE)) or not on:
                self._registered[usage] = on
            elif on:
                raise ctypes.WinError(ctypes.get_last_error())

    def run(self):
        try: self._message_loop()
        except Exception as e:
            if self.on_error: self.on_error(e)


    def _is_ours(self, hdev):
        r = self._devs.get(hdev)
        if r is None:
            r = False
            if hdev:
                size = W.UINT(0)
                user32.GetRawInputDeviceInfoW(hdev, RIDI_DEVICENAME, None, ctypes.byref(size))
                name = ctypes.create_unicode_buffer(size.value + 1)
                if user32.GetRawInputDeviceInfoW(hdev, RIDI_DEVICENAME, name, ctypes.byref(size)) > 0:
                    r = self.vid in name.value.upper()
            self._devs[hdev] = r
            if r: self.found = True
        return r

    def _message_loop(self):
        hdr = ctypes.sizeof(RAWINPUTHEADER)
        buf = ctypes.create_string_buffer(128)  # one long-lived buffer — no allocation per event
        size = W.UINT(0)
        perf = time.perf_counter

        def proc(hwnd, msg, wp, lp):
            if msg == 0x0010:
                user32.DestroyWindow(hwnd); return 0
            if msg == 0x0002:
                user32.PostQuitMessage(0); return 0
            if msg == 0x00FE:
                self._devs.clear(); self.found = False; return 0
            if msg == WM_DEVICECHANGE:
                if wp in (DBT_DEVICEARRIVAL, DBT_DEVICEREMOVECOMPLETE) and lp and self.on_hotplug:
                    try:
                        hdr = ctypes.cast(lp, ctypes.POINTER(DEV_BROADCAST_DEVICEINTERFACE)).contents
                        name = ctypes.wstring_at(lp + _NAME_OFFSET) if hdr.dbcc_devicetype == DBT_DEVTYP_DEVICEINTERFACE else ""
                        if self.vid in name.upper(): self.on_hotplug()
                    except Exception:
                        pass
                return 1
            if msg == WM_APP_REREGISTER:
                try: self._register(hwnd)
                except OSError as e:
                    if self.on_error: self.on_error(e)
                return 0
            if msg == WM_INPUT:
                try:
                    size.value = 128
                    if user32.GetRawInputData(lp, RID_INPUT, buf, ctypes.byref(size), hdr) not in (0, 0xFFFFFFFF):
                        typ, hdev = _U32(buf, 0)[0], _PTR(buf, 8)[0]
                        ours = self._is_ours(hdev)
                        if typ == 0:
                            bflags, bdata = _BTN(buf, hdr + 4)
                            x, y = _XY(buf, hdr + 12)
                            if (x or y) and self._want["motion"] and (ours or not self.found): self.on_move()
                            if bflags and ours and self.on_button:
                                if bflags & 0x003: self.on_button(BTN_LEFT, bool(bflags & 0x001), None)
                                if bflags & 0x00C: self.on_button(BTN_RIGHT, bool(bflags & 0x004), None)
                            if ours and self.stats_on:
                                with self.stats_lock:
                                    if x or y:
                                        t = perf()
                                        if not self.n: self.t_first = t
                                        self.t_last = t; self.n += 1
                                        self.dx += x; self.dy += y; self.pos[0] += x; self.pos[1] += y
                                    if bflags:
                                        if bflags & 0x400: self.wheel += bdata // 120
                                        for dn, up, name in self.BTN:
                                            if bflags & dn: self._down[name] = perf()
                                            if bflags & up:
                                                t0 = self._down.pop(name, None)
                                                self.events.append(("btn", name, None if t0 is None else int((perf() - t0) * 1000)))
                        elif typ == 1 and ours:
                            flags, vk = _U16(buf, hdr + 2)[0], _U16(buf, hdr + 6)[0]
                            down = not (flags & 1)
                            self.on_key(vk, down)
                            if self.stats_on and down: self.events.append(("key", vk, None))
                except Exception:
                    pass
            return user32.DefWindowProcW(hwnd, msg, wp, lp)

        self._proc = WNDPROC(proc)  # keep a reference, otherwise GC
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = self._proc, hinst, "AeroxLiteRawInput"
        if not user32.RegisterClassW(ctypes.byref(wc)): raise ctypes.WinError(ctypes.get_last_error())
        hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "AeroxLite", 0, 0, 0, 0, 0,
                                      W.HWND(HWND_MESSAGE), None, hinst, None)
        if not hwnd: raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = hwnd
        filt = DEV_BROADCAST_DEVICEINTERFACE(ctypes.sizeof(DEV_BROADCAST_DEVICEINTERFACE), DBT_DEVTYP_DEVICEINTERFACE, 0,
                                             GUID_DEVINTERFACE_HID)
        notify = user32.RegisterDeviceNotificationW(hwnd, ctypes.byref(filt), 0)
        self.hotplug = bool(notify)
        try:
            self._register(hwnd)
            if self.stop_event.is_set(): return
            msg = W.MSG()
            while True:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == -1: raise ctypes.WinError(ctypes.get_last_error())
                if result == 0: break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self.hotplug = False
            if notify: user32.UnregisterDeviceNotification(notify)
            for usage in (2, 6):
                if self._registered[usage]:
                    user32.RegisterRawInputDevices(ctypes.byref(RAWINPUTDEVICE(1, usage, RIDEV_REMOVE, None)), 1,
                                                   ctypes.sizeof(RAWINPUTDEVICE))
                    self._registered[usage] = False
            user32.DestroyWindow(hwnd)
            self.hwnd = None
            user32.UnregisterClassW(wc.lpszClassName, hinst)


# ---------------------------------------------------------------- Macros
VK = {c.lower(): ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"}
VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})
VK.update({
    "enter": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20, "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdn": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "caps": 0x14, "printscreen": 0x2C,
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
    "minus": 0xBD, "equals": 0xBB, "comma": 0xBC, "period": 0xBE, "slash": 0xBF, "semicolon": 0xBA,
    "quote": 0xDE, "lbracket": 0xDB, "rbracket": 0xDD, "backslash": 0xDC, "tilde": 0xC0,
    "volup": 0xAF, "voldown": 0xAE, "mute": 0xAD, "play": 0xB3, "next": 0xB0, "prev": 0xB1,
})
VK_NAMES = {v: k for k, v in VK.items()}
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x2C}
MEDIA_VK = {0xAF, 0xAE, 0xAD, 0xB3, 0xB0, 0xB1}
KEYUP, UNICODE, SCANCODE, EXTKEY = 0x2, 0x4, 0x8, 0x1
CLICK = {"left": (0x02, 0x04), "right": (0x08, 0x10), "middle": (0x20, 0x40)}
STEP_DELAY = 0.015


def _vk(name, n):
    k = name.strip().lower()
    if k not in VK: raise ValueError("Line {0}: unknown key “{1}”".format(n, name))
    return VK[k]


def parse(text):
    ops = []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"): continue
        parts = line.split(None, 1)
        cmd, arg = parts[0], parts[1] if len(parts) > 1 else ""
        c, arg = cmd.lower(), arg.strip()
        if c == "wait":
            try: ops.append(("wait", max(0, int(arg))))
            except ValueError: raise ValueError("Line {0}: wait requires a number (ms)".format(n))
        elif c == "text":
            ops.append(("text", arg))
        elif c in ("down", "up") and arg:
            ops.append((c, _vk(arg, n)))
        elif c == "click":
            if arg.lower() not in CLICK: raise ValueError("Line {0}: click left / right / middle".format(n))
            ops.append(("click", arg.lower()))
        else:
            ops.append(("combo", [_vk(k, n) for k in line.replace(" ", "").split("+")]))
    return ops


def _send(*items):
    arr = (INPUT * len(items))(*items)
    if user32.SendInput(len(items), arr, ctypes.sizeof(INPUT)) != len(items):
        raise OSError("SendInput failed (target may require elevated permissions)")


def key(vk, up=False):
    flags = (KEYUP if up else 0) | (EXTKEY if vk in EXTENDED else 0)
    scan = 0 if vk in MEDIA_VK else user32.MapVirtualKeyW(vk, 0)
    ki = KEYBDINPUT(0, scan, flags | SCANCODE, 0, 0) if scan else KEYBDINPUT(vk, 0, flags, 0, 0)
    _send(INPUT(1, _IU(ki=ki)))


def type_text(s, stop=None):
    encoded = s.encode("utf-16-le", errors="replace")
    for offset in range(0, len(encoded), 2):
        if stop is not None and stop.is_set(): return
        code = int.from_bytes(encoded[offset:offset+2], "little")
        _send(INPUT(1, _IU(ki=KEYBDINPUT(0, code, UNICODE, 0, 0))),
              INPUT(1, _IU(ki=KEYBDINPUT(0, code, UNICODE | KEYUP, 0, 0))))


def click(btn):
    d, u = CLICK[btn]
    _send(INPUT(0, _IU(mi=MOUSEINPUT(0, 0, 0, d, 0, 0))))
    time.sleep(0.01)
    _send(INPUT(0, _IU(mi=MOUSEINPUT(0, 0, 0, u, 0, 0))))


def run(ops, stop=None):
    held = []
    try:
        for op, arg in ops:
            if stop is not None and stop.is_set(): break
            if op == "wait":
                end = time.monotonic() + arg / 1000
                while time.monotonic() < end:
                    if stop is not None and stop.is_set(): return
                    time.sleep(min(0.01, max(0, end - time.monotonic())))
                continue
            if op == "combo":
                for vk in arg:
                    key(vk); held.append(vk); time.sleep(0.005)
                for vk in reversed(arg):
                    key(vk, True); held.remove(vk)
            elif op == "down": key(arg); held.append(arg)
            elif op == "up":
                key(arg, True)
                if arg in held: held.remove(arg)
            elif op == "text": type_text(arg, stop)
            elif op == "click": click(arg)
            time.sleep(STEP_DELAY)
    finally:
        for vk in reversed(held):
            try: key(vk, True)
            except OSError: pass  # never leave keys held down


class MacroRunner:
    """Modes: once — run once; hold — repeat while the button is held; toggle — repeat on/off."""

    def __init__(self, get_macro):
        self.get, self.held, self.stops = get_macro, set(), {}
        self.lock = threading.RLock()
        self.threads = {}
        self.on_error = None

    def on_key(self, vk, down):
        with self.lock: self._on_key_locked(vk, down)

    def _on_key_locked(self, vk, down):
        if not VK_F13 <= vk <= VK_F13 + 11: return
        slot = vk - VK_F13
        m = self.get(slot)
        if not m:
            if not down: self.held.discard(slot)
            return
        running = slot in self.stops and not self.stops[slot].is_set()
        if down:
            if slot in self.held: return  # key auto-repeat
            self.held.add(slot)
            if m["mode"] == "toggle" and running: self.stops[slot].set()
            elif not running: self._start(slot, m, loop=m["mode"] in ("hold", "toggle"))
        else:
            self.held.discard(slot)
            if m["mode"] == "hold" and running: self.stops[slot].set()

    def stop_all(self):
        with self.lock:
            for ev in self.stops.values(): ev.set()
            threads = list(self.threads.values())
        for thread in threads:
            if thread is not threading.current_thread(): thread.join(timeout=0.5)

    def _start(self, slot, m, loop):
        try: ops = parse(m["script"])
        except ValueError: return
        ev = threading.Event(); self.stops[slot] = ev

        def go():
            try:
                while not ev.is_set():
                    run(ops, ev)
                    if not loop: break
                    ev.wait(0.01)
            except Exception as e:
                if self.on_error: self.on_error(e)
            finally:
                ev.set()
        thread = threading.Thread(target=go, daemon=True)
        self.threads[slot] = thread
        thread.start()
