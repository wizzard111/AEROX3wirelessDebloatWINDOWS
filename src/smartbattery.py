"""
smartbattery.py — smart battery for Aerox Lite.

1) Forecast: hours remaining (based on your mouse's actual discharge rate).
2) Saver: below 25% and not charging -> "battery low" notification + on_low(True):
   Aerox Lite temporarily sets 500 Hz and turns lighting off WITHOUT touching your config.
   Charging or >= 30% -> on_low(False) (+ a notification if it was put on charge).

Does not poll the mouse itself: the level comes from the existing _monitor loop (every 30 s).
Disabled = update() does nothing.
"""
import os, json, time


APPDIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AeroxLite")
CFG_PATH = os.path.join(APPDIR, "smartbattery.json")
LOG_PATH = os.path.join(APPDIR, "battery_log.json")

DEFAULTS = {
    "enabled": True,
    "low_below": 25,       # % — below this, enable saver and notify
    "restore_at": 30,      # % — restore (hysteresis)
    "low_active": False,   # internal: saver was active (survives restarts)
    "learned_rate": None,  # learned discharge rate, %/h (survives charging and restarts)
}
SEGMENT_GAP = 10 * 60      # data gap > 10 min (PC off) = new segment
WINDOW = 6 * 3600          # forecast from the last 6 hours of discharge
MAX_SAMPLES = 3000
DEFAULT_RATE = 100 / 80    # %/h: Aerox 3 Wireless — up to ~80 h at 2.4 GHz (spec), until real data is available


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _write(path, data):
    os.makedirs(APPDIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


class SmartBattery:
    def __init__(self, on_low, log=print, notify=None, clock=time.time):
        self.on_low = on_low
        self.log = lambda text, warn=False: log(text, warn)
        self.notify = notify or (lambda text: None)
        self.clock = clock
        self.cfg = dict(DEFAULTS)
        self.cfg.update({k: v for k, v in _read(CFG_PATH, {}).items() if k in DEFAULTS})
        self.samples = [p for p in _read(LOG_PATH, []) if isinstance(p, list) and len(p) == 2]
        self.samples = self.samples[-MAX_SAMPLES:]
        self.level, self.charging = None, False
        self._last_log_save = 0

    @property
    def enabled(self):
        return self.cfg["enabled"] is True

    @property
    def low_active(self):
        return self.cfg["low_active"] is True

    def save(self):
        _write(CFG_PATH, self.cfg)

    def flush(self):
        self._save_samples(force=True)

    # ---------- main entry (_monitor thread)
    def update(self, level, charging):
        if not self.enabled or level is None:
            return
        now = self.clock()
        if charging:
            if not self.charging and self.samples:
                self.samples.clear()               # after charging, discharge is measured from scratch
                self._save_samples(force=True)
        elif not self.samples or self.samples[-1][1] != level or now - self.samples[-1][0] > SEGMENT_GAP / 2:
            changed = bool(self.samples) and self.samples[-1][1] != level
            self.samples.append([round(now), int(level)])
            del self.samples[:-MAX_SAMPLES]
            self._save_samples(force=changed)
            if changed: self._update_learned()
        self.level, self.charging = level, bool(charging)
        self._check_low()

    def _save_samples(self, force=False):
        if force or self.clock() - self._last_log_save > 300:   # write to disk at most every 5 min
            try:
                _write(LOG_PATH, self.samples)
                self._last_log_save = self.clock()
            except OSError:
                pass

    # ---------- saver
    def _check_low(self):
        c = self.cfg
        if not self.low_active and not self.charging and self.level < c["low_below"]:
            c["low_active"] = True
            self.save()
            self.on_low(True)
            self.log("Battery {0}%: saver — 500 Hz, lighting off.".format(self.level))
            fc = self.forecast_text()
            self.notify("Mouse battery low: {0}%. Battery saver is on (500 Hz, lighting off).".format(self.level)
                        + (" " + "About {0} left.".format(fc) if fc else ""))
        elif self.low_active and (self.charging or self.level >= c["restore_at"]):
            self._exit_low()

    def _exit_low(self):
        self.cfg["low_active"] = False
        self.save()
        self.on_low(False)
        self.log("Battery: saver off, settings restored")
        if self.charging:
            self.notify("Mouse is charging — battery saver is off.")

    # ---------- forecast
    # The mouse reports battery in 5% steps but drains about 1–1.5% per hour, so a new step
    # arrives only every few hours. Therefore: show the spec-based estimate immediately
    # (~80 h at 2.4 GHz), learn the rate only between the MOMENTS a step changes (otherwise
    # rounding lies), and remember it across charges.
    def _learn(self):
        """Rate from level-change moments within continuous discharge segments, %/h."""
        hours = drop = 0.0
        first = None
        pts = self.samples
        for i in range(1, len(pts)):
            (t0, l0), (t1, l1) = pts[i - 1], pts[i]
            if t1 - t0 > SEGMENT_GAP or l1 > l0:   # gap (PC off) or recharge — new segment
                first = None
                continue
            if l1 < l0:                            # step change moment
                if first is not None:
                    hours += (t1 - first[0]) / 3600
                    drop += first[1] - l1
                first = (t1, l1)
        return (drop / hours) if hours >= 0.5 and drop > 0 else None

    def _update_learned(self):
        r = self._learn()
        if r and 0.05 <= r <= 50:
            old = self.cfg.get("learned_rate")
            self.cfg["learned_rate"] = round(r if not old else old * 0.5 + r * 0.5, 4)
            try: self.save()
            except OSError: pass

    def rate(self):
        """(%/hour, learned?). Without data — the spec estimate."""
        r = self.cfg.get("learned_rate")
        if isinstance(r, (int, float)) and r > 0:
            return r, True
        return DEFAULT_RATE, False

    def hours_left(self):
        if self.level is None or self.charging:
            return None
        r, _ = self.rate()
        return self.level / r

    def forecast_text(self):
        if not self.enabled:
            return ""
        if self.charging:
            return "charging"
        h = self.hours_left()
        if h is None:
            return ""
        _, learned = self.rate()
        if h < 1:
            txt = "≈ {0} min".format(max(1, round(h * 60)))
        else:
            txt = "≈ {0} h".format(f"{h:.0f}" if h >= 10 else f"{h:.1f}".replace(".", ","))
        return txt if learned else txt + " (estimate)"

    # ---------- module on / off
    def set_enabled(self, on):
        if not on and self.low_active:
            self._exit_low()
        self.cfg["enabled"] = bool(on)
        self.save()
        self.log("Smart battery: ON" if on else "Smart battery: OFF")
