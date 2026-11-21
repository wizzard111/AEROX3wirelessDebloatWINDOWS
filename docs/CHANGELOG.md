# Changelog

## V5.0.1

### Highlights
- **65 more SteelSeries mice.** Rival, Sensei, Prime, Aerox 5 / 9, Kana and Kinzu models (76 USB IDs)
  are recognised automatically and get the same window as the Aerox 3, with a picture of your model.
  Nothing extra to download. See "Supported mice" in the README.
- **New look** with a light and a dark theme, an interface size control and small animations.
- **Starts in ~0.2 s instead of ~4.5 s:** the installed program is a folder instead of a single EXE that unpacked itself (and was scanned by the antivirus) on every start.

### Other SteelSeries mice
- Found by their USB ID, from the open device descriptions of
  [rivalcfg](https://github.com/flozz/rivalcfg); the Aerox 3 Wireless keeps its own full-featured code.
- Window built for each model: buttons on the left, a picture of the mouse with its lit zones in your
  colours in the middle, and the Settings, Lighting and Modules tabs on the right.
- Button remapping on 47 models: another button, CPI switch, scroll, a keyboard key, a media key or a
  macro.
- CPI levels or presets, polling rate, every colour zone with "Set all", lighting effects, reactive
  colour.
- Wireless mice show the battery level and forecast and the sleep / dim timers; wired mice show a short
  summary instead.
- Settings are remembered per model and sent again on connect.

### Look and feel
- Rounded cards, switches, pill buttons and tabs, round colour swatches, an app icon, clearer button
  names (Left button -> Left click), a battery indicator and a connection chip in the header.
- Light and dark theme: the switch at the top left changes it at once; the choice is saved.
- Interface size: A- / A+ at the top right scale text, buttons and the mouse picture (50-200%, limited
  by the screen).
- Windows display scaling (125%, 150%, ...) enlarges the mouse picture and the window too.
- The window never squeezes its content: columns cannot slide over the mouse picture, and the right
  column keeps one width for all tabs.
- Activity shows the last two events; the full log opens on demand. The mouse sensor log is for one
  session: it is always off when the app starts.
- Small animations, only while something changes: switches slide, the theme switch slides before the
  colours change, and a new colour fades in on the mouse picture.

### Faster and leaner
- Near-zero background cost: threads and the window sleep until something happens (idle wakeups
  ~47/s -> under 1/s, idle CPU ~0); the mouse picture is redrawn only when it changes and only while
  visible.
- Mouse input is read only while a feature needs it (macros, multi-click, smart lighting, the
  visible sensor log). Multi-click uses Raw Input instead of a low-level mouse hook written in
  Python, so the cursor cannot stutter; the 1 ms timer is requested only during a click burst.
- A newly plugged-in mouse is noticed at once through Windows device notifications.
- Theme and interface size change in place (theme ~0.8 s -> ~0.2 s); switching tabs takes ~20 ms.
- At autostart the app starts in the tray and builds its window only when first opened
  (~0.65 s -> ~0.1 s of start-up work).
- rivalcfg and the pictures of other mice load only when such a mouse is plugged in; one USB scan per
  check; unplugging a mouse is noticed at once.
- Smaller build: unused image codecs, colour management, OpenSSL and Tcl time-zone data are left out;
  bytecode is optimised.

### Windows
- The installed program is a folder (%LOCALAPPDATA%\Programs\AeroxLite) and starts in ~0.2 s.
  The portable AeroxLite.exe is still attached to releases (12 MB, was 20 MB).
- Releases also ship AeroxLite-windows.zip (installer, program and guide).

### Install and uninstall
- "Install Aerox Lite.bat": double-click, no administrator rights. Installs the program, adds
  Start menu (and optional desktop) shortcuts, registers it in Settings > Apps, removes the
  downloaded-file mark so SmartScreen does not ask on every start, repoints an old "Start with
  Windows" entry and starts the app. From source it finds or installs Python and builds first.
- "Uninstall Aerox Lite.bat" or Settings > Apps > Uninstall removes it again.
- The installer and the uninstaller close only the installed copy, never one running elsewhere.
- The uninstaller asks whether to remove only the app or everything (settings and the downloaded
  folder too).
- HOW-TO-INSTALL.txt: a step-by-step guide, included in the download.
- The repository root and the download hold only the installer, the uninstaller and the guide.

### Smaller fixes
- When the mouse cannot be opened, the log says why (no SteelSeries device, wrong interface, or the
  exact error with a permission hint).
- Saving or deleting a macro no longer leaks the old button menus; a failing input callback no longer
  stops the listener; the SteelSeries GG check no longer delays start-up.
- The SteelSeries GG check no longer fails silently when Windows lists processes in a non-UTF-8
  code page.
- Every build is self-tested before it is packaged.

### Size and resource use
- Download: AeroxLite-windows.zip 12 MB, portable AeroxLite.exe 12 MB; 25 MB on disk after installing.
- Memory: 49 MB in the tray (29 MB of its own), 56 MB with the window open (35 MB of its own).
- CPU: about 0% in the tray and with the window open (16 ms of CPU time per minute).
- Measured on Windows 11 with an Aerox 3 Wireless connected.

## V5 — public GitHub release
- English-only: the RU/EN switch and the Russian UI were removed; all UI text, logs,
  notifications, comments and docs are in English. A `language` key left in an old
  config is ignored.
- Macro scripts: the Russian-language command aliases for `wait` and `text` were removed.
- MIT license, GitHub Actions build (tests + PyInstaller EXE, attached to tagged releases).

## V5 — optimizations
- Removed the "Everywhere / Minecraft only" choice: multi-click works in all applications.
- Removed the foreground-process check from the low-level mouse hook.
- RGB: no HID commands are sent for zones whose color did not change.
- Smart lighting: when inactive, its thread polls 4 times/s instead of 20.
- Tray preview refreshes at most once per second.
- Existing configs are kept; obsolete `only_apps` / `apps` keys are ignored.

## V5 — modules
- Fixes after the first test: the tray item toggles only multi-click and directional
  sensitivity; the "RAW ACCEL FOLDER" button searches for Raw Accel automatically first;
  the battery forecast is shown immediately (estimate) and then learns from 5% step changes.
- Modules tab: every module has its own toggle. A disabled module is not imported at
  startup and uses no resources. State is stored in %APPDATA%\AeroxLite
  (directional_state.json, rclick.json, smartbattery.json).
- Directional sensitivity: calibration mini-game (8 directions x 4 flicks, Raw Input,
  cursor confined to the window) in a separate process (`AeroxLite.exe --calibrate`,
  before the mutex) so it does not interfere with the main app's Raw Input. Applied via
  Raw Accel 1.6+: a copy of your settings.json with Output DPI, Y/X, L/R and U/D
  (→ ↓ ← ↑) is passed to writer.exe. Your settings.json is never changed; off =
  writer.exe settings.json. The profile is re-applied when Aerox Lite starts (after a
  reboot the driver loads its own settings).
- Left/right multi-click: each button has its own toggle and ×2…×6 slider; the tap
  threshold is adjustable (60–400 ms). Short press = N clicks, holding works as usual.
  The WH_MOUSE_LL hook is installed only while the module is on; physical input is never
  swallowed and injected clicks (including macros) are ignored.
- Smart battery: runtime forecast in the status bar and tray (based on actual discharge,
  PC downtime excluded). Below 25% and not charging: a "battery low" notification and a
  temporary saver (500 Hz, lighting off) without changing the config; "Save to mouse"
  during the saver writes the real settings to mouse memory. Restored on charging or ≥30%.
- Tray: one item turns the modules off and restores exactly those that were on.
- 17 new tests (36 total).
- Fixed before release: the battery forecast lost discharge segments with sparse samples.

## V4 HID padding hotfix
- Accept successful Windows HIDAPI writes padded to the output report length.
  Exact byte-count equality caused false disconnects on the Aerox dongle.
- Preserve short/zero/failed-write checks and include actual counts in errors.
- Validate probe/battery writes through the same helper.
- Add three regression tests; 19 tests now pass.

## V4 encoding hotfix
- Explicit UTF-8 in every test file read; Windows CP1251 no longer corrupts
  macro source or breaks translation checks. Build commands enable UTF-8 mode.

## V4
- RU/EN runtime switch, persisted language, translated UI/tray/editor/errors.
  An unsaved macro draft is retained when switching languages; old log lines
  and user-provided names/scripts remain in their original language.
- Validate imported config: CPI levels (1–5), active level, polling, timers,
  color strings, modes, macro slots and bindings. Unknown/invalid values
  fall back to defaults. V3 settings remain compatible.
- Atomically replace config through a temporary file, flush/fsync and replace.
  Disk errors are logged and shown rather than claiming successful saving.
- Queue immutable configuration snapshots for settings application.
  Hold the HID lock across entire apply/effect/smart-light transactions.
- Only accept battery reports matching the requested command. Bound draining
  to 64 reports per call; reject partial HID command writes and reconnect.
- Show saving-in-progress until the save command has been sent successfully.
- Persist effect speed changes. Reject adding more than five CPI levels.
- Monotonic timing, interruptible thread waits, stop Raw Input and macro test
  threads on exit; restore a static fallback for software lighting.
- Thread-safe rotating logger, capped UI queue work per tick, skip mouse art
  rendering while hidden, and redraw the tray icon only when state changes.
- Raw Input startup error reporting, synchronized sensor counters, device
  cache refresh on device changes, explicit Win32 teardown/prototypes.
- Macro parser supports tabs, text injection supports UTF-16 surrogate pairs,
  SendInput failures are reported; release partially pressed key combinations
  on errors, cancel running macros when edited/deleted.
- Windows single-instance mutex avoids concurrent controllers.
- Isolated Windows build with regression tests and proper failure handling.
- No old V3 executable/build cache included. UPX disabled in the build spec.
