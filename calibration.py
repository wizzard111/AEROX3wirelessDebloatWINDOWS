"""
calibration.py — directional sensitivity for Aerox Lite.

1) Mini-game: 8 directions x 4 flicks. For each flick we capture the point where the hand
   stopped after the initial motion (before correction). Overshoot/undershoot -> multiplier.
   Result: %APPDATA%\\AeroxLite\\directional.json
2) Applied via the Raw Accel driver (1.6+): a copy of your settings.json is built with
   modified Output DPI, Y/X, L/R and U/D (→ ↓ ← ↑) and passed to writer.exe.
   Your settings.json is never modified. Disabling = writer.exe settings.json.

Calibration runs in a SEPARATE process (Raw Input registration is per process; inside
Aerox Lite it would override winput.py's registration). In the built EXE this is
`AeroxLite.exe --calibrate`; main() intercepts the flag before the single-instance mutex.
"""
import sys, os, json, math, time, random, queue, threading, statistics, argparse, subprocess


DIRS, REPS = 8, 4
NAMES = ["→", "↗", "↑", "↖", "←", "↙", "↓", "↘"]
BG, INK, MUTE, LINE = "#000000", "#ffffff", "#8c8c8c", "#2e2e2e"
FONT = "Segoe UI"
APPDIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AeroxLite")
DEFAULT_OUT = os.path.join(APPDIR, "directional.json")
STATE_PATH = os.path.join(APPDIR, "directional_state.json")
RA_PROFILE = os.path.join(APPDIR, "rawaccel_directional.json")

MIN_MULT, MAX_MULT = 0.85, 1.15   # multiplier limits
SHRINK = 0.5                      # correction damping (0.5 = half)
MOVE_START = 400.0                # counts/s — flick started
STOP_FRAC = 0.15                  # speed dropped to 15% of peak — initial motion finished
STOP_GAP = 0.012                  # no events for 12 ms — hand is still
WRITER_TIMEOUT = 60               # writer.exe shows a window on error — wait until it is closed


# =====================================================================
# Profile computation (pure logic, testable without Windows)
# =====================================================================
def compute_profile(results):
    """results: [{'d': 0..7, 'ratio': float}] -> profile with 8 multipliers."""
    sectors = []
    for d in range(DIRS):
        r = [x["ratio"] for x in results if x["d"] == d]
        sectors.append({"d": d, "ratio": statistics.median(r) if r else 1.0, "n": len(r)})
    raw = [(1.0 / max(0.3, s["ratio"])) ** SHRINK for s in sectors]
    g = math.exp(sum(math.log(v) for v in raw) / len(raw))  # overall sensitivity stays the same
    for s, v in zip(sectors, raw):
        s["mult"] = min(MAX_MULT, max(MIN_MULT, v / g))
    return {
        "version": 2,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "trials": len(results),
        "sectors": [{"angle": s["d"] * 45, "mult": round(s["mult"], 4),
                     "overshoot": round(s["ratio"] - 1, 4), "n": s["n"]} for s in sectors],
    }


def axis_mults(profile):
    """(→, ↑, ←, ↓) — what Raw Accel supports; it interpolates diagonals itself."""
    m = {s["angle"]: s["mult"] for s in profile["sectors"]}
    return m[0], m[90], m[180], m[270]


def _find_key(d, *parts):
    for k in d:
        if any(p in k for p in parts):
            return k
    return None


def build_rawaccel_settings(settings, profile):
    """Copy of Raw Accel's settings.json with directional multipliers in every profile.
    Returns (new dict, None) or (None, error text)."""
    right, up, left, down = axis_mults(profile)
    new = json.loads(json.dumps(settings))
    profs = new.get("profiles")
    if not isinstance(profs, list) or not profs:
        return None, "Raw Accel: settings.json has no profiles"
    for p in profs:
        if not isinstance(p, dict):
            return None, "Raw Accel: settings.json has no profiles"
        k_yx, k_lr, k_ud = _find_key(p, "Y/X"), _find_key(p, "L/R"), _find_key(p, "U/D")
        k_sens = _find_key(p, "Output DPI", "Sensitivity multiplier")
        if not (k_yx and k_lr and k_ud and k_sens):
            return None, "Raw Accel: version 1.6 or newer required (no L/R and U/D)"
        p[k_sens] = round(p[k_sens] * right, 4)            # →
        p[k_yx] = round(p[k_yx] * down / right, 4)         # ↓ relative to →
        p[k_lr] = round(p[k_lr] * left / right, 4)         # ← relative to →
        p[k_ud] = round(p[k_ud] * up / down, 4)            # ↑ relative to ↓
    return new, None


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_profile(path=DEFAULT_OUT):
    p = _read_json(path, {})
    return p if isinstance(p.get("sectors"), list) and len(p["sectors"]) == DIRS else None


def save_profile(profile, path=DEFAULT_OUT):
    _write_json(path, profile)


def profile_text(profile):
    if not profile:
        return "Not calibrated yet"
    r, u, l, d = axis_mults(profile)
    return f"→ {r:.3f}   ↑ {u:.3f}   ← {l:.3f}   ↓ {d:.3f}"


# =====================================================================
# State and Raw Accel
# =====================================================================
def get_state():
    st = {"enabled": False, "rawaccel_dir": None}
    st.update(_read_json(STATE_PATH, {}))
    return st


def _save_state(st):
    _write_json(STATE_PATH, st)


def _search_roots():
    home = os.path.expanduser("~")
    roots = [os.path.join(home, d) for d in ("Downloads", "Desktop", "Documents", "OneDrive", "OneDrive\\Desktop")]
    roots += [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    roots += [os.environ.get("SystemDrive", "C:") + "\\", home]
    seen, out = set(), []
    for r in roots:
        if r and os.path.isdir(r) and os.path.normcase(r) not in seen:
            seen.add(os.path.normcase(r)); out.append(r)
    return out


def find_rawaccel(roots=None, max_depth=3, time_limit=4.0):
    """Find the Raw Accel folder with writer.exe. Prefer folders with settings.json, otherwise any with writer.exe."""
    deadline = time.monotonic() + time_limit
    skip = {"windows", "$recycle.bin", "appdata", "node_modules", ".git", "programdata", "system volume information"}
    best = None
    for root in roots or _search_roots():
        base = root.rstrip("\\/").count(os.sep)
        for cur, dirs, files in os.walk(root):
            if time.monotonic() > deadline:
                return best
            depth = cur.rstrip("\\/").count(os.sep) - base
            names = {f.lower() for f in files}
            if "writer.exe" in names and ("rawaccel" in cur.lower().replace(" ", "").replace("_", "")
                                          or "rawaccel.exe" in names or "grapher.exe" in names):
                if "settings.json" in names:
                    return cur
                best = best or cur
            if depth >= max_depth:
                dirs[:] = []
            else:
                dirs[:] = [d for d in dirs if d.lower() not in skip and not d.startswith(".")]
    return best


def set_rawaccel_dir(path, log=print):
    if not path or not os.path.isfile(os.path.join(path, "writer.exe")):
        log("Raw Accel: writer.exe not found in that folder", True)
        return False
    if not os.path.isfile(os.path.join(path, "settings.json")):
        log("Raw Accel: no settings.json — open Raw Accel and press Apply once", True)
        return False
    st = get_state()
    st["rawaccel_dir"] = path
    _save_state(st)
    log("Raw Accel: folder {0}".format(path))
    return True


def _writer(st, settings_path, log):
    d = st.get("rawaccel_dir")
    exe = os.path.join(d, "writer.exe") if d else None
    if not exe or not os.path.exists(exe):
        log("Raw Accel: choose the Raw Accel folder", True)
        return False
    try:
        r = subprocess.run([exe, settings_path], cwd=d, timeout=WRITER_TIMEOUT, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        log("Raw Accel: writer.exe error: {0}".format(e), True)
        return False
    if r.returncode != 0:
        log("Raw Accel: writer.exe returned code {0}".format(r.returncode), True)
        return False
    return True


def set_enabled(enabled, log=print):
    """Blocking call (writer.exe) — call from a background thread. Returns the resulting state."""
    st = get_state()
    if enabled:
        profile = load_profile()
        if not profile:
            log("Run the calibration first", True)
            return False
        d = st.get("rawaccel_dir")
        if not d:
            log("Raw Accel: choose the Raw Accel folder", True)
            return False
        try:
            with open(os.path.join(d, "settings.json"), encoding="utf-8-sig") as f:
                settings = json.load(f)
        except (OSError, ValueError) as e:
            log("Raw Accel: cannot read settings.json: {0}".format(e), True)
            return False
        new, err = build_rawaccel_settings(settings, profile)
        if err:
            log(err, True)
            return False
        _write_json(RA_PROFILE, new)
        if not _writer(st, RA_PROFILE, log):
            return False
        st["enabled"] = True
        _save_state(st)
        log("Directional sensitivity: ON ({0})".format(profile_text(profile)))
        return True
    restored = True
    if st.get("enabled") and st.get("rawaccel_dir"):
        restored = _writer(st, os.path.join(st["rawaccel_dir"], "settings.json"), log)
        if not restored:
            log("WARNING: could not restore Raw Accel settings — open Raw Accel and press Apply", True)
    st["enabled"] = False
    _save_state(st)
    log("Directional sensitivity: OFF (Raw Accel settings restored)" if restored and st.get("rawaccel_dir")
        else "Directional sensitivity: OFF")
    return False


def reapply(log=print):
    """On Aerox Lite startup: after a reboot the Raw Accel driver loads its own settings — re-apply ours."""
    if get_state()["enabled"]:
        set_enabled(True, log)


# =====================================================================
# Raw Input (Windows only) — separate DLL instances so winput.py argtypes are not affected
# =====================================================================
if os.name == "nt":
    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    WM_INPUT, RID_INPUT, RIDEV_INPUTSINK = 0x00FF, 0x10000003, 0x00000100
    RI_MOUSE_LEFT_BUTTON_DOWN, MOUSE_MOVE_ABSOLUTE = 0x0001, 0x0001
    HWND_MESSAGE = wt.HWND(-3)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
                    ("hbrBackground", wt.HANDLE), ("lpszMenuName", wt.LPCWSTR),
                    ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]

    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [("usUsagePage", wt.USHORT), ("usUsage", wt.USHORT),
                    ("dwFlags", wt.DWORD), ("hwndTarget", wt.HWND)]

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [("dwType", wt.DWORD), ("dwSize", wt.DWORD),
                    ("hDevice", wt.HANDLE), ("wParam", wt.WPARAM)]

    class _BTN(ctypes.Structure):
        _fields_ = [("usButtonFlags", wt.USHORT), ("usButtonData", wt.USHORT)]

    class _BTNU(ctypes.Union):
        _fields_ = [("ulButtons", wt.ULONG), ("s", _BTN)]

    class RAWMOUSE(ctypes.Structure):
        _fields_ = [("usFlags", wt.USHORT), ("u", _BTNU), ("ulRawButtons", wt.ULONG),
                    ("lLastX", wt.LONG), ("lLastY", wt.LONG), ("ulExtraInformation", wt.ULONG)]

    class RAWINPUT(ctypes.Structure):
        _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]

    user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = wt.ATOM
    user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND,
                                       wt.HMENU, wt.HINSTANCE, wt.LPVOID]
    user32.CreateWindowExW.restype = wt.HWND
    user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wt.UINT, wt.UINT]
    user32.GetRawInputData.argtypes = [wt.HANDLE, wt.UINT, ctypes.c_void_p,
                                       ctypes.POINTER(wt.UINT), wt.UINT]
    user32.GetRawInputData.restype = wt.UINT
    user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.ClipCursor.argtypes = [ctypes.c_void_p]
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wt.HINSTANCE

    class RawMouse(threading.Thread):
        """Puts ('m', dx, dy, t) and ('c', t) into the queue. No system speed/acceleration."""

        def __init__(self, q):
            super().__init__(daemon=True)
            self.q, self.error = q, None
            self.ready = threading.Event()

        def run(self):
            try:
                hinst = kernel32.GetModuleHandleW(None)
                self._proc = WNDPROC(self._wndproc)  # keep a reference, otherwise GC
                wc = WNDCLASSEXW()
                wc.cbSize = ctypes.sizeof(wc)
                wc.lpfnWndProc = self._proc
                wc.hInstance = hinst
                wc.lpszClassName = "AeroxLiteCalibRaw"
                if not user32.RegisterClassExW(ctypes.byref(wc)):
                    raise ctypes.WinError(ctypes.get_last_error())
                hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "", 0, 0, 0, 0, 0,
                                              HWND_MESSAGE, None, hinst, None)
                if not hwnd:
                    raise ctypes.WinError(ctypes.get_last_error())
                rid = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, hwnd)
                if not user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid)):
                    raise ctypes.WinError(ctypes.get_last_error())
            except Exception as e:
                self.error = e
                self.ready.set()
                return
            self.ready.set()
            msg = wt.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        def _wndproc(self, hwnd, m, wp, lp):
            if m == WM_INPUT:
                buf = RAWINPUT()
                size = wt.UINT(ctypes.sizeof(buf))
                r = user32.GetRawInputData(lp, RID_INPUT, ctypes.byref(buf), ctypes.byref(size),
                                           ctypes.sizeof(RAWINPUTHEADER))
                if r not in (0, 0xFFFFFFFF) and buf.header.dwType == 0:  # RIM_TYPEMOUSE
                    t = time.perf_counter()
                    mo = buf.mouse
                    if not (mo.usFlags & MOUSE_MOVE_ABSOLUTE) and (mo.lLastX or mo.lLastY):
                        self.q.put(("m", mo.lLastX, mo.lLastY, t))
                    if mo.u.s.usButtonFlags & RI_MOUSE_LEFT_BUTTON_DOWN:
                        self.q.put(("c", t))
            return user32.DefWindowProcW(hwnd, m, wp, lp)


# =====================================================================
# Calibration window (separate process)
# =====================================================================
def _make_app_class():
    import tkinter as tk

    class CalibrationApp(tk.Tk):
        def __init__(self, out, distance):
            super().__init__()
            self.out, self.R = out, distance
            self.title("Aerox Lite — calibration")
            self.configure(bg=BG)
            self.resizable(False, False)
            self.S = int(distance / 0.38)
            self.q = queue.Queue()
            self.raw = None
            self.running = False
            self.trial = None
            self.results, self.pending = [], []
            self.profile = None
            total = DIRS * REPS

            tk.Label(self, text="Directional sensitivity", bg=BG, fg=INK,
                     font=(FONT, 16, "bold")).pack(anchor="w", padx=20, pady=(16, 0))
            self.sub = tk.Label(self, bg=BG, fg=MUTE, font=(FONT, 10), justify="left", wraplength=self.S,
                                text="Flick to the target and click. 8 directions × 4. Esc — abort.")
            self.sub.pack(anchor="w", padx=20, pady=(2, 10))
            self.cv = tk.Canvas(self, width=self.S, height=self.S, bg=BG, highlightthickness=2,
                                highlightbackground=INK, cursor="arrow")
            self.cv.pack(padx=20)
            hud = tk.Frame(self, bg=BG)
            hud.pack(fill="x", padx=20, pady=(6, 0))
            self.prog = tk.Label(hud, text=f"0 / {total}", bg=BG, fg=MUTE, font=(FONT, 10))
            self.prog.pack(side="left")
            self.last = tk.Label(hud, text="—", bg=BG, fg=MUTE, font=(FONT, 10))
            self.last.pack(side="right")
            bar = tk.Frame(self, bg=BG)
            bar.pack(fill="x", padx=20, pady=14)
            self.b_start = self._btn(bar, "Start calibration", self.start, primary=True)
            self.b_save = self._btn(bar, "Save and close", self.save_close)
            self.b_save.config(state="disabled")
            self._btn(bar, "Close", self.destroy).pack(side="right")

            self.bind("<Escape>", lambda e: self.abort("Aborted. Start again."))
            self.bind("<FocusOut>", lambda e: self.running and self.abort(
                "Window lost focus — aborted. Start again."))
            self.protocol("WM_DELETE_WINDOW", self.destroy)
            self.draw_arena()
            self.after(4, self.pump)

        def _btn(self, parent, text, cmd, primary=False):
            b = tk.Button(parent, text=text, command=cmd, font=(FONT, 10, "bold"), relief="flat",
                          bd=0, padx=14, pady=7, cursor="hand2",
                          bg=INK if primary else BG, fg=BG if primary else INK,
                          activebackground=MUTE, activeforeground=BG,
                          highlightthickness=1, highlightbackground=INK)
            b.pack(side="left", padx=(0, 8))
            return b

        # ---------- controls
        def start(self):
            if os.name != "nt":
                self.sub.config(text="Calibration requires Windows (Raw Input).")
                return
            if self.raw is None:
                self.raw = RawMouse(self.q)
                self.raw.start()
                self.raw.ready.wait(2)
                if self.raw.error:
                    self.sub.config(text="Raw Input failed to start: {0}".format(self.raw.error))
                    self.raw = None
                    return
            self.results = []
            self.pending = [i % DIRS for i in range(DIRS * REPS)]
            random.shuffle(self.pending)
            self.running = True
            self.cv.config(cursor="none")
            self.b_start.config(state="disabled")
            self.b_save.config(state="disabled")
            self.focus_force()
            self._clip(True)
            with self.q.mutex:
                self.q.queue.clear()
            self.next_trial()

        def _clip(self, on):
            if os.name != "nt":
                return
            if on:
                x, y = self.cv.winfo_rootx(), self.cv.winfo_rooty()
                r = RECT(x, y, x + self.S, y + self.S)
                user32.ClipCursor(ctypes.byref(r))
                user32.SetCursorPos(x + self.S // 2, y + self.S // 2)
            else:
                user32.ClipCursor(None)

        def abort(self, why):
            if not self.running:
                return
            self.running, self.trial = False, None
            self._clip(False)
            self.cv.config(cursor="arrow")
            self.b_start.config(state="normal")
            self.sub.config(text=why)
            self.prog.config(text=f"0 / {DIRS * REPS}")
            self.draw_arena()

        def next_trial(self):
            if not self.pending:
                self.finish()
                return
            d = self.pending.pop()
            a = d * math.pi / 4
            self.trial = {"d": d, "ux": math.cos(a), "uy": -math.sin(a), "x": 0.0, "y": 0.0,
                          "t0": time.perf_counter(), "s": [], "peak": 0.0, "moving": False,
                          "primary": None, "lt": None}
            self.prog.config(text=f"{DIRS * REPS - len(self.pending)} / {DIRS * REPS}")

        def finish(self):
            self.running, self.trial = False, None
            self._clip(False)
            self.cv.config(cursor="arrow")
            self.profile = compute_profile(self.results)
            self.sub.config(text="Done: {0}".format(profile_text(self.profile)))
            self.b_start.config(state="normal", text="Run again")
            self.b_save.config(state="normal")
            self.draw_result()

        def save_close(self):
            if self.profile:
                save_profile(self.profile, self.out)
            self.destroy()

        def destroy(self):
            self._clip(False)
            super().destroy()

        # ---------- input
        def pump(self):
            changed = False
            try:
                while True:
                    ev = self.q.get_nowait()
                    if not self.running or not self.trial:
                        continue
                    if ev[0] == "m":
                        self.on_move(*ev[1:])
                    else:
                        self.on_click()
                    changed = True
            except queue.Empty:
                pass
            tr_ = self.trial
            if self.running and tr_ and tr_["moving"] and tr_["primary"] is None and tr_["lt"]:
                if time.perf_counter() - tr_["lt"] > STOP_GAP:   # no events — hand is still
                    tr_["primary"] = self._proj(tr_)
            if changed and self.running:
                self.draw_arena()
            self.after(4, self.pump)

        def _proj(self, t):
            return (t["x"] * t["ux"] + t["y"] * t["uy"]) / self.R

        def on_move(self, dx, dy, t):
            tr_ = self.trial
            tr_["x"] += dx
            tr_["y"] += dy
            tr_["lt"] = t
            s = tr_["s"]
            s.append((t, tr_["x"], tr_["y"]))
            j = len(s) - 1
            while j > 0 and t - s[j - 1][0] < 0.010:
                j -= 1
            if j > 0:
                t0, x0, y0 = s[j - 1]
                v = math.hypot(tr_["x"] - x0, tr_["y"] - y0) / max(t - t0, 0.001)
                tr_["peak"] = max(tr_["peak"], v)
                if tr_["peak"] > MOVE_START:
                    tr_["moving"] = True
                if tr_["moving"] and tr_["primary"] is None and v < tr_["peak"] * STOP_FRAC:
                    tr_["primary"] = self._proj(tr_)

        def on_click(self):
            tr_ = self.trial
            ratio = tr_["primary"] if tr_["primary"] is not None else self._proj(tr_)
            ms = round((time.perf_counter() - tr_["t0"]) * 1000)
            if tr_["moving"]:
                self.results.append({"d": tr_["d"], "ratio": ratio, "ms": ms})
                self.last.config(text="{0}  {1:+.0f}%  {2} ms".format(NAMES[tr_["d"]], (ratio - 1) * 100, ms))
            else:
                self.pending.insert(0, tr_["d"])  # click without a flick — retry later
            self.next_trial()

        # ---------- rendering
        def draw_arena(self):
            c, S, R = self.cv, self.S, self.R
            cx = cy = S / 2
            c.delete("all")
            c.create_oval(cx - R, cy - R, cx + R, cy + R, outline=LINE, dash=(4, 6))
            for d in range(DIRS):
                a = d * math.pi / 4
                c.create_line(cx, cy, cx + math.cos(a) * R * 1.15, cy - math.sin(a) * R * 1.15, fill=LINE)
            c.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=MUTE, outline="")
            t = self.trial
            if self.running and t:
                tx, ty = cx + t["ux"] * R, cy + t["uy"] * R
                tr_r = max(10, S * 0.035)
                c.create_oval(tx - tr_r, ty - tr_r, tx + tr_r, ty + tr_r, outline=INK, width=3)
                c.create_oval(tx - 3, ty - 3, tx + 3, ty + 3, fill=INK, outline="")
                px, py = cx + t["x"], cy + t["y"]
                c.create_line(px - 8, py, px + 9, py, fill=INK, width=2)
                c.create_line(px, py - 8, px, py + 9, fill=INK, width=2)

        def draw_result(self):
            c, S = self.cv, self.S
            cx = cy = S / 2
            K, k = S * 0.3, S * 1.3
            rad = lambda m: K + (m - 1) * k
            c.delete("all")
            for m in (MIN_MULT, 1.0, MAX_MULT):
                r = rad(m)
                c.create_oval(cx - r, cy - r, cx + r, cy + r,
                              outline=MUTE if m == 1.0 else LINE, dash=(4, 4) if m == 1.0 else ())
            pts = []
            for s in self.profile["sectors"]:
                a = math.radians(s["angle"])
                r = rad(s["mult"])
                pts += [cx + math.cos(a) * r, cy - math.sin(a) * r]
                lx, ly = cx + math.cos(a) * S * 0.46, cy - math.sin(a) * S * 0.46
                c.create_text(lx, ly, text=f"{NAMES[s['angle'] // 45]}\n{s['mult']:.3f}",
                              fill=MUTE, font=(FONT, 9), justify="center")
            c.create_polygon(*pts, outline=INK, fill="", width=3)
            for i in range(0, len(pts), 2):
                c.create_rectangle(pts[i] - 3, pts[i + 1] - 3, pts[i] + 3, pts[i + 1] + 3, fill=INK, outline="")

    return CalibrationApp


def cli(argv=None):
    """Calibration process entry point (`AeroxLite.exe --calibrate` or `python calibration.py`)."""
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--distance", type=int, default=240, help="distance to target, counts")
    a, _ = ap.parse_known_args(argv)
    _make_app_class()(a.out, a.distance).mainloop()


def open_calibration(root, on_done=None, log=print, out=DEFAULT_OUT):
    """From Aerox Lite: start calibration in a separate process, then call on_done(profile)."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--calibrate"]
    else:
        exe = sys.executable
        if exe.lower().endswith("python.exe"):
            w = exe[:-len("python.exe")] + "pythonw.exe"
            if os.path.exists(w):
                exe = w
        cmd = [exe, os.path.abspath(__file__)]
    before = os.path.getmtime(out) if os.path.exists(out) else 0
    try:
        proc = subprocess.Popen(cmd + ["--out", out])
    except OSError as e:
        log("Calibration failed to start: {0}".format(e), True)
        return None
    log("Calibration: window opened")

    def poll():
        if proc.poll() is None:
            root.after(300, poll)
            return
        prof = load_profile(out) if os.path.exists(out) and os.path.getmtime(out) > before else None
        if prof:
            log("Calibration: saved ({0})".format(profile_text(prof)))
            if on_done:
                on_done(prof)
        else:
            log("Calibration: closed without saving")

    root.after(300, poll)
    return proc


if __name__ == "__main__":
    cli()
