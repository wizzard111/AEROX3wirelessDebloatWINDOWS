"""Validated configuration and crash-safe atomic writes (no GUI dependencies)."""
import copy
import json
import math
import os
import re
import threading

_WRITE_LOCK = threading.Lock()


def normalize(default, user, keys, special, media, modes, max_macros=12):
    c = copy.deepcopy(default)
    if not isinstance(user, dict):
        return c
    def number(value, fallback, lo, hi, step=1):
        if isinstance(value, bool): return fallback
        try:
            n = float(value)
            if not math.isfinite(n): return fallback
            return max(lo, min(hi, round(n / step) * step))
        except (TypeError, ValueError, OverflowError): return fallback
    for key in ('apply_on_connect', 'autostart', 'eco', 'smart_light', 'verbose_log'):
        if isinstance(user.get(key), bool): c[key] = user[key]
    if user.get('theme') in ('dark', 'light'): c['theme'] = user['theme']
    levels = user.get('dpi')
    if isinstance(levels, list) and levels:
        c['dpi'] = [number(x, 400, 100, 18000, 100) for x in levels[:5]]
    c['dpi_active'] = number(user.get('dpi_active'), c['dpi_active'], 0, len(c['dpi']) - 1)
    if type(user.get('poll')) is int and user['poll'] in (125, 250, 500, 1000): c['poll'] = user['poll']
    for key, lo, hi, step in [('sleep',0,20,1), ('dim',0,1200,30), ('fps',5,30,1)]:
        c[key] = number(user.get(key), c[key], lo, hi, step)
    delay = user.get('smart_delay')
    if isinstance(delay, (int, float)) and not isinstance(delay, bool) and math.isfinite(delay):
        c['smart_delay'] = max(0.1, min(5.0, delay))
    scale = user.get('ui_scale')
    if isinstance(scale, (int, float)) and not isinstance(scale, bool) and math.isfinite(scale):
        c['ui_scale'] = round(max(0.5, min(2.0, scale)), 2)
    light = user.get('light')
    color = lambda x: isinstance(x, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', x) is not None
    if isinstance(light, dict):
        if isinstance(light.get('mode'), str) and light['mode'] in modes: c['light']['mode'] = light['mode']
        for key, lo in [('brightness',0), ('speed',1)]:
            c['light'][key] = number(light.get(key), c['light'][key], lo, 100)
        if isinstance(light.get('reactive'), bool): c['light']['reactive'] = light['reactive']
        if color(light.get('reactive_color')): c['light']['reactive_color'] = light['reactive_color']
        if isinstance(light.get('colors'), list):
            for i, value in enumerate(light['colors'][:3]):
                if color(value): c['light']['colors'][i] = value
    devices = user.get('devices')
    if isinstance(devices, dict):  # other mice: {"1038:pid": {setting: value}}; generic.py validates values
        simple = lambda v: (isinstance(v, (str, int, float)) and not isinstance(v, bool) and (not isinstance(v, str) or len(v) <= 256)) \
            or (isinstance(v, list) and len(v) <= 8 and all(type(x) is int for x in v)) \
            or (isinstance(v, dict) and len(v) <= 32 and all(isinstance(a, str) and len(a) <= 32 and isinstance(b, str)
                                                            and len(b) <= 64 for a, b in v.items()))  # button mapping
        for key, values in list(devices.items())[:64]:
            if isinstance(key, str) and re.fullmatch(r'[0-9a-f]{4}:[0-9a-f]{4}', key) and isinstance(values, dict):
                c['devices'][key] = {k: v for k, v in list(values.items())[:64] if isinstance(k, str) and simple(v)}
    used = set()
    if isinstance(user.get('macros'), list):
        for m in user['macros'][:max_macros]:
            if not isinstance(m, dict): continue
            slot = m.get('slot')
            if type(slot) is not int or not 0 <= slot < max_macros or slot in used: continue
            if m.get('mode') not in ('once', 'hold', 'toggle') or not isinstance(m.get('script'), str): continue
            used.add(slot)
            c['macros'].append({'slot':slot, 'name':str(m.get('name') or f'Macro {slot+1}')[:128],
                                'mode':m['mode'], 'script':m['script'][:65536]})
    binds = user.get('binds')
    if isinstance(binds, list):
        for i, v in enumerate(binds[:len(c['binds'])]):
            if not isinstance(v, str): continue
            valid = v in special or (v.startswith('key:') and v[4:] in keys) or (v.startswith('media:') and v[6:] in media)
            if v.startswith('macro:'):
                valid = v[6:].isdigit() and int(v[6:]) in used
            if valid: c['binds'][i] = v
    return c


def atomic_save(path, cfg):
    with _WRITE_LOCK:
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        # a fixed name per process (tempfile would import shutil and random at start-up for this)
        temporary = os.path.join(directory, '.config-{0}.tmp'.format(os.getpid()))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
