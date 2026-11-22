"""Theme palettes and the small custom widgets of the interface: rounded cards, pill buttons,
switches, colour dots and icons. Pure Tk + Pillow (no extra dependencies); shapes are drawn
4x larger and scaled down, so their edges are smooth at any interface size."""
import base64
import io
import math
import tkinter as tk
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

PALETTES = {
    "dark": dict(BG="#0B0B0D", PANEL="#141417", LINE="#26262B", BTN="#0C0C0E", HOV="#26262B",
                 FG="#F4F4F5", DIM="#A1A1AA", ACC="#F4F4F5", ON_ACC="#0B0B0D", KNOB_OFF="#A1A1AA",
                 LOG_BG="#0F0F12", LOG_DIM="#71717A", GOOD="#4ADE80", TAGLINE="#3F3F46",
                 CELL_OFF="#28282C", ART_LINE="#EBEBEB"),
    "light": dict(BG="#F4F4F6", PANEL="#FFFFFF", LINE="#E4E4E7", BTN="#E7E7EB", HOV="#DADADF",
                  FG="#18181B", DIM="#52525B", ACC="#18181B", ON_ACC="#FFFFFF", KNOB_OFF="#FFFFFF",
                  LOG_BG="#FAFAFB", LOG_DIM="#71717A", GOOD="#16A34A", TAGLINE="#A1A1AA",
                  CELL_OFF="#D6D6DC", ART_LINE="#1C1C20"),
}
THEME = "dark"
ANIMATE = True   # short transitions while something changes (never while idle)
PAL = dict(PALETTES["dark"])
SCALE = 1.0
SS = 4  # supersampling factor for anti-aliased shapes
_cache = {}


def set_theme(name):
    global THEME
    THEME = name if name in PALETTES else "dark"
    PAL.clear(); PAL.update(PALETTES[THEME]); _cache.clear()
    return PAL


def set_scale(scale):
    global SCALE
    if scale != SCALE:
        SCALE = scale; _cache.clear()


def px(n):
    return max(1, round(n * SCALE))


def rgb(color):
    c = color.lstrip("#")
    if len(c) == 3: c = "".join(ch * 2 for ch in c)
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _photo(key, w, h, bg, draw):
    """Cached PhotoImage of size w x h on an opaque background, drawn at SS x by draw(d, s)."""
    img = _cache.get(key)
    if img is None:
        big = Image.new("RGB", (w * SS, h * SS), rgb(bg))
        draw(ImageDraw.Draw(big), SS)
        img = _cache[key] = ImageTk.PhotoImage(big.resize((w, h), Image.LANCZOS))
    return img


def rounded(w, h, r, fill, bg, outline=None):
    def d(dr, s):
        dr.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=r * s, fill=fill, outline=outline,
                             width=s if outline else 0)
    return _photo(("rr", w, h, r, fill, bg, outline), w, h, bg, d)


# ---------------------------------------------------------------- icons drawn into button images
def _icon(dr, s, name, cx, cy, size, color):
    k = size * s / 16
    if name == "power":
        dr.arc((cx - 6 * k, cy - 6 * k, cx + 6 * k, cy + 6 * k), start=-60, end=240, fill=color, width=max(1, round(1.7 * k)))
        dr.line((cx, cy - 7.5 * k, cx, cy - 1.5 * k), fill=color, width=max(1, round(1.7 * k)))
    elif name == "sun":
        r = 3.2 * k
        dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
        for i in range(8):

            a = i * math.pi / 4
            dr.line((cx + math.cos(a) * 5 * k, cy + math.sin(a) * 5 * k, cx + math.cos(a) * 6.8 * k, cy + math.sin(a) * 6.8 * k),
                    fill=color, width=max(1, round(1.4 * k)))
    elif name == "moon":
        r = 5.5 * k
        dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
        return "cut"


def theme_switch_image(light, pos=None):
    """Pill-shaped dark/light toggle: moon on the left (dark), sun on the right (light).
    pos (0..1) places the knob in between, for the slide animation."""
    if pos is None: pos = 1.0 if light else 0.0
    w, h = px(48), px(26)
    bg = PAL["BG"]
    def d(dr, s):
        dr.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=h * s // 2, fill=PAL["PANEL"], outline=PAL["LINE"], width=s)
        kr = (h - px(6)) * s // 2
        kx = round(((h // 2) + (w - h - 1) * pos) * s)
        ky = h * s // 2
        dr.ellipse((kx - kr, ky - kr, kx + kr, ky + kr), fill=PAL["ACC"])
        if light:
            _icon(dr, s, "sun", kx, ky, px(12), PAL["ON_ACC"])
        else:
            _icon(dr, s, "moon", kx, ky, px(12), PAL["ON_ACC"])
            off = 2.4 * px(12) * s / 16  # crescent: cover part of the moon with the knob colour
            r = 4.6 * px(12) * s / 16
            dr.ellipse((kx + off - r, ky - off - r, kx + off + r, ky - off + r), fill=PAL["ACC"])
    return _photo(("theme", light, round(pos, 3), w, h, THEME), w, h, bg, d)


def battery_image(level, charging):
    w, h = px(26), px(14)
    bg = PAL["PANEL"]
    def d(dr, s):
        lw = max(1, round(1.4 * s * SCALE))
        body = (lw // 2, lw // 2, (w - px(4)) * s, h * s - lw // 2 - 1)
        dr.rounded_rectangle(body, radius=px(3) * s, outline=PAL["DIM"], width=lw)
        dr.rounded_rectangle(((w - px(3)) * s, px(4) * s, w * s - 1, (h - px(4)) * s), radius=px(1) * s, fill=PAL["DIM"])
        if level is not None:
            inner_w = (w - px(4)) * s - 2 * px(2) * s - lw
            fw = max(px(2) * s, round(inner_w * max(0, min(100, level)) / 100))
            dr.rounded_rectangle((px(2) * s + lw // 2, px(2) * s + lw // 2, px(2) * s + lw // 2 + fw, h * s - px(2) * s - lw // 2),
                                 radius=px(1) * s, fill=PAL["GOOD"] if charging else PAL["FG"])
    return _photo(("bat", None if level is None else level // 5, charging, w, h, THEME), w, h, bg, d)


def dot_image(color, size=8, bg=None):
    bg = bg or PAL["PANEL"]; n = px(size)
    def d(dr, s):
        dr.ellipse((0, 0, n * s - 1, n * s - 1), fill=color)
    return _photo(("dot", color, n, bg), n, n, bg, d)


def logo_image(size, fill=None, glyph=None):
    """The app mark: a simple mouse (outline + wheel) on a rounded square. Readable at 16-64 px,
    unlike the detailed artwork. PIL image (RGBA)."""
    fill, glyph = fill or PAL["ACC"], glyph or PAL["ON_ACC"]
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, n - 1, n - 1), radius=round(n * 0.26), fill=fill)
    w, h, lw = n * 0.40, n * 0.58, max(SS, round(n * 0.065))
    x0, y0 = (n - w) / 2, (n - h) / 2
    d.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=w / 2, outline=glyph, width=lw)
    d.line((n / 2, y0 + lw, n / 2, y0 + h * 0.34), fill=glyph, width=lw)
    return img.resize((size, size), Image.LANCZOS)


def app_icon(size, mouse_lines_b64=None):
    """The app icon: the mouse outline on a dark rounded square (PIL image)."""
    if mouse_lines_b64 is None:
        import mouse_art
        mouse_lines_b64 = mouse_art.LINES
    lines = Image.open(io.BytesIO(base64.b64decode(mouse_lines_b64))).convert("L")
    lines = lines.crop(lines.getbbox())
    side = round(max(lines.size) * 1.3)
    icon = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    ImageDraw.Draw(icon).rounded_rectangle((0, 0, side - 1, side - 1), radius=side // 5, fill=(17, 17, 17, 255))
    icon.paste(Image.new("RGBA", lines.size, (255, 255, 255, 255)), ((side - lines.size[0]) // 2, (side - lines.size[1]) // 2), lines)
    return icon.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------- widgets
def card(parent, radius=12, fill=None, border=None):
    """A Frame with rounded corners: a 1 px border plus anti-aliased corner masks placed over the
    square corners. Works with pack/grid like any Frame; keep content inset by >= the radius."""
    fill = fill or PAL["PANEL"]; border = border or PAL["LINE"]
    outside = parent.cget("bg"); r = px(radius)
    f = tk.Frame(parent, bg=fill, highlightthickness=1, highlightbackground=border, highlightcolor=border, bd=0)
    imgs = _corners(r, fill, border, outside)
    f._ax_corners = {}
    for k, (rx, ry, dx, dy) in {"nw": (0, 0, -1, -1), "ne": (1, 0, 1, -1), "se": (1, 1, 1, 1), "sw": (0, 1, -1, 1)}.items():
        lbl = tk.Label(f, image=imgs[k], bd=0, highlightthickness=0, bg=fill)
        lbl.place(relx=rx, rely=ry, x=dx, y=dy, anchor=k); f._ax_corners[k] = lbl
    f._ax_card = radius
    return f


def _corners(r, fill, border, outside):
    key = ("corners", r, fill, border, outside)
    imgs = _cache.get(key)
    if imgs is None:
        big = Image.new("RGB", (2 * r * SS, 2 * r * SS), rgb(outside))
        ImageDraw.Draw(big).ellipse((0, 0, 2 * r * SS - 1, 2 * r * SS - 1), fill=fill, outline=border, width=SS)
        small = big.resize((2 * r, 2 * r), Image.LANCZOS)
        boxes = {"nw": (0, 0, r, r), "ne": (r, 0, 2 * r, r), "se": (r, r, 2 * r, 2 * r), "sw": (0, r, r, 2 * r)}
        imgs = _cache[key] = {k: ImageTk.PhotoImage(small.crop(b)) for k, b in boxes.items()}
    return imgs


# colour options of plain Tk widgets that the palette sets
_COLOR_OPTS = ("background", "foreground", "activebackground", "activeforeground", "highlightbackground",
               "highlightcolor", "selectcolor", "troughcolor", "insertbackground", "selectbackground",
               "inactiveselectbackground", "disabledforeground", "selectforeground")
# when two palette entries share a colour, the first listed wins (the rest are fixed by option below)
_ORDER = ("BG", "PANEL", "FG", "DIM", "LINE", "BTN", "HOV", "ACC", "ON_ACC", "KNOB_OFF", "LOG_BG", "LOG_DIM",
          "GOOD", "TAGLINE", "CELL_OFF", "ART_LINE")
_BY_OPTION = {"activebackground": "HOV", "activeforeground": "ON_ACC", "selectbackground": "HOV",
              "inactiveselectbackground": "HOV"}


def rescale(root):
    """The interface size changed (set_scale first): redraw what was drawn for one size, in place.
    Fonts follow by themselves (named fonts); widgets created with sizes in pixels keep their base
    values in w._ax_px = {option: base px}."""
    stack = [root]
    while stack:
        w = stack.pop()
        if isinstance(w, (Pill, Switch, ColorDot)):
            w.redraw(); continue
        for opt, (base, low) in getattr(w, "_ax_px", {}).items():
            w.configure({opt: max(low, px(base))})
        if getattr(w, "_ax_card", None):
            fill = w.cget("background"); border = w.cget("highlightbackground")
            imgs = _corners(px(w._ax_card), fill, border, w.master.cget("background"))
            for k, lbl in w._ax_corners.items(): lbl.configure(image=imgs[k])
        stack.extend(c for c in w.winfo_children() if c not in getattr(w, "_ax_corners", {}).values())


def sized(widget, **base):
    """Remember sizes given in base pixels (option=n or option=(n, minimum)) and apply them scaled."""
    widget._ax_px = {k: (v if isinstance(v, tuple) else (v, 1)) for k, v in base.items()}
    for opt, (b, low) in widget._ax_px.items(): widget.configure({opt: max(low, px(b))})
    return widget


def restyle(root, old):
    """Recolour an already built window from palette `old` to the current one (set_theme first), in
    place: much faster than building it again. Plain widgets get their colour options mapped; the
    drawn widgets (pills, switches, colour dots, card corners) redraw themselves."""
    new = PAL
    vmap = {}
    for k in _ORDER: vmap.setdefault(old[k].lower(), new[k])
    special = {(opt, old[k].lower()): new[k] for opt, k in _BY_OPTION.items()}
    stack = [root]
    while stack:
        w = stack.pop()
        if isinstance(w, (Pill, Switch, ColorDot)):
            w.redraw()
            continue
        for opt in _COLOR_OPTS:
            try: v = str(w.cget(opt)).lower()
            except (tk.TclError, ValueError): continue
            nv = special.get((opt, v)) or vmap.get(v)
            if nv and nv.lower() != v:
                try: w.configure({opt: nv})
                except tk.TclError: pass
        if getattr(w, "_ax_card", None):  # rounded corners: drawn for the card and its surroundings
            fill = w.cget("background"); border = w.cget("highlightbackground")
            imgs = _corners(px(w._ax_card), fill, border, w.master.cget("background"))
            for k, lbl in w._ax_corners.items(): lbl.configure(image=imgs[k], bg=fill)
        stack.extend(c for c in w.winfo_children() if not getattr(c, "_ax_corner", False)
                     and c not in getattr(w, "_ax_corners", {}).values())


class Pill(tk.Label):
    """Rounded button. kind: normal | primary | ghost | quiet (no fill until hovered).
    set(text=..., sel=...) updates it; icon draws a small symbol instead of text."""

    def __init__(self, parent, text="", command=None, sel=False, kind="normal", font="AxFB",
                 padx=12, pady=6, width=None, radius=8, icon=None, abs_width=None, chars=None):
        super().__init__(parent, compound="center", bd=0, highlightthickness=0, padx=0, pady=0, font=font,
                         cursor="hand2" if command else "")
        self._a = dict(text=text, sel=sel, kind=kind, padx=padx, pady=pady, width=width, radius=radius,
                       icon=icon, hover=False, abs_width=abs_width, chars=chars)
        if command:
            self.bind("<Button-1>", lambda e: command())
            self.bind("<Enter>", lambda e: self._hover(True))
            self.bind("<Leave>", lambda e: self._hover(False))
        self.set()

    def _hover(self, on):
        self._a["hover"] = on; self.set()

    def redraw(self):
        self.set()

    def set(self, text=None, sel=None):
        a = self._a
        if text is not None: a["text"] = text
        if sel is not None: a["sel"] = sel
        bg = self.master.cget("bg")
        f = tkfont.nametofont(str(self.cget("font")))
        lines = a["text"].split("\n") if a["text"] else [""]
        tw = max(f.measure(l) for l in lines)
        th = f.metrics("linespace") * len(lines)
        if a["chars"]: w = f.measure("0") * a["chars"] + 2 * px(a["padx"])
        else: w = a["abs_width"] or (px(a["width"]) if a["width"] else tw + 2 * px(a["padx"]))
        h = th + 2 * px(a["pady"])
        if a["icon"]: w = h = max(h, px(34))
        outline = None
        if a["sel"] or a["kind"] == "primary":
            fill, fg = PAL["ACC"], PAL["ON_ACC"]
        elif a["kind"] == "ghost":
            fill, fg, outline = (PAL["HOV"] if a["hover"] else bg), PAL["FG"], PAL["LINE"]
        elif a["kind"] == "quiet":
            fill, fg = (PAL["HOV"] if a["hover"] else bg), PAL["FG"]
        else:
            fill, fg = (PAL["HOV"] if a["hover"] else PAL["BTN"]), PAL["FG"]
        if a["icon"]:
            r = px(a["radius"]); icon = a["icon"]
            def d(dr, s):
                dr.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=r * s, fill=fill, outline=outline,
                                     width=s if outline else 0)
                _icon(dr, s, icon, w * s // 2, h * s // 2, px(15), PAL["DIM"])
            img = _photo(("icon", icon, w, h, r, fill, bg, outline), w, h, bg, d)
        else:
            img = rounded(w, h, px(a["radius"]), fill, bg, outline)
        self._img = img
        super().configure(image=img, text=a["text"], fg=fg, bg=bg, activebackground=bg)


class Switch(tk.Label):
    """On/off switch. set(on) updates it; the command runs on click."""

    def __init__(self, parent, command=None, on=False, small=False):
        super().__init__(parent, bd=0, highlightthickness=0, cursor="hand2")
        self._small, self._on, self._anim = small, bool(on), None
        if command: self.bind("<Button-1>", lambda e: command())
        self._draw(1.0 if on else 0.0)

    STEPS = 6          # frames of the knob slide (~100 ms)

    def redraw(self):
        self._anim = None; self._draw(1.0 if self._on else 0.0)

    def set(self, on):
        on = bool(on)
        changed = on != self._on
        self._on = on
        if changed and ANIMATE and self.winfo_ismapped():
            self._anim = 1; self._step(); return
        self._anim = None; self._draw(1.0 if on else 0.0)

    def _step(self):
        if self._anim is None: return
        t = self._anim / self.STEPS
        t = t * t * (3 - 2 * t)                       # ease in-out
        self._draw(t if self._on else 1 - t)
        if self._anim < self.STEPS:
            self._anim += 1; self.after(16, self._step)
        else: self._anim = None

    def _draw(self, pos):
        """pos 0 = off (knob left), 1 = on; colours switch half way."""
        w, h = (px(30), px(18)) if self._small else (px(38), px(22))
        bg = self.master.cget("bg")
        lit = pos >= 0.5
        track = PAL["ACC"] if lit else PAL["LINE"]
        knob = PAL["ON_ACC"] if lit else PAL["KNOB_OFF"]
        def d(dr, s):
            dr.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=h * s // 2, fill=track)
            m = px(3) * s; kd = h * s - 2 * m
            x = m + (w * s - 2 * m - kd) * pos
            dr.ellipse((x, m, x + kd, m + kd), fill=knob)
        self._img = _photo(("sw", round(pos, 3), w, h, track, knob, bg), w, h, bg, d)
        super().configure(image=self._img, bg=bg)


class ColorDot(tk.Label):
    """A round colour swatch. configure(bg=color) changes the colour (so existing code keeps working)."""

    def __init__(self, parent, color="#ffffff", size=30, command=None):
        super().__init__(parent, bd=0, highlightthickness=0, cursor="hand2" if command else "")
        self._color, self._size, self._theme_key = color, size, None
        if command: self.bind("<Button-1>", lambda e: command())
        self._draw()

    def show_theme(self, key):
        """Show a palette colour (e.g. "LINE" for "off") that follows the theme, unlike a chosen colour."""
        self._theme_key = key; self._color = PAL[key]; self._draw()

    def redraw(self):
        if self._theme_key: self._color = PAL[self._theme_key]
        self._draw()

    def _draw(self):
        n = px(self._size); bg = self.master.cget("bg"); color = self._color
        def d(dr, s):
            dr.ellipse((0, 0, n * s - 1, n * s - 1), fill=color, outline=PAL["LINE"], width=s)
        self._img = _photo(("cdot", color, n, bg, THEME), n, n, bg, d)
        super().configure(image=self._img, bg=bg)

    def configure(self, cnf=None, **kw):
        if "bg" in kw:   # a chosen colour: stays as it is when the theme changes
            self._color = kw.pop("bg"); self._theme_key = None; self._draw()
        if kw or cnf: return super().configure(cnf, **kw)
    config = configure


class Mascot(tk.Label):
    """The small looping animation at the bottom of the left panel (mascot_art.py): one for each theme,
    painted in the panel colours. Built to cost nothing when nobody looks at it:
    - frames are made only when it is first shown, for the current theme and size, and freed by
      stop(free=True) (window in the tray) - in the tray it holds no images and no timer;
    - it plays only while run(True) (window visible and active, enough room); otherwise no timer runs;
    - one Tk timer per frame change (light theme: 4 frames per 0.45 s, dark: ~8 per second)."""

    def __init__(self, parent):
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("bg"))
        self._frames, self._times, self._key = None, None, None
        self._i, self._after, self._on, self._height = 0, None, False, None

    HEIGHT = 150  # px at 100 % (mascot_art.py frames are this tall): the largest it is shown
    MIN_HEIGHT = 72  # smaller than this (px at 100 %) it is not worth showing

    def fit(self, width, height):
        """Pixel height to show it at in a free area of width x height (the current theme's picture,
        at most HEIGHT at the interface size), or 0 when it does not fit. Cheap: decodes nothing."""
        import mascot_art
        (w, h), _, _ = mascot_art.MASCOT["light" if THEME == "light" else "dark"]
        size = min(px(self.HEIGHT), height, int(width * h / w))
        return size if size >= px(self.MIN_HEIGHT) else 0

    def set_height(self, height):
        """Show it at this pixel height (from fit); redrawn now if it is already shown."""
        if height != self._height:
            self._height = height
            self.refresh()

    def _build(self):
        """PhotoImages for the current theme / size / background (once; again only when one changes)."""
        bg = self.cget("bg")
        key = (THEME, SCALE, bg, self._height)
        if key == self._key: return
        import mascot_art  # decoded only here, never at start
        (w, h), times, data = mascot_art.MASCOT["light" if THEME == "light" else "dark"]
        strip = Image.open(io.BytesIO(base64.b64decode("".join(data)))).convert("L")
        sh = self._height or px(h)
        sw = max(1, round(w * sh / h))
        lo, hi = rgb(bg), rgb(PAL["FG"])
        luts = [[round(a + (b - a) * v / 255) for v in range(256)] for a, b in zip(lo, hi)]
        frames = []
        for i in range(len(times)):
            ink = strip.crop((i * w, 0, (i + 1) * w, h))
            if (sw, sh) != (w, h): ink = ink.resize((sw, sh), Image.LANCZOS)
            frames.append(ImageTk.PhotoImage(Image.merge("RGB", [ink.point(t) for t in luts])))
        self._frames, self._times, self._key = frames, times, key
        self._i %= len(frames)
        super().configure(image=frames[self._i], width=sw, height=sh)

    def run(self, on):
        """Shown: play (True) or hold still on the current frame (False). Holding costs nothing."""
        self._on = on
        self._build()
        if not on: self._cancel()
        elif self._after is None: self._after = self.after(self._times[self._i], self._tick)

    def refresh(self):
        """Theme or interface size changed: redraw now (also while held still)."""
        if self._frames is not None: self._build()

    def stop(self, free=False):
        self._on = False; self._cancel()
        if free:  # window in the tray / no room: drop the images
            super().configure(image="")
            self._frames = self._key = None

    def _cancel(self):
        if self._after is not None: self.after_cancel(self._after); self._after = None

    def _tick(self):
        self._after = None
        if not self._on or not self._frames: return
        self._build()  # no-op unless the theme or size changed
        self._i = (self._i + 1) % len(self._frames)
        super().configure(image=self._frames[self._i])
        self._after = self.after(self._times[self._i], self._tick)
