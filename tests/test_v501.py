"""Tests for 5.0.1: UI scale setting and HID diagnostics."""
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.modules.setdefault('hid', types.SimpleNamespace(enumerate=lambda *_: []))
sys.modules.setdefault('hidraw', sys.modules['hid'])
sys.modules.setdefault('pystray', types.SimpleNamespace())
import aerox_lite as app


def normalize(user):
    return app.normalize(app.DEFAULT, user, app.KEYS, app.SPECIAL, app.MEDIA, dict(app.MODES), app.MAX_MACROS)


class UiScaleTests(unittest.TestCase):
    def test_default_and_range(self):
        self.assertEqual(normalize({})['ui_scale'], 1.0)
        self.assertEqual(normalize({'ui_scale': 1.25})['ui_scale'], 1.25)
        self.assertEqual(normalize({'ui_scale': 9})['ui_scale'], 2.0)
        self.assertEqual(normalize({'ui_scale': 0.1})['ui_scale'], 0.5)
        for bad in ('big', True, None, float('nan'), [1]):
            self.assertEqual(normalize({'ui_scale': bad})['ui_scale'], 1.0)

    def test_scale_steps_include_default(self):
        self.assertIn(1.0, app.UI_SCALES)
        self.assertEqual(app.UI_SCALES, tuple(sorted(app.UI_SCALES)))
        self.assertTrue(all(name in app.FONT_SPECS for name in (app.F, app.FB, app.FS, app.FT, app.FU, app.FH, app.FM, app.FM2)))


class HidDiagnosisTests(unittest.TestCase):
    def test_nothing_visible(self):
        self.assertIn('no SteelSeries device', app.hid_diagnosis([], [], []))

    def test_wrong_interfaces_only(self):
        found = [{'product_id': 0x1838, 'interface_number': 0}, {'product_id': 0x1838, 'interface_number': 1}]
        msg = app.hid_diagnosis(found, [], [])
        self.assertIn('none is a supported mouse', msg)
        self.assertIn('PID 0x1838 interface 1', msg)

    def test_open_failure_reports_path_and_permission(self):
        with tempfile.NamedTemporaryFile(delete=False) as f: path = f.name
        try:
            os.chmod(path, 0o400)
            d = {'product_id': 0x1838, 'interface_number': 3, 'path': path.encode()}
            msg = app.hid_diagnosis([d], [(1, d, True)], [(d, OSError('open failed'))])
            self.assertIn(path, msg)
            self.assertIn('open failed', msg)
            if os.name == 'posix' and os.geteuid() != 0:
                self.assertIn('no permission', msg)
        finally:
            os.chmod(path, 0o600); os.unlink(path)

    def test_mouse_records_diagnosis(self):
        fake = types.SimpleNamespace(enumerate=lambda *_: [{'product_id': 0x1838, 'interface_number': 0, 'path': b'x'}])
        old = app.hid
        app.hid = fake
        try:
            m = app.Mouse()
            self.assertFalse(m.open())
            self.assertIn('none is a supported mouse', m.diag)
        finally:
            app.hid = old


class DisplayFactorTests(unittest.TestCase):
    def fake_root(self, scaling):
        return types.SimpleNamespace(tk=types.SimpleNamespace(call=lambda *a: scaling))

    def test_windows_dpi(self):
        self.assertEqual(app.display_factors(self.fake_root(96 / 72)), (1.0, 1.0))
        self.assertEqual(app.display_factors(self.fake_root(1.5 * 96 / 72)), (1.0, 1.5))


if __name__ == '__main__':
    unittest.main()
