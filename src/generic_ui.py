"""Window contents for the other SteelSeries mice (generic.py): the same layout as for the Aerox 3.
Left: buttons (remapping, keys, media, macros). Centre: tabs and the picture of the mouse with its
lit zones in the chosen colours. Right: Settings (sensitivity, polling, battery and timers for a
wireless mouse, or a summary for a wired one), Lighting (zones, effects) and Modules.

Everything is built from the mouse's own settings (generic.specs), so one layout serves every model."""
import base64
import io
import re
import tkinter as tk
from tkinter import colorchooser

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk

import generic
import model_art
import mouse_art
import ui_theme
from ui_theme import ColorDot, Pill, Switch

F, FB, FS, FT, FU = "AxF", "AxFB", "AxFS", "AxFT", "AxFU"
ART_Y = 30          # picture offset in the canvas (room for the top tag)
TAG_W, TAG_H = 30, 20


def P(k): return ui_theme.PAL[k]
def px(n): return ui_theme.px(n)


def _band(mask, k, n):
    """k-th of n horizontal bands of a mask, between its own top and bottom."""
    bb = mask.getbbox()
    if not bb: return mask
    y0, y1 = bb[1], bb[3]
    b = Image.new("L", mask.size, 0)
    ImageDraw.Draw(b).rectangle((0, y0 + (y1 - y0) * k // n, mask.size[0], y0 + (y1 - y0) * (k + 1) // n), fill=255)
    return ImageChops.multiply(mask, b)


POSITIONS = ["top", "middle top", "middle", "middle bottom", "bottom"]


def zone_plan(color_specs, zones):
    """Which part of the picture each colour setting lights up.
    zones: {zone name: L mask}. Returns [(spec, mask or None, tag)]."""
    out, sides = [], {"left": [], "right": [], "strip": []}
    for s in color_specs:
        lab = s["label"].lower()
        m = re.match(r"(left|right)?\s*strip,?\s*(middle top|middle bottom|top|middle|bottom)", lab)
        if "wheel" in lab: out.append([s, zones.get("wheel"), "W"])
        elif "logo" in lab: out.append([s, zones.get("logo"), "LG"])
        elif m:
            side = m.group(1) or "strip"
            sides[side].append((POSITIONS.index(m.group(2)), s))
            out.append([s, None, ""])
        else:                                   # one colour for the whole mouse
            u = None
            for z in zones.values(): u = z if u is None else ImageChops.lighter(u, z)
            out.append([s, u, "LED"])
    for side, items in sides.items():
        if not items: continue
        items.sort(key=lambda t: t[0])
        if side == "strip":   # honeycomb, edge strip or both side strips, in bands
            base = zones.get("cells") or zones.get("rear")
            if base is None:
                for z in ("left", "right"):
                    if z in zones: base = zones[z] if base is None else ImageChops.lighter(base, zones[z])
        else:
            base = zones.get(side)
        for k, (_, s) in enumerate(items):
            mask = _band(base, k, len(items)) if base is not None else None
            tag = ("Z" if side == "strip" else side[0].upper()) + str(k + 1)
            for row in out:
                if row[0] is s: row[1], row[2] = mask, tag
    return [tuple(r) for r in out]


def zone_name(spec):
    return re.sub(r"\s*(LED\s+)?colou?rs?(\s+and\s+effects)?\s*$", "", spec["label"], flags=re.I) or spec["label"]


class GenericView:
    def __init__(self, app, lib):
        self.app, self.lib, self.mouse = app, lib, app.mouse
        self.values = app._gen_values()
        self.specs = {s["name"]: s for s in self.mouse.specs}
        self.btn_spec = next((s for s in self.mouse.specs if s["kind"] == "buttons"), None)
        self.colors = [s for s in self.mouse.specs if s["kind"] == "color"]
        self.sel_level = 0
        self.bind_btns, self.dots, self.tab_btns = {}, {}, {}
        self._art, self._art_key, self.art_tk = None, None, None

    # ------------------------------------------------------------ helpers
    def cur(self, name):
        s = self.specs[name]
        v = self.values.get(name, s.get("default"))
        if s["kind"] == "dpi": return generic.parse_dpi(v, s) or []
        if s["kind"] == "range":
            r = generic.valid_value(s, v)
            return s["range"][0] if r is None else r
        return v

    def set(self, name, value):
        self.app._gen_set(name, value)

    def card(self, parent, title=None, right=None):
        f = ui_theme.card(parent, radius=12)
        if title or right:
            h = tk.Frame(f, bg=P("PANEL")); h.pack(fill="x", padx=14, pady=(12, 6))
            if title: tk.Label(h, text=title, bg=P("PANEL"), fg=P("DIM"), font=FS).pack(side="left")
            if right: right(h)
        return f

    def note(self, parent, text, wrap=300):
        tk.Label(parent, text=text, bg=parent.cget("bg"), fg=P("DIM"), font=FS, justify="left",
                 wraplength=wrap).pack(anchor="w", padx=14, pady=(0, 10))

    def unit(self, name, v):
        if "sleep" in name: return "off" if v == 0 else "{0} min".format(v)
        if "dim" in name: return "off" if v == 0 else "{0} s".format(v)
        if "brightness" in name: return "{0}%".format(v)
        if "sensitivity" in name: return "{0} CPI".format(v)
        return str(v)

    # ------------------------------------------------------------ left: buttons
    def action_label(self, v):
        if re.fullmatch(r"button\d+", v or ""):
            names = {"button1": "Left click", "button2": "Right click", "button3": "Middle click",
                     "button4": "Back", "button5": "Forward"}
            return names.get(v) or "Button {0}".format(v[6:])
        if v in ("tiltleft", "tiltright"): return generic.BUTTON_LABELS[v]
        return self.lib.action_name(v, self.app.cfg["macros"])

    def binds(self):
        return dict(self.values.get("buttons_mapping") or {})

    def build_buttons(self, box):
        tk.Label(box, text='BUTTONS', bg=P("PANEL"), fg=P("DIM"), font=FS).pack(anchor="w", padx=14, pady=(12, 6))
        if not self.btn_spec:
            self.note(box, "This mouse does not let its buttons be remapped.", 270)
            return
        b = self.binds()
        for name, label, default in self.btn_spec["buttons"]:
            row = tk.Frame(box, bg=P("PANEL")); row.pack(fill="x", padx=14, pady=2)
            tk.Label(row, text=label, bg=P("PANEL"), fg=P("DIM"), font=F, width=14, anchor="w").pack(side="left")
            mb = tk.Menubutton(row, text=self.action_label(b.get(name, default)), bg=P("BTN"), fg=P("FG"),
                               activebackground=P("HOV"), activeforeground=P("FG"), relief="flat", font=FB,
                               anchor="w", width=15, padx=10, pady=4, cursor="hand2", bd=0, highlightthickness=0)
            mb["menu"] = self.bind_menu(mb, name); mb.pack(side="right")
            self.bind_btns[name] = mb
        br = tk.Frame(box, bg=P("PANEL")); br.pack(fill="x", padx=14, pady=(10, 2))
        self.lib.flatbtn(br, 'Reset', self.reset_buttons, kind="ghost").pack(side="left", padx=(0, 6))
        self.lib.flatbtn(br, 'Macros…', self.app.open_editor, kind="ghost").pack(side="left")

    def bind_menu(self, mb, name):
        mk = lambda parent: tk.Menu(parent, tearoff=0, bg=P("PANEL"), fg=P("FG"), activebackground=P("ACC"),
                                    activeforeground=P("ON_ACC"), font=F)
        m, act = mk(mb), self.btn_spec["actions"]
        names = [b[0].lower() for b in self.btn_spec["buttons"] if re.fullmatch(r"button\d+", b[0].lower())]
        for v in names: m.add_command(label=self.action_label(v), command=lambda v=v: self.set_bind(name, v))
        for v, ok in (("dpi", act["dpi"]), ("scrollup", act["scroll"]), ("scrolldown", act["scroll"]),
                      ("disabled", act["disabled"])):
            if ok: m.add_command(label=self.action_label(v), command=lambda v=v: self.set_bind(name, v))
        if act["keys"]:
            m.add_separator()
            kb = mk(m)
            for gname, keys in self.lib.KEY_GROUPS:
                sub = mk(kb)
                for k in keys: sub.add_command(label=k, command=lambda k=k: self.set_bind(name, "key:" + k))
                kb.add_cascade(label=gname, menu=sub)
            m.add_cascade(label='Keyboard', menu=kb)
        if act["media"]:
            mm = mk(m)
            for k, (n, _) in self.lib.MEDIA.items(): mm.add_command(label=n, command=lambda k=k: self.set_bind(name, "media:" + k))
            m.add_cascade(label='Media', menu=mm)
        if act["keys"]:
            mc = mk(m)
            for mac in sorted(self.app.cfg["macros"], key=lambda x: x["slot"]):
                mc.add_command(label=mac["name"], command=lambda sl=mac["slot"]: self.set_bind(name, "macro:{0}".format(sl)))
            if not self.app.cfg["macros"]: mc.add_command(label='(no macros — open editor)', state="disabled")
            m.add_cascade(label='Macros', menu=mc)
        return m

    def set_bind(self, name, v):
        b = self.binds(); b[name] = v
        self.set("buttons_mapping", b)
        self.bind_btns[name].config(text=self.action_label(v))
        self.app.log('{0}: {1}'.format(dict((n, l) for n, l, _ in self.btn_spec["buttons"])[name], self.action_label(v)))
        self.app._update_input()

    def reset_buttons(self):
        if not self.btn_spec: return
        self.set("buttons_mapping", {})
        for name, _, default in self.btn_spec["buttons"]: self.bind_btns[name].config(text=self.action_label(default))
        self.app.log('Buttons reset to default')

    def rebuild_menus(self):
        b = self.binds()
        for name, mb in self.bind_btns.items():
            old = mb["menu"]; mb["menu"] = self.bind_menu(mb, name)
            try: mb.nametowidget(old).destroy()
            except (KeyError, tk.TclError): pass
            default = next(d for n, _, d in self.btn_spec["buttons"] if n == name)
            mb.config(text=self.action_label(b.get(name, default)))

    # ------------------------------------------------------------ centre: tabs + picture
    def build_center(self, body):
        center = tk.Frame(body, bg=P("BG"))
        tabs = ui_theme.card(center, radius=12); tabs.pack(pady=(0, 10))
        for key, txt in (("settings", 'Settings'), ("light", 'Lighting'), ("modules", 'Modules')):
            b = Pill(tabs, txt, lambda k=key: self.app._tab(k), kind="quiet", font=FT, padx=18, pady=7, radius=9)
            b.pack(side="left", padx=3, pady=3); self.tab_btns[key] = b
        self.canvas = tk.Canvas(center, width=px(320), height=px(ART_Y + 430), bg=P("BG"), highlightthickness=0)
        self.canvas.pack()
        self.draw_art()
        return center

    def _layers(self):
        """(lines, shell, {zone: mask}) of this model at picture size."""
        slug = generic.art_slug(self.mouse.product)
        if slug in model_art.ART:
            img = Image.open(io.BytesIO(base64.b64decode("".join(model_art.ART[slug])))).convert("RGB")
            r, g, b = img.split()
            zones = {}
            for zi, zname in enumerate(model_art.ZONES):
                if not zname: continue
                m = b.point(lambda v, zi=zi: 255 if v == zi else 0)
                if m.getbbox(): zones[zname] = m.filter(ImageFilter.GaussianBlur(0.6)).point(lambda v: min(255, v * 2))
            return r, g, zones
        # the original wired Aerox 3: its picture is the one the Aerox 3 Wireless uses
        lines = Image.open(io.BytesIO(base64.b64decode(mouse_art.LINES))).convert("L")
        cells = Image.open(io.BytesIO(base64.b64decode(mouse_art.CELLS))).convert("L")
        shell = Image.new("L", lines.size, 0)
        return lines, shell, {"cells": cells}

    def draw_art(self):
        if not getattr(self, "canvas", None): return
        self._shown = None
        sc = self.app.ui_scale * self.app.px_k
        if self._art is None or self._art[0] != sc:
            lines, shell, zones = self._layers()
            size = (round(lines.size[0] * sc), round(lines.size[1] * sc))
            if sc != 1:
                lines, shell = lines.resize(size, Image.LANCZOS), shell.resize(size, Image.LANCZOS)
                zones = {k: v.resize(size, Image.LANCZOS) for k, v in zones.items()}
            plan = []
            for spec, mask, tag in zone_plan(self.colors, zones):
                glow = mask.filter(ImageFilter.GaussianBlur(5 * sc)) if mask is not None else None
                plan.append((spec, mask, glow, tag))
            self._art = (sc, lines, shell, plan, size)
            self._draw_tags()
        self.render_art()

    def _draw_tags(self):
        c = self.canvas; c.delete("all")
        sc, lines, shell, plan, (W, H) = self._art
        cw = round(320 * sc); c.config(width=cw, height=round((ART_Y + 430) * sc))
        ox, oy = (cw - W) // 2, round(ART_Y * sc)
        self.art_id = c.create_image(ox, oy, anchor="nw"); self.art_tk = None
        tags = []
        for spec, mask, glow, tag in plan:
            if mask is None or not tag or not mask.getbbox(): continue
            bb = mask.getbbox(); cx, cy = (bb[0] + bb[2]) // 2, (bb[1] + bb[3]) // 2
            # point at the zone itself (the middle of a band can fall between honeycomb cells)
            k = 4  # search a 4x smaller copy: same answer to a few pixels, 16x fewer reads
            small = mask.crop(bb).resize((max(1, (bb[2] - bb[0]) // k), max(1, (bb[3] - bb[1]) // k)), Image.BOX)
            data, sw = small.load(), small.size[0]
            pts = [(bb[0] + x * k + k // 2, bb[1] + y * k + k // 2) for y in range(small.size[1]) for x in range(sw)
                   if data[x, y] > 100]
            if pts: cx, cy = min(pts, key=lambda q: (q[0] - cx) ** 2 + (q[1] - cy) ** 2)
            right = not (tag.startswith("L") and tag[1:].isdigit())   # left strip tags left, the rest right
            tags.append((right, cy, cx, tag))
        bw, bh, r = round(TAG_W * sc), round(TAG_H * sc), max(2, round(3 * sc))
        self._tag_img = ui_theme.rounded(bw, bh, max(3, round(6 * sc)), P("BTN"), P("BG"), P("TAGLINE"))
        for side in (False, True):
            last = -10 ** 6
            for right, cy, cx, tag in sorted(t for t in tags if t[0] == side):
                ty = max(cy, last + bh + round(4 * sc)); last = ty
                lx = cw - round(4 * sc) - bw // 2 if right else round(4 * sc) + bw // 2
                c.create_line(lx, oy + ty, ox + cx, oy + cy, fill=P("TAGLINE"))
                c.create_oval(ox + cx - r, oy + cy - r, ox + cx + r, oy + cy + r, fill=P("FG"), outline=P("BG"))
                c.create_image(lx, oy + ty, image=self._tag_img)
                c.create_text(lx, oy + ty, text=tag, fill=P("FG"), font=FS)

    def colours(self):
        return [ui_theme.rgb(generic.color_hex(self.values.get(s["name"], s.get("default")), "#000000"))
                for s, m, g, t in self._art[3]]

    def render_art(self, fade=True):
        """Draw the picture in the current colours; a colour change fades in (~160 ms)."""
        if self._art is None: return
        to = self.colours()
        shown = getattr(self, "_shown", None)
        if fade and ui_theme.ANIMATE and shown and len(shown) == len(to) and shown != to:
            self._fade = (shown, __import__("time").monotonic(), to); self._fade_step(); return
        self._paint(to)

    def _fade_step(self):
        import time
        frm, t0, to = self._fade
        if to != self.colours(): return self.render_art()   # changed again meanwhile
        f = min(1.0, (time.monotonic() - t0) / 0.16)
        self._paint([tuple(round(a + (b - a) * f) for a, b in zip(x, y)) for x, y in zip(frm, to)])
        if f < 1: self.canvas.after(16, self._fade_step)

    def _paint(self, cols):
        self._shown = cols
        sc, lines, shell, plan, (W, H) = self._art
        dark = ui_theme.THEME == "dark"
        frame = Image.new("RGB", (W, H), ui_theme.rgb(P("BG")))
        frame.paste(ui_theme.rgb(P("PANEL")), (0, 0, W, H), shell)
        for (spec, mask, glow, tag), col in zip(plan, cols):
            if mask is None: continue
            if max(col) <= 12:
                frame.paste(ui_theme.rgb(P("CELL_OFF")), (0, 0, W, H), mask)
            else:
                frame.paste(tuple(int(v * 0.45) for v in col) if dark else col, (0, 0, W, H), glow)
                frame.paste(col, (0, 0, W, H), mask)
        frame.paste(ui_theme.rgb(P("ART_LINE")), (0, 0, W, H), lines)
        if self.art_tk is not None and (self.art_tk.width(), self.art_tk.height()) == (W, H):
            self.art_tk.paste(frame)
        else:
            self.art_tk = ImageTk.PhotoImage(frame); self.canvas.itemconfig(self.art_id, image=self.art_tk)

    def rescale(self):
        self._art = None; self.draw_art(); self.render_dpi(); self.update_status()

    def retheme(self):
        """Colours changed: draw the picture, its tags and the battery bar again."""
        self._art = None; self.draw_art(); self.update_status()

    def free_art(self):
        """While the window is hidden the picture buffers are not needed."""
        self._art, self.art_tk = None, None
        if getattr(self, "canvas", None): self.canvas.delete("all")

    # ------------------------------------------------------------ right: tab panes
    def build_right(self, body):
        self.right = tk.Frame(body, bg=P("BG"))
        self.panes = {k: tk.Frame(self.right, bg=P("BG")) for k in ("settings", "light", "modules")}
        self.build_settings(self.panes["settings"])
        self.build_light(self.panes["light"])
        self.app._build_modules(self.panes["modules"])
        return self.right

    def tab(self, key):
        for k, b in self.tab_btns.items(): b.set(sel=(k == key))
        p = self.panes[key]  # stacked in one place, each shown when first opened; switching only raises one
        if not p.winfo_manager(): p.place(x=0, y=0, relwidth=1, relheight=1)
        p.tkraise()

    def size_right(self):
        self.app.root.update_idletasks()
        self.right.config(width=max(p.winfo_reqwidth() for p in self.panes.values()),
                          height=max(p.winfo_reqheight() for p in self.panes.values()))
        self.right.pack_propagate(False)

    # settings ----------------------------------------------------
    def build_settings(self, p):
        specs = self.mouse.specs
        dpi = next((s for s in specs if s["kind"] == "dpi"), None)
        presets = [s for s in specs if s["kind"] == "range" and "sensitivity" in s["name"]]
        picks = [s for s in specs if s["kind"] == "choice" and "sensitivity" in s["name"]]  # fixed CPI steps
        if dpi: self.build_dpi(p, dpi)
        elif picks and not presets:
            c = self.card(p, 'SENSITIVITY', lambda h: tk.Label(h, text='CPI button switches presets', bg=P("PANEL"),
                                                               fg=P("DIM"), font=FS).pack(side="right"))
            c.pack(fill="x")
            for s in picks:
                tk.Label(c, text=s["label"].replace("Sensitivity preset", "Preset"), bg=P("PANEL"), fg=P("FG"),
                         font=F).pack(anchor="w", padx=14)
                self.choice_row(c, s, suffix=" CPI")
        elif presets:
            c = self.card(p, 'SENSITIVITY', lambda h: tk.Label(h, text='CPI button switches presets', bg=P("PANEL"),
                                                               fg=P("DIM"), font=FS).pack(side="right"))
            c.pack(fill="x")
            for s in presets: self.range_row(c, s, s["label"].replace("Sensitivity preset", "Preset"))
            ui_theme.sized(tk.Frame(c, bg=P("PANEL")), height=4).pack()
        poll = self.specs.get("polling_rate")
        if poll:
            c = self.card(p, 'POLLING RATE'); c.pack(fill="x", pady=(10, 0))
            self.choice_row(c, poll, suffix=" Hz")
        timers = [s for s in specs if s["kind"] == "range" and "timer" in s["name"]]
        if self.mouse.has_battery or timers:
            c = self.card(p, 'BATTERY'); c.pack(fill="x", pady=(10, 0))
            top = tk.Frame(c, bg=P("PANEL")); top.pack(fill="x", padx=14)
            self.batt_big = tk.Label(top, text="—", bg=P("PANEL"), fg=P("FG"), font="AxFH"); self.batt_big.pack(side="left")
            self.batt_txt = tk.Label(top, text="", bg=P("PANEL"), fg=P("DIM"), font=F); self.batt_txt.pack(side="left", padx=(10, 0))
            self.batt_bar = ui_theme.sized(tk.Canvas(c, bg=P("PANEL"), highlightthickness=0), height=8, width=300)
            self.batt_bar.pack(fill="x", padx=14, pady=(6, 10))
            self.batt_bar.bind("<Configure>", self._draw_batt_bar)
            for s in timers: self.range_row(c, s, "Sleep after" if "sleep" in s["name"] else "Dim lighting after")
            self.update_status()
        else:
            c = self.card(p, 'THIS MOUSE'); c.pack(fill="x", pady=(10, 0))
            grid = tk.Frame(c, bg=P("PANEL")); grid.pack(fill="x", padx=14)
            levels = dpi["max"] if dpi else len(presets) or len(picks)
            if dpi or presets: top_cpi = (dpi or presets[0])["range"][1]
            else: top_cpi = max([int(c) for s in picks for c in s["choices"] if str(c).isdigit()] or [0])
            facts = [(str(len(self.colors)), 'light zones'), (str(levels), 'CPI levels' if dpi else 'CPI presets'),
                     ("{0}k".format(round(top_cpi / 1000)) if top_cpi >= 1000 else str(top_cpi), 'max CPI')]
            for i, (big, small) in enumerate(facts):
                f = ui_theme.sized(tk.Frame(grid, bg=P("BG")), padx=10, pady=8); f.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
                grid.columnconfigure(i, weight=1)
                tk.Label(f, text=big, bg=P("BG"), fg=P("FG"), font="AxFH").pack(anchor="w")
                tk.Label(f, text=small, bg=P("BG"), fg=P("DIM"), font=FS).pack(anchor="w")
            tk.Label(c, text='Powered by the cable: no battery, no sleep or dim timers.', bg=P("PANEL"), fg=P("DIM"),
                     font=FS, wraplength=300, justify="left").pack(anchor="w", padx=14, pady=(8, 10))
        more = [s for s in specs if s["kind"] == "choice" and s["group"] in ("Performance", "Other")
                and s["name"] != "polling_rate" and s not in picks]
        if more:
            c = self.card(p, 'MORE'); c.pack(fill="x", pady=(10, 0))
            for s in more:
                tk.Label(c, text=s["label"], bg=P("PANEL"), fg=P("FG"), font=F).pack(anchor="w", padx=14)
                self.choice_row(c, s)

    def build_dpi(self, p, s):
        lo, hi, step = s["range"]
        c = self.card(p, 'SENSITIVITY', lambda h: tk.Label(h, text='CPI button cycles levels', bg=P("PANEL"), fg=P("DIM"),
                                                           font=FS).pack(side="right"))
        c.pack(fill="x")
        self.dpi_spec = s
        self.lv_row = tk.Frame(c, bg=P("PANEL")); self.lv_row.pack(fill="x", padx=14)
        r = tk.Frame(c, bg=P("PANEL")); r.pack(fill="x", padx=14, pady=(8, 0))
        self.dpi_s = self.lib.slider(r, lo, hi, step, self._dpi_slid); self.dpi_s.pack(side="left", fill="x", expand=True)
        self.dpi_var = tk.StringVar()
        e = tk.Entry(r, textvariable=self.dpi_var, width=7, bg=P("BTN"), fg=P("FG"), insertbackground=P("FG"),
                     relief="flat", font=FB, justify="center")
        e.pack(side="left", padx=(10, 0), ipady=3); e.bind("<Return>", self._dpi_entry); e.bind("<FocusOut>", self._dpi_entry)
        links = tk.Frame(c, bg=P("PANEL")); links.pack(fill="x", padx=14, pady=(4, 10))
        for txt, fn in (('Add level', self._dpi_add), ('Remove level', self._dpi_rm)):
            l = tk.Label(links, text=txt, bg=P("PANEL"), fg=P("FG"), font=FU, cursor="hand2")
            l.bind("<Button-1>", lambda e, fn=fn: fn()); l.pack(side="left", padx=(0, 14))
        tk.Label(links, text="{0}–{1}".format(lo, hi), bg=P("PANEL"), fg=P("DIM"), font=FS).pack(side="right")
        self.render_dpi()

    def render_dpi(self):
        if not hasattr(self, "lv_row"): return
        levels = self.cur(self.dpi_spec["name"]) or [800]
        self.sel_level = min(self.sel_level, len(levels) - 1)
        for w in self.lv_row.winfo_children(): w.destroy()
        for i, v in enumerate(levels):
            b = Pill(self.lv_row, "LV {0}\n{1}".format(i + 1, v), lambda i=i: self._dpi_pick(i), sel=(i == self.sel_level),
                     font=FS, padx=8, pady=4)
            b.pack(side="left", padx=(0, 6))
        self._loading = True
        self.dpi_s.set(levels[self.sel_level]); self.dpi_var.set(str(levels[self.sel_level]))
        self._loading = False

    def _dpi_store(self, levels):
        self.set(self.dpi_spec["name"], levels); self.render_dpi()

    def _dpi_pick(self, i): self.sel_level = i; self.render_dpi()

    def _dpi_slid(self, v):
        if getattr(self, "_loading", False): return
        levels = list(self.cur(self.dpi_spec["name"]) or [800])
        n = generic.parse_dpi([v], self.dpi_spec)[0]
        if levels[self.sel_level] != n:
            levels[self.sel_level] = n; self.dpi_var.set(str(n)); self.set(self.dpi_spec["name"], levels)
            for i, w in enumerate(self.lv_row.winfo_children()):
                w.set(text="LV {0}\n{1}".format(i + 1, levels[i]))

    def _dpi_entry(self, _=None):
        got = generic.parse_dpi([self.dpi_var.get()], self.dpi_spec)
        if not got: self.render_dpi(); return
        levels = list(self.cur(self.dpi_spec["name"]) or [800]); levels[self.sel_level] = got[0]; self._dpi_store(levels)

    def _dpi_add(self):
        levels = list(self.cur(self.dpi_spec["name"]) or [800])
        if len(levels) >= self.dpi_spec["max"]: return
        levels.append(min(self.dpi_spec["range"][1], levels[-1] * 2)); self.sel_level = len(levels) - 1; self._dpi_store(levels)

    def _dpi_rm(self):
        levels = list(self.cur(self.dpi_spec["name"]) or [800])
        if len(levels) <= 1: return
        levels.pop(self.sel_level); self._dpi_store(levels)

    def range_row(self, parent, s, title):
        h = tk.Frame(parent, bg=P("PANEL")); h.pack(fill="x", padx=14)
        tk.Label(h, text=title, bg=P("PANEL"), fg=P("FG"), font=F).pack(side="left")
        val = tk.Label(h, text=self.unit(s["name"], self.cur(s["name"])), bg=P("PANEL"), fg=P("FG"), font=FB)
        val.pack(side="right")
        lo, hi, step = s["range"]
        def moved(v, s=s, val=val):
            v = generic.valid_value(s, v)
            val.config(text=self.unit(s["name"], v))
            if v != self.cur(s["name"]): self.set(s["name"], v)
        sl = self.lib.slider(parent, lo, hi, step, None); sl.set(self.cur(s["name"])); sl.config(command=moved)
        sl.pack(fill="x", padx=14, pady=(2, 10))

    def choice_row(self, parent, s, suffix=""):
        cur = self.cur(s["name"])
        if len(s["choices"]) <= 6 and sum(len(str(c)) for c in s["choices"]) <= 36:
            row = tk.Frame(parent, bg=P("PANEL")); row.pack(fill="x", padx=14, pady=(2, 10))
            pills = []
            def pick(c):
                for p_, cc in pills: p_.set(sel=str(cc) == str(c))
                self.set(s["name"], c)
            for c in s["choices"]:
                last = c == s["choices"][-1]
                b = Pill(row, str(c) + (suffix if last and suffix else ""), lambda c=c: pick(c), sel=str(c) == str(cur),
                         font=FS, padx=10, pady=4)
                b.pack(side="left", padx=(0, 6)); pills.append((b, c))
            return
        mb = tk.Menubutton(parent, text=str(cur), bg=P("BTN"), fg=P("FG"), activebackground=P("HOV"),
                           activeforeground=P("FG"), relief="flat", font=FB, anchor="w", padx=10, pady=4,
                           cursor="hand2", bd=0, highlightthickness=0)
        menu = tk.Menu(mb, tearoff=0, bg=P("PANEL"), fg=P("FG"), activebackground=P("HOV"), activeforeground=P("FG"))
        for c in s["choices"]:
            menu.add_command(label=str(c), command=lambda c=c: (mb.config(text=str(c)), self.set(s["name"], c)))
        mb["menu"] = menu; mb.pack(fill="x", padx=14, pady=(2, 10))

    # lighting ----------------------------------------------------
    def build_light(self, p):
        c = self.card(p, 'LIGHTING ZONES', (lambda h: Pill(h, 'Set all…', self.set_all, kind="ghost", font=FS, padx=10,
                                                           pady=2).pack(side="right")) if len(self.colors) > 1 else None)
        c.pack(fill="x")
        if not self.colors:
            self.note(c, 'This mouse has no adjustable colours.')
        tags = {s["name"]: t for s, m, t in zone_plan(self.colors, {})}
        for s in self.colors:
            row = tk.Frame(c, bg=P("PANEL")); row.pack(fill="x", padx=14, pady=3)
            tag = tags.get(s["name"], "")
            if tag:
                tk.Label(row, text=tag, bg=P("BTN"), fg=P("FG"), font=FS, width=4).pack(side="left", padx=(0, 10))
            tk.Label(row, text=zone_name(s), bg=P("PANEL"), fg=P("FG"), font=F, anchor="w").pack(side="left")
            dot = ColorDot(row, generic.color_hex(self.values.get(s["name"], s.get("default")), "#000000"), 22,
                           lambda s=s: self.pick(s))
            dot.pack(side="right"); self.dots[s["name"]] = dot
        ui_theme.sized(tk.Frame(c, bg=P("PANEL")), height=8).pack()
        fx = [s for s in self.mouse.specs if s["group"] == "Lighting" and s["kind"] in ("choice", "range", "reactive", "action")]
        if fx:
            e = self.card(p, 'EFFECTS'); e.pack(fill="x", pady=(10, 0))
            for s in fx:
                if s["kind"] == "range": self.range_row(e, s, s["label"]); continue
                row = tk.Frame(e, bg=P("PANEL")); row.pack(fill="x", padx=14, pady=(2, 2))
                tk.Label(row, text=s["label"], bg=P("PANEL"), fg=P("FG"), font=F).pack(side="left")
                if s["kind"] == "choice": self.choice_row(e, s)
                elif s["kind"] == "reactive": self.reactive_row(row, s); row.pack_configure(pady=(2, 8))
                else:
                    Pill(row, 'Run', lambda n=s["name"]: self.app._gen_run(n), kind="ghost", font=FS, padx=10,
                         pady=3).pack(side="right"); row.pack_configure(pady=(2, 8))

    def reactive_row(self, row, s):
        cur = self.values.get(s["name"], s.get("default"))
        off = cur == "off"
        dot = ColorDot(row, generic.color_hex(None if off else cur, P("LINE")), 22, None)
        if off: dot.show_theme("LINE")
        last = {"c": generic.color_hex(None if off else cur, "#ffffff")}
        def flip():
            now = self.values.get(s["name"], s.get("default"))
            if now == "off": v = last["c"]; on = True
            else: last["c"] = generic.color_hex(now, "#ffffff"); v = "off"; on = False
            sw.set(on); self.set(s["name"], v)
            if on: dot.config(bg=v)
            else: dot.show_theme("LINE")
        def pick():
            c = colorchooser.askcolor(color=last["c"], parent=row.winfo_toplevel(), title=s["label"])[1]
            if c: last["c"] = c; dot.config(bg=c); sw.set(True); self.set(s["name"], c)
        dot.bind("<Button-1>", lambda e: pick()); dot.config(cursor="hand2"); dot.pack(side="right")
        sw = Switch(row, flip, on=not off, small=True); sw.pack(side="right", padx=(0, 10))

    def pick(self, s):
        c = colorchooser.askcolor(color=generic.color_hex(self.values.get(s["name"], s.get("default")), "#ffffff"),
                                  parent=self.app.root, title=zone_name(s))[1]
        if not c: return
        self.dots[s["name"]].config(bg=c); self.set(s["name"], c); self.render_art()

    def set_all(self):
        first = self.colors[0]
        c = colorchooser.askcolor(color=generic.color_hex(self.values.get(first["name"], first.get("default")), "#ffffff"),
                                  parent=self.app.root, title='All zones')[1]
        if not c: return
        for s in self.colors: self.dots[s["name"]].config(bg=c); self.set(s["name"], c)
        self.render_art()

    # status ------------------------------------------------------
    def update_status(self):
        if not hasattr(self, "batt_big"): return
        lvl, ch = self.app.batt
        conn = self.app.mouse.connected()
        self.batt_big.config(text="{0}%".format(lvl) if conn and lvl is not None else "—")
        sb = self.app.sb
        fc = sb.forecast_text() if sb and sb.enabled and lvl is not None and not ch else ""
        if not conn: txt = 'not connected'
        elif lvl is None: txt = 'asleep or off'
        elif ch: txt = 'charging'
        else: txt = fc or 'on battery'
        self.batt_txt.config(text=txt)
        self._batt = (conn, lvl)
        self._draw_batt_bar()

    def _draw_batt_bar(self, _=None):
        """Drawn at the bar's current width; redrawn when it is resized (asking Tk for the width before
        it is laid out would force a relayout of the whole window)."""
        conn, lvl = getattr(self, "_batt", (False, None))
        bar = self.batt_bar; bar.delete("all")
        w, h = max(10, bar.winfo_width() if bar.winfo_width() > 1 else px(300)), px(8)
        bar.create_rectangle(0, 0, w, h, fill=P("LINE"), width=0)
        if conn and lvl is not None:
            bar.create_rectangle(0, 0, w * lvl / 100, h, fill=P("GOOD"), width=0)

    def load(self):
        self.render_dpi(); self.render_art()
