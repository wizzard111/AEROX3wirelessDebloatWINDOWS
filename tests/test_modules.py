"""Tests for V5 modules: calibration math, Raw Accel profile, smart battery, rclick logic, helpers."""
import copy
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.modules.setdefault('hid', types.SimpleNamespace(enumerate=lambda *_: []))
sys.modules.setdefault('pystray', types.SimpleNamespace())
import calibration
import helpers
import rclick
import smartbattery
import aerox_lite as app


def profile_from(ratios):
    return calibration.compute_profile([{'d': d, 'ratio': r} for d, r in enumerate(ratios) for _ in range(4)])


RA_SETTINGS = {
    "version": "1.7.0",
    "profiles": [{
        "name": "default",
        "Output DPI": 1000.0,
        "Y/X output DPI ratio (vertical sens multiplier)": 1.0,
        "L/R output DPI ratio (left sens multiplier)": 1.0,
        "U/D output DPI ratio (up sens multiplier)": 1.0,
    }],
    "devices": [],
}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.patches = [patch.object(m, 'APPDIR', d) for m in (calibration, helpers, rclick, smartbattery)]
        self.patches += [
            patch.object(calibration, 'DEFAULT_OUT', os.path.join(d, 'directional.json')),
            patch.object(calibration, 'STATE_PATH', os.path.join(d, 'directional_state.json')),
            patch.object(calibration, 'RA_PROFILE', os.path.join(d, 'rawaccel_directional.json')),
            patch.object(helpers, 'STATE_PATH', os.path.join(d, 'helpers.json')),
            patch.object(rclick, 'CFG_PATH', os.path.join(d, 'rclick.json')),
            patch.object(smartbattery, 'CFG_PATH', os.path.join(d, 'smartbattery.json')),
            patch.object(smartbattery, 'LOG_PATH', os.path.join(d, 'battery_log.json')),
        ]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in self.patches: p.stop()
        self.tmp.cleanup()


class CalibrationTests(Tmp):
    def test_profile_keeps_overall_sensitivity_and_clamps(self):
        p = profile_from([1.04, 1.09, 0.97, 0.95, 0.98, 1.06, 1.03, 0.93])
        mults = [s['mult'] for s in p['sectors']]
        prod = 1.0
        for m in mults: prod *= m
        self.assertAlmostEqual(prod ** (1 / 8), 1.0, places=3)
        extreme = profile_from([3.0, 0.3, 1, 1, 1, 1, 1, 1])
        self.assertTrue(all(0.85 <= s['mult'] <= 1.15 for s in extreme['sectors']))

    def test_overshoot_lowers_multiplier(self):
        p = profile_from([1.10, 1, 1, 1, 0.90, 1, 1, 1])  # overshoot right, undershoot left
        m = {s['angle']: s['mult'] for s in p['sectors']}
        self.assertLess(m[0], 1.0)
        self.assertGreater(m[180], 1.0)

    def test_rawaccel_settings_four_directions(self):
        p = profile_from([1.10, 1, 0.95, 1, 0.90, 1, 1.05, 1])
        right, up, left, down = calibration.axis_mults(p)
        new, err = calibration.build_rawaccel_settings(RA_SETTINGS, p)
        self.assertIsNone(err)
        q = new['profiles'][0]
        dpi = q['Output DPI']
        self.assertAlmostEqual(dpi / 1000, right, places=3)                                            # →
        self.assertAlmostEqual(dpi / 1000 * q['L/R output DPI ratio (left sens multiplier)'], left, places=3)   # ←
        yx = q['Y/X output DPI ratio (vertical sens multiplier)']
        self.assertAlmostEqual(dpi / 1000 * yx, down, places=3)                                        # ↓
        self.assertAlmostEqual(dpi / 1000 * yx * q['U/D output DPI ratio (up sens multiplier)'], up, places=3)  # ↑
        self.assertEqual(RA_SETTINGS['profiles'][0]['Output DPI'], 1000.0)  # original untouched

    def test_rawaccel_old_version_rejected(self):
        old = {"profiles": [{"Sensitivity multiplier": 1.0, "Y/X sensitivity ratio (vertical sens multiplier)": 1.0}]}
        new, err = calibration.build_rawaccel_settings(old, profile_from([1] * 8))
        self.assertIsNone(new); self.assertIn('1.6', err)

    def test_enable_requires_calibration_and_folder(self):
        logs = []
        self.assertFalse(calibration.set_enabled(True, lambda t, w=False: logs.append(t)))
        calibration.save_profile(profile_from([1] * 8))
        self.assertFalse(calibration.set_enabled(True, lambda t, w=False: logs.append(t)))
        self.assertFalse(calibration.get_state()['enabled'])
        self.assertFalse(helpers.module_on('directional'))

    def test_enable_and_disable_via_writer(self):
        ra = os.path.join(self.tmp.name, 'ra'); os.makedirs(ra)
        for f in ('writer.exe', 'settings.json'):
            Path(ra, f).write_text(json.dumps(RA_SETTINGS), encoding='utf-8')
        calibration.save_profile(profile_from([1.1, 1, 1, 1, 0.9, 1, 1, 1]))
        self.assertTrue(calibration.set_rawaccel_dir(ra, lambda *a: None))
        calls = []
        ok = types.SimpleNamespace(returncode=0)
        with patch.object(calibration.subprocess, 'run', lambda cmd, **kw: calls.append(cmd) or ok):
            self.assertTrue(calibration.set_enabled(True, lambda *a: None))
            self.assertTrue(helpers.module_on('directional'))
            self.assertEqual(calls[-1][1], calibration.RA_PROFILE)
            calibration.set_enabled(False, lambda *a: None)
            self.assertEqual(calls[-1][1], os.path.join(ra, 'settings.json'))  # user settings restored
        self.assertFalse(helpers.module_on('directional'))
        self.assertEqual(json.loads(Path(ra, 'settings.json').read_text(encoding='utf-8')), RA_SETTINGS)


class BatteryTests(Tmp):
    def make(self):
        self.now = getattr(self, 'now', [1_000_000.0])
        self.events = getattr(self, 'events', [])
        self.notes = getattr(self, 'notes', [])
        return smartbattery.SmartBattery(self.events.append, lambda *a: None, self.notes.append, clock=lambda: self.now[0])

    def test_forecast_and_hysteresis(self):
        sb = self.make()
        level = 40
        for i in range(600):                      # 1 sample/min, ~3 %/h
            self.now[0] = 1_000_000 + i * 60
            level = 40 - i // 20
            sb.update(level, False)
        self.assertEqual(self.events, [True])     # saver turned on once — below 25%
        self.assertEqual(len(self.notes), 1)
        self.assertIn('24%', self.notes[0])       # "battery low" notification
        self.assertAlmostEqual(sb.hours_left(), level / 3, delta=0.5)
        sb.update(21, False); sb.update(25, False)
        self.assertEqual(self.events, [True])     # between 25 and 30 — no flapping
        sb.update(25, True)
        self.assertEqual(self.events, [True, False])
        self.assertEqual(len(self.notes), 2)      # "charging — saver off"
        self.assertEqual(sb.forecast_text(), 'charging')

    def test_low_state_survives_restart_and_disable_restores(self):
        sb = self.make(); sb.update(25, False)
        self.assertEqual(self.events, [])         # exactly 25% — not yet
        sb.update(20, False)
        sb2 = self.make()
        self.assertTrue(sb2.low_active)
        sb2.set_enabled(False)
        self.assertEqual(self.events, [True, False])
        self.assertFalse(helpers.module_on('battery'))

    def test_saver_snapshot_and_apply(self):
        a = app.App.__new__(app.App); a.cfg = copy.deepcopy(app.DEFAULT); a.jobs = queue.Queue(); a.saver = True
        a.enqueue({'poll', 'light'})
        cats, save, cfg = a.jobs.get_nowait()
        self.assertTrue(cfg['_saver'])
        sent = []
        m = types.SimpleNamespace(connected=lambda: True, generic=False, set_poll=sent.append,
                                  set_reactive=lambda *_: None, set_zone=lambda z, c, fast=False: sent.append(c),
                                  set_default_light=lambda *_: None)
        a.mouse, a.log, a.post = m, lambda *_: None, lambda *_: None
        a._apply_locked(cats, False, cfg)
        self.assertEqual(sent[0], 500)
        self.assertEqual(sent[1:], [(0, 0, 0)] * 3)
        self.assertNotIn('_saver', a.cfg)  # never written to config


class RclickTests(Tmp):
    def test_tap_vs_hold_per_button(self):
        cfg = rclick.load_cfg()
        self.assertNotIn('apps', cfg)
        self.assertFalse(cfg['enabled'])
        self.assertEqual(rclick.is_tap(40, cfg, 'right'), 2)   # right ×3: 1 real + 2 injected
        self.assertEqual(rclick.is_tap(40, cfg, 'left'), 0)    # left is off by default
        cfg['left_on'], cfg['left'] = True, 6
        self.assertEqual(rclick.is_tap(40, cfg, 'left'), 5)    # left ×6
        self.assertEqual(rclick.is_tap(400, cfg, 'left'), 0)   # holds (mining) are left alone
        cfg['tap_ms'] = 60
        self.assertEqual(rclick.is_tap(80, cfg, 'left'), 0)    # adjustable tap threshold

    def test_ranges_and_setters(self):
        rc = rclick.RightClickMultiplier(lambda *a: None)
        rc.set_count('left', 9); rc.set_tap(5); rc.set_button('left', True)
        cfg = rclick.load_cfg()
        self.assertEqual((cfg['left'], cfg['tap_ms'], cfg['left_on']), (rclick.COUNT_MAX, rclick.TAP_MIN, True))
        self.assertEqual(rclick.counts_text(cfg), 'left ×6, right ×3')

    def test_bad_and_old_configs(self):
        Path(rclick.CFG_PATH).write_text('{"count": "x", "apps": 5, "enabled": "yes"}', encoding='utf-8')
        cfg = rclick.load_cfg()
        self.assertEqual(cfg['right'], 3); self.assertNotIn('apps', cfg)
        self.assertFalse(cfg['enabled'])
        Path(rclick.CFG_PATH).write_text('{"count": 5, "enabled": true}', encoding='utf-8')   # first V5 format
        cfg = rclick.load_cfg()
        self.assertEqual((cfg['right'], cfg['right_on'], cfg['left_on']), (5, True, False))
        Path(rclick.CFG_PATH).write_text('{"left": 0, "right": 4}', encoding='utf-8')         # 0 = button off
        cfg = rclick.load_cfg()
        self.assertEqual((cfg['left_on'], cfg['left'], cfg['right_on'], cfg['right']), (False, 3, True, 4))


class V5FixTests(Tmp):
    def test_rawaccel_autosearch(self):
        root = os.path.join(self.tmp.name, 'Downloads')
        a = os.path.join(root, 'RawAccel'); os.makedirs(a)
        Path(a, 'writer.exe').write_text('', encoding='utf-8')
        self.assertEqual(calibration.find_rawaccel([root]), a)          # found, but without settings.json
        self.assertFalse(calibration.set_rawaccel_dir(a, lambda *x: None))
        Path(a, 'settings.json').write_text('{}', encoding='utf-8')
        self.assertTrue(calibration.set_rawaccel_dir(calibration.find_rawaccel([root]), lambda *x: None))
        self.assertIsNone(calibration.find_rawaccel([os.path.join(self.tmp.name, 'empty')]))

    def test_multiclick_everywhere_by_default(self):
        cfg = rclick.load_cfg()
        self.assertNotIn('only_apps', cfg)
        self.assertNotIn('apps', cfg)

    def test_tray_toggles_only_multiclick_and_directional(self):
        self.assertEqual(set(helpers.TRAY_MODULES), {'directional', 'rclick'})

    def test_battery_estimate_before_learning(self):
        sb = smartbattery.SmartBattery(lambda a: None, lambda *a: None, clock=lambda: 1e6)
        sb.update(80, False)
        txt = sb.forecast_text()
        self.assertIn('(estimate)', txt)                 # estimate shown immediately, not "collecting data"
        self.assertAlmostEqual(sb.hours_left(), 80 / smartbattery.DEFAULT_RATE, places=3)


class HelpersTests(Tmp):
    def test_defaults_and_recall(self):
        self.assertTrue(helpers.module_on('battery'))
        self.assertFalse(helpers.module_on('rclick'))
        helpers.remember(['rclick', 'battery', 'bogus'])
        self.assertEqual(helpers.recall(), ['rclick', 'battery'])
        helpers.remember(None)
        self.assertEqual(helpers.recall(), [])


if __name__ == '__main__':
    unittest.main()
