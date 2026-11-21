# Aerox Lite

A lightweight replacement for SteelSeries GG for the **SteelSeries Aerox 3 Wireless** (2020/2022, Snow/Ghost) on Windows.

Features: tray icon with battery level, CPI levels, polling rate, sleep/dim timers, button bindings, lighting (including software effects), macros, and optional modules (directional sensitivity, multi-click, smart battery).

The device protocol is based on the open-source [rivalcfg](https://github.com/flozz/rivalcfg) project.

> **Before you start:** close SteelSeries GG / SteelSeries Engine and remove them from autostart. GG overwrites the mouse lighting and settings.

## Download

> **New to this?** Follow [HOW-TO-INSTALL.txt](HOW-TO-INSTALL.txt), a simple step-by-step guide. It is also included in the download.

Get `AeroxLite-windows.zip` (the program plus the guide) or just `AeroxLite.exe` from the **Releases** page. GitHub Actions builds both from this repository.

## Build from source

1. Install [Python](https://www.python.org/downloads/windows/) 3.12+ for Windows (with Tcl/Tk) and add it to `PATH`.
2. Exit any running Aerox Lite and SteelSeries GG.
3. Run `build.bat`. It creates an isolated `.venv`, installs dependencies, runs the tests and builds `dist\AeroxLite.exe`.
4. Start `run.bat` or `dist\AeroxLite.exe`.

If you used autostart with an older version, toggle it off and on again so Windows registers the new EXE path.

| File | Location |
|---|---|
| Config | `%APPDATA%\AeroxLite\config.json` |
| Log | `%APPDATA%\AeroxLite\log.txt` (rotated at 512 KiB) |

Software lighting effects and macros work only while the app is running (in the tray). The static color and the hardware rainbow keep working without the app after **Save to mouse**.

## Modules

Each module on the **Modules** tab has its own toggle. Disabled modules are not loaded.

- **Directional sensitivity** requires [Raw Accel](https://github.com/a1xd/rawaccel) 1.6+.
  1. Click **RAW ACCEL FOLDER**. The app searches Downloads, Desktop, Documents and Program Files. If it finds nothing, choose the folder that contains `writer.exe`. `settings.json` appears after you press Apply in Raw Accel once.
  2. Click **CALIBRATE** and complete 32 flicks, then click **Save and close**. Running it 2–3 times gives better results.
  3. Turn the toggle on. Turning it off restores your Raw Accel settings. Your `settings.json` is never modified.
- **Multi-click (left / right)**: each button has its own toggle and a ×2…×6 slider. A press shorter than the tap threshold (60–400 ms) sends multiple clicks; a longer press is a normal hold. Works in all applications.
- **Smart battery**: shows a runtime forecast. Below 25%, you get a notification and a temporary power saver (500 Hz, lighting off). Everything is restored when charging or at ≥30%.

The tray item **Multi-click & directional sens** turns those two modules off and back on.

## Macros

One action per line:

```
ctrl+c        key combination
enter         single key
down shift    hold key
up shift      release key
wait 50       delay, ms
text Hello    type text
click left    left / right / middle click
# ...         comment
```

Assign a macro to a mouse button under **Actions → Macros**.

## Development

```
python -X utf8 -m unittest discover -s tests -v
```

There are 36 hardware-independent tests; HID and the tray are mocked. The real GUI, Win32 Raw Input/SendInput and the mouse itself still need a manual check on Windows.

### Releasing

```
git tag v5.0.0
git push origin v5.0.0
```

The workflow runs the tests, builds the EXE and attaches it to a GitHub Release.

## Disclaimer

This is an unofficial project, not affiliated with or endorsed by SteelSeries. "SteelSeries" and "Aerox" are trademarks of their respective owners. Use at your own risk.

## License

[MIT](LICENSE). The bundled EXE also contains third-party libraries under their own licenses: [hidapi](https://github.com/trezor/cython-hidapi) (BSD option), [pystray](https://github.com/moses-palmer/pystray) (LGPL-3.0), [Pillow](https://github.com/python-pillow/Pillow) (MIT-CMU), and [PyInstaller](https://pyinstaller.org) bootloader (GPL with a bundling exception).
