"""Hardware-independent regression tests. Real Windows/HID smoke test still required."""
import ast
import copy
import importlib
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Keep the production imports intact; fake only unavailable hardware/tray backends.
sys.modules['hid'] = types.SimpleNamespace(enumerate=lambda *_: [])
sys.modules['pystray'] = types.SimpleNamespace()
import aerox_lite as app
from config_store import atomic_save

# Parse/playback is tested from the Windows source without calling the Win32 ABI.
source = (ROOT / 'winput.py').read_text(encoding='utf-8')
macro_code = source[source.index('VK = {'):]
macro = types.ModuleType('macro_logic')
macro.__dict__.update(threading=threading, time=importlib.import_module('time'), VK_F13=0x7C)
exec(compile(macro_code, 'winput macro logic', 'exec'), macro.__dict__)

class FakeHID:
    def __init__(self, reports=()):
        self.reports = list(reports)
        self.writes = []
        self.closed = False
        self.forever = False
        self.short = False
    def write(self, data):
        self.writes.append(data)
        return len(data) - 1 if self.short else len(data)
    def read(self, size, timeout_ms):
        if self.forever: return [0x21, 99]
        # Drain has a 1ms timeout; battery response appears after its request.
        if timeout_ms == 1: return []
        return self.reports.pop(0) if self.reports else []
    def close(self): self.closed = True

class CoreTests(unittest.TestCase):
    def normalize(self, user):
        return app.normalize(app.DEFAULT,user,app.KEYS,app.SPECIAL,app.MEDIA,dict(app.MODES))
    def test_bad_types_and_ranges(self):
        cfg = self.normalize({'dpi':[], 'binds':None, 'light':{'mode':[], 'colors':[None,'#123456','red'], 'brightness':999},
                              'poll':123, 'dpi_active':-50, 'macros':[None,{'slot':[]}]})
        self.assertEqual(cfg['dpi'], app.DEFAULT['dpi'])
        self.assertEqual(cfg['binds'], app.DEFAULT['binds'])
        self.assertEqual(cfg['light']['brightness'],100)
        self.assertEqual(cfg['light']['colors'],['#ffffff','#123456','#ffffff'])
        self.assertEqual(cfg['light']['mode'],'static')
    def test_legacy_config_and_macro_validation(self):
        cfg = self.normalize({'dpi':[455,19000,-100, float('nan'),300,400], 'dpi_active':99,
            'macros':[{'slot':2,'name':'X','mode':'hold','script':'a'}, {'slot':2,'mode':'once','script':'b'}, {'slot':15,'mode':'once','script':'c'}],
            'binds':['macro:bad','macro:2','macro:3','media:bad'], 'language':'en'})
        self.assertEqual(cfg['dpi'],[500,18000,100,400,300])
        self.assertEqual(cfg['dpi_active'],4)
        self.assertEqual(len(cfg['macros']),1)
        self.assertEqual(cfg['binds'][1],'macro:2')
        self.assertEqual(cfg['binds'][2],'button3')
        self.assertNotIn('language', cfg)  # legacy key from bilingual versions is dropped
    def test_arbitrary_config_values(self):
        for value in [None, True, [], {}, 3, 'wrong', float('inf')]:
            with self.subTest(value=value):
                cfg = self.normalize({k:value for k in app.DEFAULT})
                self.assertTrue(1 <= len(cfg['dpi']) <= 5)
                self.assertEqual(len(cfg['binds']),8)
                self.assertEqual(len(cfg['light']['colors']),3)
    def test_atomic_save_preserves_previous_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/'config.json')
            atomic_save(path,{'dpi':[400]})
            with patch('config_store.os.replace',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError): atomic_save(path,{'dpi':[800]})
            self.assertEqual(json.loads(Path(path).read_text(encoding='utf-8')), {'dpi':[400]})
            self.assertEqual(len(list(Path(tmp).iterdir())),1)
    def test_atomic_concurrent_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'config.json')
            threads=[threading.Thread(target=atomic_save,args=(path,{'n':i})) for i in range(15)]
            for t in threads:t.start()
            for t in threads:t.join()
            self.assertIn(json.loads(Path(path).read_text(encoding='utf-8'))['n'],range(15))
    def test_battery_rejects_unrelated_report(self):
        mouse=app.Mouse(); mouse.dev=FakeHID([[0x21,21]])
        self.assertEqual(mouse.battery(),(None,None))
        self.assertEqual(len(mouse.unsolicited),1)
    def test_battery_exact_and_wireless(self):
        for wireless,cmd in [(False,0x92),(True,0xD2)]:
            mouse=app.Mouse(); mouse.wireless=wireless; mouse.dev=FakeHID([[0x21,21],[cmd,0x80|11]])
            self.assertEqual(mouse.battery(),(50,True))
    def test_drain_bounded(self):
        mouse=app.Mouse(); mouse.dev=FakeHID(); mouse.dev.forever=True
        mouse._drain()
        self.assertEqual(len(mouse.unsolicited),50)
    def test_short_write_disconnects(self):
        mouse=app.Mouse(); device=FakeHID(); device.short=True;mouse.dev=device
        with self.assertRaises(IOError):mouse._cmd([0x21,1],fast=True)
        self.assertIsNone(mouse.dev)
        self.assertTrue(device.closed)
    def test_windows_padded_write_stays_connected(self):
        mouse=app.Mouse(); device=FakeHID();mouse.dev=device;mouse.wireless=True
        device.write=lambda data:64
        mouse._cmd([0x21,1,0,255,255,255],fast=True)
        self.assertIs(mouse.dev,device)
        self.assertFalse(device.closed)
    def test_windows_padded_battery_write(self):
        mouse=app.Mouse();device=FakeHID([[0xD2,11]]);mouse.dev=device;mouse.wireless=True
        device.write=lambda data:64
        self.assertEqual(mouse.battery(),(50,False))
        self.assertIs(mouse.dev,device)
    def test_failed_or_zero_write_disconnects(self):
        for result in (0,-1):
            with self.subTest(result=result):
                mouse=app.Mouse();device=FakeHID();mouse.dev=device
                device.write=lambda data:result
                with self.assertRaisesRegex(IOError,'HID write'):mouse._cmd([0x21,1],fast=True)
                self.assertIsNone(mouse.dev)
    def test_bind_malformed_macro_safe(self):
        self.assertEqual(app.encode_buttons(['macro:bad'])[0],1)
        self.assertEqual(len(app.encode_buttons(['key:A','macro:2'])),40)
    def test_worker_snapshot(self):
        a=app.App.__new__(app.App); a.cfg=copy.deepcopy(app.DEFAULT);a.jobs=queue.Queue()
        a.enqueue({'dpi'}); a.cfg['dpi'][0]=9000
        cats,save,cfg=a.jobs.get_nowait()
        self.assertEqual(cfg['dpi'][0],200)
    def test_speed_persist_scheduled(self):
        a=app.App.__new__(app.App);a.cfg=copy.deepcopy(app.DEFAULT); a._loading=False
        a.sp_lbl=types.SimpleNamespace(config=lambda **_:None);cats=[];a.changed=cats.append
        a._on_speed('77');self.assertEqual(a.cfg['light']['speed'],77);self.assertEqual(cats,['light'])
    def test_english_only_sources(self):
        for path in [*ROOT.glob('*.py'), *ROOT.glob('tests/*.py')]:
            text=path.read_text(encoding='utf-8')
            self.assertFalse(any('\u0400'<=ch<='\u04ff' for ch in text), path.name)
        self.assertEqual(app.action_name('button1'),'Button 1')
        self.assertTrue(app.MacroEditor.HELP.startswith('One line per action'))
    def test_macro_tabs_and_errors(self):
        self.assertEqual(macro.parse('wait\t50\ndown shift\nup shift\nctrl+c\ntext 😀')[0],('wait',50))
        with self.assertRaisesRegex(ValueError,'Line 1'):macro.parse('badkey')
    def test_macro_stop_releases_held_key(self):
        events=[];stop=threading.Event()
        def key(vk,up=False):
            events.append((vk,up))
            if not up:stop.set()
        macro.key=key
        macro.run([('down',65),('wait',999999)],stop)
        self.assertEqual(events,[(65,False),(65,True)])
    def test_macro_error_releases_partial_combo(self):
        events=[]
        def key(vk,up=False):
            if vk==66 and not up:raise OSError('injection failed')
            events.append((vk,up))
        macro.key=key
        with self.assertRaises(OSError):macro.run([('combo',[65,66])])
        self.assertEqual(events,[(65,False),(65,True)])

if __name__=='__main__':unittest.main()
