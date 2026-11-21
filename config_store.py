"""Validated configuration and crash-safe atomic writes (no GUI dependencies)."""
import copy
import json
import math
import os
import re
import tempfile
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
        fd, temporary = tempfile.mkstemp(prefix='.config-', suffix='.tmp', dir=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
