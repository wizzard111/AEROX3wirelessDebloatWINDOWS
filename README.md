# Aerox Lite

*In collaboration with [Claude](https://claude.ai).*

A lightweight, free replacement for SteelSeries GG on Windows. Made for the **SteelSeries Aerox 3 Wireless**
(2020 / 2022, Snow, Ghost) and now also for **65 other SteelSeries mice**: Rival, Sensei, Prime, Aerox 5 / 9,
Kana and Kinzu ([supported mice](#supported-mice)).

- **Battery** level in the tray icon and the window, with a forecast of the time left
- **CPI** levels, **polling rate**, **sleep and dim timers**
- **Buttons**: remap to another button, a key, a media key or a **macro**
- **Lighting** per zone, shown on a picture of your mouse in your colours; software effects on the Aerox 3
- **Modules**: multi-click, smart battery forecast and directional sensitivity
- Light and dark theme, interface size 50–200%, HiDPI screens
- Starts with Windows if you like; near-zero background cost; no account, no telemetry, no internet connection

The device protocol is based on the open-source [rivalcfg](https://github.com/flozz/rivalcfg) project.

> **Before you start:** close SteelSeries GG / SteelSeries Engine and remove them from autostart. GG overwrites the mouse lighting and settings.

## Install

> **New to this?** Follow [HOW-TO-INSTALL.txt](HOW-TO-INSTALL.txt), a simple step-by-step guide. It is also included in the download.

1. Download `AeroxLite-windows.zip` from **Releases** and extract it.
2. Double-click **Install Aerox Lite.bat**. No administrator rights are needed. The installer:
   1. Offers to quit SteelSeries GG.
   2. Installs the program to `%LOCALAPPDATA%\Programs\AeroxLite`.
   3. Adds a Start menu shortcut, and a desktop shortcut if you want one.
   4. Registers the app in **Settings → Apps**, so it can be uninstalled normally.
   5. Starts the app.

   The log is saved as `install.log`.

The same installer also works on the **source code**. Without a ready-made program it finds Python 3.10–3.14 with Tk, or offers to install the official one from python.org for your user only, then builds the app and installs it.

To remove the app, run `Uninstall Aerox Lite.bat`, or use **Settings → Apps → Aerox Lite → Uninstall**. It asks what to remove:

1. **Only the app.**
2. **Everything:** the app, its settings and the downloaded folder, including the installer and the uninstaller.

For scripted use there are `-AppOnly` and `-All`.

A standalone `AeroxLite.exe` is attached to each release too. It runs without installing, but starts more slowly because it unpacks itself on every start. The installed version is a folder and starts in about 0.2 s.

| File | Location |
|---|---|
| Program | `%LOCALAPPDATA%\Programs\AeroxLite\AeroxLite.exe` |
| Config | `%APPDATA%\AeroxLite\config.json` |
| Log | `%APPDATA%\AeroxLite\log.txt` (rotated at 512 KiB) |

Software lighting effects and macros work only while the app is running (in the tray). The static color and the hardware rainbow keep working without the app after **Save to mouse**.

## Disk space, memory and CPU

| | |
|---|---|
| Download | `AeroxLite-windows.zip` 12 MB, or the portable `AeroxLite.exe` 12 MB |
| On disk after installing | 25 MB in `%LOCALAPPDATA%\Programs\AeroxLite`; settings a few KB; log files at most 1 MB |
| Memory in the tray | 49 MB (29 MB of its own) |
| Memory with the window open | 56 MB (35 MB of its own) |
| CPU, in the tray or with the window open | about 0%: 16 ms of CPU time per minute |

The window is built only when you open it, and the app sleeps until something happens (a setting, the
mouse, a battery check every 30 s). Software lighting effects (breathing, wave, colour cycle) are the
exception: they keep sending colours to the mouse while they run.

*Measured on Windows 11 with an Aerox 3 Wireless connected (V5.0.1).*

## Project layout

| Path | Contents |
|---|---|
| `Install Aerox Lite.bat`, `Uninstall Aerox Lite.bat` | Installer and uninstaller |
| `src/` | Application source code |
| `packaging/windows/` | PyInstaller spec, build, install and uninstall scripts |
| `packaging/requirements*.txt` | Python dependencies |
| `tests/` | Unit tests |
| `docs/CHANGELOG.md` | Version history |

To build by hand, run `packaging\windows\build.bat`. The result is `build\dist\AeroxLite.exe`. To run it, use `packaging\windows\run.bat`.
un.bat`.

## Other SteelSeries mice

Aerox Lite also works with the other SteelSeries mice that [rivalcfg](https://github.com/flozz/rivalcfg) supports
(65 models, 76 USB IDs: Rival 3/5/100/110/300/310/500/600/650/700, Sensei, Prime, Aerox 5/9, Kana, Kinzu, ...; see [Supported mice](#supported-mice)).
Plug the mouse in and the app finds it by itself: nothing to download or install, the descriptions
of every supported model come with the app.

These mice get the same window as the Aerox 3, built from what each model can do:

- **Buttons** (left): remap any button to another button, CPI switch, scroll, a keyboard key, a
  media key or a **macro** (47 models; a macro is sent as one of the keys F13–F24, which the app
  turns into the macro, exactly as for the Aerox 3).
- **Picture** (centre): a drawing of your model with the parts that light up shown in the colours you
  pick, and tags (W wheel, LG logo, L1/R1 side strips, Z1 zones) that match the Lighting tab.
- **Settings**: CPI levels or presets and polling rate. A **wireless** mouse adds its battery level
  and forecast and the sleep / dim timers; a **wired** one shows a short summary instead.
- **Lighting**: every colour zone, "Set all", effects, reactive colour. **Modules** work as usual.

Changes apply at once; **Save to mouse** stores them in the mouse. Settings are remembered per model
and sent again on connect when "Apply settings on connect" is on. Software lighting effects stay an
Aerox 3 feature, and the Aerox 3 always uses its own code path.

## Supported mice

Plug the mouse in and Aerox Lite finds it by its USB ID; nothing to download or set up. The Aerox 3 Wireless
has the full feature set; the other models get every setting their device description offers.

<details>
<summary><b>All 66 models</b> (76 USB IDs) — click to open</summary>

| Model | Connection | Button remapping & macros | Colour zones | Battery | CPI |
|---|---|---|---|---|---|
| **Aerox 3 Wireless** (2020 / 2022, Snow, Ghost, CS2 Dragon Lore) | USB + 2.4 GHz | yes, plus macros | 3 + software effects | yes | 100–18000 |
| Aerox 3 | USB | yes | 3 | — | 200–8500 |
| Aerox 5 | USB | yes | 3 | — | 100–18000 |
| Aerox 5 Wireless | USB + 2.4 GHz | yes | 3 | yes | 100–18000 |
| Aerox 5 Wireless Destiny 2 Edition | USB + 2.4 GHz | yes | 3 | yes | 100–18000 |
| Aerox 5 Wireless Diablo IV Edition | USB + 2.4 GHz | yes | 3 | yes | 100–18000 |
| Aerox 9 Wireless | USB + 2.4 GHz | — | 3 | yes | 100–18000 |
| Aerox 9 Wireless WOW Edition | USB + 2.4 GHz | — | 3 | yes | 100–18000 |
| Prime | USB | yes | 1 | — | 50–18000 |
| Prime CS:GO Neo Noir Edition | USB | yes | 1 | — | 50–18000 |
| Prime Mini | USB | yes | 1 | — | 50–18000 |
| Prime Mini Wireless | USB + 2.4 GHz | yes | 1 | yes | 100–18000 |
| Prime Wireless | USB + 2.4 GHz | yes | 1 | yes | 100–18000 |
| Prime+ | USB | yes | 1 | — | 50–18000 |
| Prime Rainbow 6 Siege Black Ice Edition | USB | yes | 1 | — | 50–18000 |
| Rival | USB | yes | 2 | — | 50–6500 |
| Rival Dota 2 Edition | USB | yes | 2 | — | 50–6500 |
| Rival 3 | USB | yes | 4 | — | 200–8500 |
| Rival 3 (firmware v0.37.0.0) | USB | yes | 4 | — | 200–8500 |
| Rival 3 Gen 2 | USB | yes | 3 | — | 200–8500 |
| Rival 3 Wireless | 2.4 GHz | yes | — | yes | 100–18000 |
| Rival 3 Wireless Gen 2 | 2.4 GHz | yes | — | yes | 100–18000 |
| Rival 5 | USB | yes | 10 | — | 100–18000 |
| Rival 5 Destiny Edition | USB | yes | 10 | — | 100–18000 |
| Rival 95 | USB | — | — | — | 250–4000 |
| Rival 95 MSI Edition | USB | — | — | — | 250–4000 |
| Rival 95 PC Bang | USB | — | — | — | 250–4000 |
| Rival 100 | USB | — | 1 | — | 250–4000 |
| Rival 100 (Dell China) | USB | — | 1 | — | 250–4000 |
| Rival 100 Dota 2 Edition (Lenovo) | USB | — | 1 | — | 250–4000 |
| Rival 100 Dota 2 Edition (retail) | USB | — | 1 | — | 250–4000 |
| Rival 100 PC Bang | USB | — | — | — | 250–4000 |
| Rival 105 | USB | — | 1 | — | 250–4000 |
| Rival 106 | USB | — | 1 | — | 200–7200 |
| Rival 110 | USB | — | 1 | — | 200–7200 |
| Rival 300 | USB | yes | 2 | — | 50–6500 |
| Rival 300 Acer Predator Edition | USB | yes | 2 | — | 50–6500 |
| Rival 300 CS:GO Fade Edition | USB | yes | 2 | — | 50–6500 |
| Rival 300 CS:GO Fade Edition (stm32) | USB | yes | 2 | — | 50–6500 |
| Rival 300 CS:GO Hyper Beast Edition | USB | yes | 2 | — | 50–6500 |
| Rival 300 Evil Geniuses Edition | USB | yes | 2 | — | 50–6500 |
| Rival 300 Fallout 4 Edition | USB | yes | 2 | — | 50–6500 |
| Rival 300 HP OMEN Edition | USB | yes | 2 | — | 50–6500 |
| Rival 300S | USB | — | 1 | — | 200–7200 |
| Rival 310 | USB | yes | 2 | — | 100–12000 |
| Rival 310 CS:GO Howl Edition | USB | yes | 2 | — | 100–12000 |
| Rival 310 PUBG Edition | USB | yes | 2 | — | 100–12000 |
| Rival 500 | USB | yes | 2 | — | 100–12000 |
| Rival 600 | USB | yes | 8 | — | 100–12000 |
| Rival 600 Dota 2 Edition | USB | yes | 8 | — | 100–12000 |
| Rival 650 Wireless | USB + 2.4 GHz | yes | — | yes | 100–12000 |
| Rival 700 | USB | — | 2 | — | 100–12000 |
| Rival 710 | USB | — | 2 | — | 100–12000 |
| Sensei TEN | USB | yes | 2 | — | 50–18000 |
| Sensei TEN CS:GO Neon Rider Edition | USB | yes | 2 | — | 50–18000 |
| Sensei [RAW] | USB | yes | — | — | 90–5670 |
| Sensei [RAW] CoD Black Ops II Edition | USB | yes | — | — | 90–5670 |
| Sensei [RAW] Diablo III Edition | USB | yes | — | — | 90–5670 |
| Sensei [RAW] Heroes of the Storm Edition | USB | yes | — | — | 90–5670 |
| Sensei [RAW] World of Tanks Edition | USB | yes | — | — | 90–5670 |
| Sensei [RAW] Guild Wars 2 Edition | USB | yes | — | — | 90–5670 |
| Sensei 310 | USB | yes | 2 | — | 100–12000 |
| Kana v2 | USB | — | — | — | 400–4000 |
| Kinzu v2 | USB | — | — | — | 400–3200 |

</details>

"Button remapping & macros: —" means the mouse does not let its buttons be remapped from a computer
program. Colour zones are the parts that light up and can be given a colour. The device descriptions come
from [rivalcfg](https://github.com/flozz/rivalcfg); a model added there can be added here too.

## Light and dark theme

The switch at the top left (moon / sun) changes between the dark and the light look. The choice is saved.

## Interface size

Use **A−** and **A+** at the top right of the window to make text, buttons and the mouse picture smaller or larger (50%–200%, limited by the screen size). The choice is saved.

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

There are 43 hardware-independent tests; HID and the tray are mocked. The real GUI, Win32 Raw Input/SendInput and the mouse itself still need a manual check on Windows.

### Releasing

```
git tag v5.0.1
git push origin v5.0.1
```

The workflow runs the tests, builds and self-tests the EXE, and attaches `AeroxLite-windows.zip` (installer + program) and `AeroxLite.exe` to a GitHub Release.

## Disclaimer

This is an unofficial project, not affiliated with or endorsed by SteelSeries. "SteelSeries" and "Aerox" are trademarks of their respective owners. Use at your own risk.

## License

[MIT](LICENSE). The bundled EXE also contains third-party libraries under their own licenses: [hidapi](https://github.com/trezor/cython-hidapi) (BSD option), [rivalcfg](https://github.com/flozz/rivalcfg) (WTFPL, mouse descriptions), [pystray](https://github.com/moses-palmer/pystray) (LGPL-3.0), [Pillow](https://github.com/python-pillow/Pillow) (MIT-CMU), and [PyInstaller](https://pyinstaller.org) bootloader (GPL with a bundling exception).
