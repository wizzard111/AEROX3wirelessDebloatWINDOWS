"""Theme and size changes in place, and the animations (needs a display; skipped without one)."""
from pathlib import Path
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import tkinter as tk
import ui_theme

try:
    if os.environ.get("CI") and sys.platform == "darwin":
        raise tk.TclError("no window server for Tk on a CI Mac")   # Tk may abort instead of raising there
    _root = tk.Tk(); _root.withdraw()
    from tkinter import font as _tkfont
    _FONTS = [_tkfont.Font(root=_root, name=n, size=9) for n in ("AxF", "AxFB", "AxFS", "AxFT", "AxFU", "AxFH")]
except tk.TclError:  # pragma: no cover
    _root = None


@unittest.skipIf(_root is None, "no display")
class InPlaceTests(unittest.TestCase):
    def setUp(self):
        ui_theme.set_theme("dark"); ui_theme.set_scale(1.0)
        self.top = tk.Toplevel(_root, bg=ui_theme.PAL["BG"])
        self.card = ui_theme.card(self.top, radius=12); self.card.pack()
        P = ui_theme.PAL
        self.lbl = tk.Label(self.card, text="x", bg=P["PANEL"], fg=P["DIM"]); self.lbl.pack()
        self.mb = tk.Menubutton(self.card, bg=P["BTN"], fg=P["FG"], activebackground=P["HOV"]); self.mb.pack()
        self.pill = ui_theme.Pill(self.card, "Save", lambda: None, kind="primary"); self.pill.pack()
        self.sw = ui_theme.Switch(self.card, None, on=True); self.sw.pack()
        self.dot = ui_theme.ColorDot(self.card, P["LINE"], 20); self.dot.show_theme("LINE"); self.dot.pack()
        self.zone = ui_theme.ColorDot(self.card, "#ffffff", 20); self.zone.pack()   # a colour the user chose
        self.spacer = ui_theme.sized(tk.Frame(self.card), height=12); self.spacer.pack()

    def tearDown(self):
        self.top.destroy(); ui_theme.set_theme("dark"); ui_theme.set_scale(1.0)

    def test_restyle_maps_every_colour(self):
        old = dict(ui_theme.PAL); ui_theme.set_theme("light"); ui_theme.restyle(self.top, old)
        L = ui_theme.PALETTES["light"]
        self.assertEqual(self.top.cget("bg").upper(), L["BG"])
        self.assertEqual(self.card.cget("bg").upper(), L["PANEL"])
        self.assertEqual(self.card.cget("highlightbackground").upper(), L["LINE"])
        self.assertEqual(self.lbl.cget("fg").upper(), L["DIM"])
        self.assertEqual(self.mb.cget("bg").upper(), L["BTN"])
        self.assertEqual(self.mb.cget("activebackground").upper(), L["HOV"])   # same dark colour as LINE
        self.assertEqual(self.dot._color.upper(), L["LINE"])                  # "off" swatch follows the theme
        self.assertEqual(self.zone._color.lower(), "#ffffff")                  # a chosen colour never changes
        self.assertEqual(self.pill.cget("bg").upper(), L["PANEL"])

    def test_chosen_white_survives_light_to_dark(self):
        """#FFFFFF is also the light theme's card colour: it must not be taken for a theme colour."""
        ui_theme.set_theme("light"); self.zone.config(bg="#ffffff")
        old = dict(ui_theme.PAL); ui_theme.set_theme("dark"); ui_theme.restyle(self.top, old)
        self.assertEqual(self.zone._color.lower(), "#ffffff")
        self.assertEqual(self.dot._color.upper(), ui_theme.PALETTES["dark"]["LINE"])

    def test_rescale_redraws_sizes(self):
        w0 = self.pill._img.width(); h0 = int(self.spacer.cget("height"))
        ui_theme.set_scale(2.0); ui_theme.rescale(self.top)
        self.assertEqual(int(self.spacer.cget("height")), 24)
        self.assertEqual(self.pill._img.width() - w0, 24)   # padding 2 x 12 px doubled (fonts are resized by the app)
        self.assertEqual(h0, 12)

    def test_switch_slides_only_on_screen(self):
        frames = []
        orig = self.sw._draw
        self.sw._draw = lambda pos: (frames.append(pos), orig(pos))[1]
        self.sw.set(False)                       # not mapped (withdrawn root): jumps, no frames queued
        self.assertEqual(frames, [0.0])
        self.sw.redraw()                         # redraw never animates
        self.assertEqual(frames[-1], 0.0)


@unittest.skipIf(_root is None, "no display")
class MascotTests(unittest.TestCase):
    """The panel animation: frames only while shown, a timer only while playing, theme colours."""
    def setUp(self):
        ui_theme.set_theme("dark"); ui_theme.set_scale(1.0)
        self.top = tk.Toplevel(_root, bg=ui_theme.PAL["PANEL"])
        self.m = ui_theme.Mascot(self.top); self.m.pack()

    def tearDown(self):
        self.m.stop(free=True); self.top.destroy()

    def test_assets_decode(self):
        import mascot_art, base64, io
        from PIL import Image
        for name, ((w, h), times, data) in mascot_art.MASCOT.items():
            strip = Image.open(io.BytesIO(base64.b64decode("".join(data))))
            self.assertEqual(strip.size, (w * len(times), h), name)
            self.assertEqual(h, ui_theme.Mascot.HEIGHT)

    def test_fits_the_free_space(self):
        m, full = self.m, ui_theme.Mascot.HEIGHT
        self.assertEqual(m.fit(1000, 1000), full)            # never larger than at 100 %
        self.assertEqual(m.fit(1000, 100), 100)              # shrinks to the free height
        self.assertEqual(m.fit(180, 1000), 180 * 150 // 270)  # and to the free width (dark: 270 x 150)
        self.assertEqual(m.fit(1000, ui_theme.Mascot.MIN_HEIGHT - 1), 0)  # too small: not shown
        m.set_height(100); m.run(False)
        self.assertEqual((m._frames[0].width(), m._frames[0].height()), (180, 100))
        self.assertIsNone(m._after)

    def test_nothing_until_shown(self):
        self.assertIsNone(self.m._frames); self.assertIsNone(self.m._after)

    def test_play_hold_free(self):
        self.m.run(True)
        self.assertEqual(len(self.m._frames), len(__import__("mascot_art").MASCOT["dark"][1]))
        self.assertIsNotNone(self.m._after)
        self.m.run(False)                        # held still: picture stays, no timer
        self.assertIsNotNone(self.m._frames); self.assertIsNone(self.m._after)
        self.m.run(True); self.m.stop(free=True)  # tray: no timer, no images
        self.assertIsNone(self.m._frames); self.assertIsNone(self.m._after)
        self.assertEqual(str(self.m.cget("image")), "")

    def test_follows_theme_and_size(self):
        self.m.run(False)
        dark = self.m._frames
        ui_theme.set_theme("light"); self.m.configure(bg=ui_theme.PAL["PANEL"]); self.m.refresh()
        self.assertIsNot(self.m._frames, dark)
        self.assertEqual(len(self.m._frames), len(__import__("mascot_art").MASCOT["light"][1]))
        ui_theme.set_scale(1.5); self.m.refresh()
        self.assertEqual(self.m._frames[0].height(), round(ui_theme.Mascot.HEIGHT * 1.5))


if __name__ == '__main__':
    unittest.main()
