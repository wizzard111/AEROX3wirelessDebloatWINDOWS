# Changelog

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
