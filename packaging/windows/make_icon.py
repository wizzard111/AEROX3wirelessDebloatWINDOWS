"""Rebuild packaging/windows/AeroxLite.ico: the app mark from the window header (ui_theme.logo_image,
a mouse on a dark rounded square), drawn separately at each size so small sizes stay sharp.
Usage: python packaging/windows/make_icon.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import ui_theme  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main():
    imgs = [ui_theme.logo_image(n, "#18181B", "#FFFFFF") for n in SIZES]
    out = Path(__file__).resolve().parent / "AeroxLite.ico"
    imgs[-1].save(out, format="ICO", sizes=[(n, n) for n in SIZES], append_images=imgs[:-1])
    print("written", out, out.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
