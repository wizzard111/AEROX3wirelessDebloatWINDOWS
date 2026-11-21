"""Other SteelSeries mice (generic.py): detection, settings, what is sent, config and the app path."""
from pathlib import Path
import struct
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.modules.setdefault('hid', types.SimpleNamespace(enumerate=lambda *_: []))
sys.modules.setdefault('hidraw', sys.modules['hid'])
sys.modules.setdefault('pystray', types.SimpleNamespace())
import aerox_lite as app
import generic

try:
    from rivalcfg import usbhid, mouse as rc_mouse
except ImportError:  # pragma: no cover
    usbhid = None

RIVAL3, AEROX5W = 0x1824, 0x1852


class Dev:
    """Records what is written, in the format of rivalcfg's FakeDevice (type byte + data)."""
    def __init__(self, fail=False, reply=b""):
        self.data, self.fail, self.reply, self.closed = bytearray(), fail, reply, False
    def open_path(self, path):
        if self.fail: raise OSError("permission denied")
    def write(self, b): self.data += struct.pack("B", 2) + bytes(b); return len(b)
    def send_feature_report(self, b): self.data += struct.pack("B", 3) + bytes(b); return len(b)
    def read(self, n, timeout_ms=0): return list(self.reply)
    def close(self): self.closed = True


def fake_hid(entries, fail=False, reply=b""):
    devs = []
    def device():
        d = Dev(fail, reply); devs.append(d); return d
    return types.SimpleNamespace(enumerate=lambda vid=0, pid=0: [e for e in entries if not pid or e["product_id"] == pid],
                                 device=device, devs=devs)


def entry(pid, iface, usage_page=0xFFC0):
    return {"product_id": pid, "interface_number": iface, "usage_page": usage_page, "path": b"/dev/x%d" % iface}


def expected(pid, name, value):
    d = usbhid.FakeDevice()
    m = rc_mouse.Mouse(d, generic.profiles()[(0x1038, pid)], generic._NoStore(), command_delay=0.001)
    getattr(m, "set_" + name)(value)
    return d.bytes.getvalue()


@unittest.skipIf(usbhid is None, "rivalcfg not installed")
class GenericTests(unittest.TestCase):
    def test_every_supported_model_has_settings(self):
        profs = generic.profiles()
        self.assertGreater(len(profs), 50)
        for prof in profs.values():
            sp = generic.specs(prof)
            self.assertTrue(sp, prof["name"])
            for s in sp:
                self.assertIn(s["kind"], ("choice", "range", "dpi", "color", "reactive", "action", "buttons"))
                self.assertIn(s["group"], generic.GROUPS)
                if s["kind"] == "range": self.assertEqual(len(s["range"]), 3)
            buttons = [s for s in sp if s["kind"] == "buttons"]
            self.assertEqual(bool(buttons), "buttons_mapping" in prof["settings"], prof["name"])

    def test_detects_model_on_its_interface_only(self):
        h = fake_hid([entry(RIVAL3, 0), entry(RIVAL3, 3), entry(0x1838, 3)])
        m = generic.GenericMouse(h, app.KNOWN_PIDS)
        self.assertTrue(m.open())
        self.assertEqual((m.pid, m.product, m.key), (RIVAL3, "Rival 3", "1038:1824"))
        self.assertEqual(len(h.devs), 1)
        self.assertFalse(m.has_battery)

    def test_aerox3_is_left_to_the_native_path(self):
        m = generic.GenericMouse(fake_hid([entry(0x1838, 3), entry(0x183A, 3)]), app.KNOWN_PIDS)
        self.assertFalse(m.open())
        self.assertEqual(m.diag, "")

    def test_open_failure_is_explained(self):
        m = generic.GenericMouse(fake_hid([entry(RIVAL3, 3)], fail=True), app.KNOWN_PIDS)
        self.assertFalse(m.open())
        self.assertIn("Rival 3", m.diag); self.assertIn("permission denied", m.diag)

    def test_settings_sent_like_rivalcfg(self):
        h = fake_hid([entry(RIVAL3, 3)])
        m = generic.GenericMouse(h, app.KNOWN_PIDS); m.open()
        values = {"sensitivity": [800, 1600], "polling_rate": 500, "z1_color": "#ff8800", "light_effect": "breath"}
        self.assertEqual(m.apply(values, ["sensitivity"]), [])
        self.assertEqual(bytes(h.devs[0].data), expected(RIVAL3, "sensitivity", [800, 1600]))
        for name in ("polling_rate", "z1_color", "light_effect"):
            h.devs[0].data.clear()
            self.assertEqual(m.apply(values, [name]), [])
            self.assertEqual(bytes(h.devs[0].data), expected(RIVAL3, name, values[name]), name)

    def test_invalid_values_are_refused_not_sent(self):
        h = fake_hid([entry(RIVAL3, 3)])
        m = generic.GenericMouse(h, app.KNOWN_PIDS); m.open()
        refused = m.apply({"polling_rate": 333, "z1_color": "red!!", "nope": 1})
        self.assertEqual(sorted(n for n, _ in refused), ["polling_rate", "z1_color"])
        self.assertEqual(bytes(h.devs[0].data), b"")

    def test_values_are_clamped(self):
        spec = {s["name"]: s for s in generic.specs(generic.profiles()[(0x1038, RIVAL3)])}["sensitivity"]
        self.assertEqual(generic.parse_dpi("150, 830, 99999", spec), [200, 800, 8500])
        self.assertEqual(generic.parse_dpi("1,2,3,4,5,6,7", spec), [200] * spec["max"])
        self.assertIsNone(generic.parse_dpi("abc", spec))
        timer = {s["name"]: s for s in generic.specs(generic.profiles()[(0x1038, AEROX5W)])}["sleep_timer"]
        self.assertEqual(generic.valid_value(timer, 99), timer["range"][1])
        self.assertIsNone(generic.valid_value(timer, True))

    def test_wired_mouse_disconnect_is_noticed(self):
        entries = [entry(RIVAL3, 3)]
        h = fake_hid(entries)
        m = generic.GenericMouse(h, app.KNOWN_PIDS); m.open()
        self.assertEqual(m.battery(), (None, None)); self.assertTrue(m.connected())
        entries.clear()
        self.assertEqual(m.battery(), (None, None)); self.assertFalse(m.connected())

    def test_usb_error_closes_device(self):
        h = fake_hid([entry(RIVAL3, 3)])
        m = generic.GenericMouse(h, app.KNOWN_PIDS); m.open()
        def broken(b): raise OSError("gone")
        h.devs[0].write = broken
        with self.assertRaises(IOError): m.apply({"polling_rate": 500})
        self.assertFalse(m.connected())

    def test_color_swatch(self):
        self.assertEqual(generic.color_hex("#FF0000"), "#ff0000")
        self.assertEqual(generic.color_hex("rgbgradient(duration=1000; colors=0%: #ff00e1, 50%: #00ff00)"), "#ff00e1")
        self.assertEqual(generic.color_hex(None, "#123456"), "#123456")


@unittest.skipIf(usbhid is None, "rivalcfg not installed")
class ButtonsAndArtTests(unittest.TestCase):
    def spec(self, pid):
        return next(s for s in generic.specs(generic.profiles()[(0x1038, pid)]) if s["kind"] == "buttons")

    def test_bindings_sent_like_rivalcfg(self):
        h = fake_hid([entry(RIVAL3, 3)])
        m = generic.GenericMouse(h, app.KNOWN_PIDS); m.open()
        binds = {"Button4": "key:A", "Button5": "media:VolumeUp", "Button6": "macro:2", "Button2": "button1",
                 "Button3": "disabled", "Button1": "key:Esc"}
        self.assertEqual(m.apply({"buttons_mapping": binds}), [])
        want = {"buttons": {"Button1": "Esc", "Button2": "button1", "Button3": "disabled", "Button4": "A",
                            "Button5": "VolumeUp", "Button6": "F15", "ScrollUp": "default", "ScrollDown": "default"}}
        self.assertEqual(bytes(h.devs[0].data), expected(RIVAL3, "buttons_mapping", want))

    def test_unknown_binding_falls_back_to_default(self):
        s = self.spec(RIVAL3)
        got = generic.valid_value(s, {"Button4": "key:NoSuchKey!", "Button9": "key:A", "Button5": "macro:99"})
        self.assertEqual(got["buttons"]["Button4"], "default")
        self.assertEqual(got["buttons"]["Button5"], "default")
        self.assertNotIn("Button9", got["buttons"])

    def test_button_list_order_and_labels(self):
        names = [(n, l) for n, l, _ in self.spec(0x170E)["buttons"]]   # Rival 500: 13 buttons + tilt
        self.assertEqual(names[0], ("Button1", "Left button"))
        self.assertEqual([n for n, _ in names][:13], ["Button%d" % i for i in range(1, 14)])
        self.assertEqual(names[-2:], [("TiltLeft", "Wheel tilt left"), ("TiltRight", "Wheel tilt right")])

    def test_every_model_has_a_picture(self):
        import model_art
        for prof in generic.profiles().values():
            name = generic.short_name(prof)
            slug = generic.art_slug(name)
            if name.startswith("Aerox 3"): self.assertIsNone(slug); continue
            self.assertIn(slug, model_art.ART, name)
        self.assertEqual(generic.art_slug("Rival 3 Wireless Gen 2"), "rival-3")
        self.assertEqual(generic.art_slug("Rival 310 PUBG Edition"), "rival-310")
        self.assertEqual(generic.art_slug("Rival"), "rival-300")
        self.assertEqual(generic.art_slug("Sensei [RAW] Diablo III Edition"), "sensei-raw")

    def test_pictures_decode_with_zones(self):
        import base64, io, model_art
        from PIL import Image
        for slug, data in model_art.ART.items():
            img = Image.open(io.BytesIO(base64.b64decode("".join(data))))
            self.assertEqual(img.size, model_art.SIZE, slug)
            zone_ids = {i for i, n in enumerate(img.split()[2].histogram()) if n}
            self.assertTrue(zone_ids <= set(range(len(model_art.ZONES))), slug)

    def test_zone_plan_for_side_strips(self):
        import generic_ui
        from PIL import Image
        colors = [s for s in generic.specs(generic.profiles()[(0x1038, 0x1724)]) if s["kind"] == "color"]  # Rival 600
        full = Image.new("L", (10, 30), 255)
        plan = generic_ui.zone_plan(colors, {"wheel": full, "logo": full, "left": full, "right": full})
        tags = sorted(t for _, _, t in plan)
        self.assertEqual(tags, ["L1", "L2", "L3", "LG", "R1", "R2", "R3", "W"])
        self.assertTrue(all(m is not None for _, m, _ in plan))


class ConfigTests(unittest.TestCase):
    def norm(self, user):
        return app.normalize(app.DEFAULT, user, app.KEYS, app.SPECIAL, app.MEDIA, dict(app.MODES), app.MAX_MACROS)

    def test_devices_kept_and_cleaned(self):
        c = self.norm({"devices": {"1038:1824": {"sensitivity": [800, 1600], "polling_rate": 500, "z1_color": "#ff0000",
                                                 "bad": {"x": 1}, "flag": True},
                                   "nonsense": {"a": 1}, "1038:1852": "x"}})
        self.assertEqual(c["devices"], {"1038:1824": {"sensitivity": [800, 1600], "polling_rate": 500, "z1_color": "#ff0000"}})
        self.assertEqual(self.norm({})["devices"], {})
        self.assertEqual(self.norm({"devices": [1]})["devices"], {})

    def test_button_mapping_kept(self):
        c = self.norm({"devices": {"1038:1824": {"buttons_mapping": {"Button4": "key:A", "Button6": "macro:1"},
                                                 "junk": {"a": 1}}}})
        self.assertEqual(c["devices"]["1038:1824"], {"buttons_mapping": {"Button4": "key:A", "Button6": "macro:1"}})


@unittest.skipIf(usbhid is None, "rivalcfg not installed")
class AppPathTests(unittest.TestCase):
    def run_apply(self, cats, save, stored):
        h = fake_hid([entry(RIVAL3, 3)])
        m = generic.GenericMouse(h, app.KNOWN_PIDS); m.open()
        logs, posted = [], []
        fake = types.SimpleNamespace(log=lambda t, w=False: logs.append(t), post=posted.append)
        app.App._apply_generic(fake, m, cats, save, {"devices": {"1038:1824": stored}})
        return bytes(h.devs[0].data), logs

    def test_changed_setting_only(self):
        data, logs = self.run_apply({"g:polling_rate"}, False, {"polling_rate": 500, "z1_color": "#ff0000"})
        self.assertEqual(data, expected(RIVAL3, "polling_rate", 500))
        self.assertEqual(logs, ["Applied: Polling rate"])

    def test_connect_applies_everything_stored_and_save_writes_memory(self):
        data, logs = self.run_apply({"dpi", "poll", "power", "buttons", "light"}, True, {"polling_rate": 500})
        self.assertTrue(data.startswith(expected(RIVAL3, "polling_rate", 500)))
        self.assertGreater(len(data), len(expected(RIVAL3, "polling_rate", 500)))  # + save command
        self.assertEqual(logs, ["Saved to mouse: Polling rate"])

    def test_nothing_stored_sends_nothing(self):
        data, logs = self.run_apply({"dpi", "poll", "power", "buttons", "light"}, False, {})
        self.assertEqual((data, logs), (b"", []))


class OptimisationTests(unittest.TestCase):
    def test_no_other_mouse_no_rivalcfg_work(self):
        m = generic.GenericMouse(types.SimpleNamespace(enumerate=lambda *a: 1 / 0), app.KNOWN_PIDS)
        self.assertFalse(m.open([{"product_id": 0x1838, "interface_number": 3}]))   # only an Aerox 3: skipped
        self.assertFalse(m.open([]))
        self.assertEqual(m.diag, "")

    def test_capped_log_rotates(self):
        import logging, os, tempfile
        d = tempfile.mkdtemp(); path = os.path.join(d, "log.txt")
        h = app._CappedLog(path, 200); h.setFormatter(logging.Formatter("%(message)s"))
        log = logging.getLogger("captest"); log.propagate = False; log.addHandler(h)
        for i in range(40): log.warning("line %d %s", i, "x" * 20)
        h.close(); log.removeHandler(h)
        self.assertTrue(os.path.exists(path + ".1"))
        self.assertLess(os.path.getsize(path), 400)

    def test_atomic_save_leaves_no_temp_file(self):
        import json, os, tempfile
        from config_store import atomic_save
        d = tempfile.mkdtemp(); path = os.path.join(d, "config.json")
        atomic_save(path, {"a": 1}); atomic_save(path, {"a": 2})
        self.assertEqual(json.load(open(path)), {"a": 2})
        self.assertEqual(os.listdir(d), ["config.json"])

    def test_unplugged_mouse_noticed_on_hotplug(self):
        fake = types.SimpleNamespace(mouse=types.SimpleNamespace(pid=0x1824))
        saved = app.hid
        try:
            app.hid = types.SimpleNamespace(enumerate=lambda vid, pid: [])
            self.assertFalse(app.App._present(fake))
            app.hid = types.SimpleNamespace(enumerate=lambda vid, pid: [{"product_id": 0x1824}])
            self.assertTrue(app.App._present(fake))
        finally:
            app.hid = saved


if __name__ == "__main__":
    unittest.main()
