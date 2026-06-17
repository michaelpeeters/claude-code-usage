# <img src="packaging/claude-usage.png" width="32" align="center"> claude-code-usage

> **Unofficial tool — not made by, affiliated with, or endorsed by Anthropic.**  
> "Claude" and the Claude logo are trademarks of Anthropic, PBC.

A lightweight PyQt6 desktop widget that shows your [Claude Code](https://claude.ai/code) token consumption at a glance — no API key required. Reads the local `~/.claude/` data written by the CLI.

| ![pro low](packaging/screenshot_pro_low.png) | ![max5x medium](packaging/screenshot_max5x_medium.png) | ![max20x high](packaging/screenshot_max20x_high.png) |
|:---:|:---:|:---:|

**What it shows:**
- Today's messages, tokens, and sessions
- Rolling 5-hour window gauge with implied token ceiling and inferred plan (~Pro / ~Max 5x / ~Max 20x)
- 7-day bar chart and totals
- Per-model token breakdown (Sonnet / Opus / Haiku)
- Real rate-limit percentages when the Claude Code statusline script is running
- In-app one-click update when a newer version is available (auto-restarts)

---

## Install

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/michaelpeeters/claude-code-usage/main/install.sh | bash
```

Or download and run manually:

```bash
git clone https://github.com/michaelpeeters/claude-code-usage.git
cd claude-code-usage
./install.sh
```

Re-run anytime to update. On Linux the installer also extracts the app icon and registers it with the hicolor icon theme so it appears correctly in your launcher.

```bash
./install.sh --uninstall
```

### Manjaro / Arch (AUR)

```bash
yay -S claude-code-usage        # stable release
yay -S claude-code-usage-git    # latest git HEAD
```

### Windows

```powershell
powershell -ExecutionPolicy Bypass -c "iwr https://raw.githubusercontent.com/michaelpeeters/claude-code-usage/main/install.ps1 | iex"
```

Or download and run manually:

```powershell
.\install.ps1           # install / update
.\install.ps1 -Uninstall
```

The installer downloads the pre-built `.exe` from the [latest release](https://github.com/michaelpeeters/claude-code-usage/releases/latest) and adds a Start Menu shortcut.

---

## Platform support

| Platform | Status | Notes |
|---|---|---|
| Linux (X11) | ✅ Full | AppImage, system tray, always-on-top pin |
| Linux (Wayland) | ✅ Works | Tray works on KDE; pin button hidden (not supported) |
| macOS | ✅ Full | Native tray, `.app` bundle via installer |
| Windows | ✅ Full | Native tray, `.exe` via installer |

**Data path** — the `.claude` folder lives inside your OS home directory:

| OS | Path |
|---|---|
| Linux | `/home/you/.claude/` |
| macOS | `/Users/you/.claude/` |
| Windows | `C:\Users\you\.claude\` |

---

## Wayland

PyQt6 auto-selects the Wayland backend when `WAYLAND_DISPLAY` is set. No extra config needed.

```bash
QT_QPA_PLATFORM=wayland claude-usage   # force Wayland
QT_QPA_PLATFORM=xcb    claude-usage   # force X11 / XWayland
```

**Known limitations:**
- **Pin button** — hidden on Wayland; `WindowStaysOnTopHint` is not supported by most compositors.
- **System tray** — requires a StatusNotifierItem panel. Works on KDE Plasma; on GNOME install the [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/). The app detects unavailability automatically and skips the tray icon.

---

## Optional: real rate-limit percentages

If the Claude Code statusline script is running it writes live data to `~/.claude/rate-limits-cache.json`. The widget picks this up automatically and shows exact percentages and reset times instead of estimates.

---

## Auto-refresh

The widget re-reads your usage data every 5 minutes. A watchdog timer (30 s tick) checks elapsed wall-clock time and triggers a refresh immediately after the system wakes from sleep — so the display catches up right away rather than waiting out whatever interval was left on the timer before sleep.

**Around rate-limit resets** the interval tightens: once the `resets_at` timestamp from the statusline cache passes, the watchdog switches to a 60-second poll for the next 15 minutes. This covers the observed real-world lag of 5–10 minutes between the advertised reset time and when the window actually clears on Anthropic's side.

**Stuck-refresh safety net**: if a background collection thread hangs for more than 60 seconds the watchdog force-clears the in-flight flag and shows "Refresh timed out", so the next tick can start a fresh attempt. The worker thread also catches `BaseException` (not just `Exception`) so the flag is cleared even on rare runtime crashes.

Data collection runs in a background thread so the window stays responsive during the scan. Both the 5-hour window scan and the usage aggregation skip JSONL files via `mtime` before opening them — only recently-modified files are read — so refreshes stay fast regardless of how many sessions or how long the session has been running.

---

## AppImage auto-update on Manjaro / Arch

Clicking the "↑ vX.Y.Z available" banner downloads and installs the new AppImage in-place, then relaunches automatically.

Two Manjaro-specific quirks are handled:

**`LD_LIBRARY_PATH` stripping** — AppImage injects its own `LD_LIBRARY_PATH` pointing at bundled libraries (including an old `libssl`). If that path reaches `curl` during the update download, `curl` picks up the wrong `libssl` and the download fails. The updater strips `LD_LIBRARY_PATH` and `LD_PRELOAD` from the subprocess environment before spawning `curl`.

**Main-thread relaunch** — After the install script finishes, the new AppImage is launched via `subprocess.Popen` and the app quits. The `Popen` call must happen on the Qt main thread (via a signal), not inside the install thread, or the child process inherits a broken Qt state on some Manjaro compositor configurations.

---

## Development

### Run from source

```bash
git clone https://github.com/michaelpeeters/claude-code-usage.git
cd claude-code-usage
./install.sh --source   # creates .venv, installs PyQt6, links claude-usage binary
claude-usage
```

Or without the installer:

```bash
pip install PyQt6
python claude_usage.py
```

### Tests and linting

```bash
pip install pytest ruff mypy PyQt6
pytest                             # unit tests
QT_QPA_PLATFORM=offscreen pytest   # headless (same as CI)
ruff check claude_usage.py tests/  # lint
ruff format --check claude_usage.py tests/
mypy claude_usage.py               # type check
```

CI runs lint + type checks + tests on Linux (Python 3.10–3.13), macOS, and Windows. CodeQL SAST runs on every PR and weekly.

Tests cover: token formatting, JSONL aggregation, stats-cache seeding, window instantiation, label refresh, implied-limit calculation, paint events for bar/chart widgets, update-check signal emission, system CA bundle selection, LD_LIBRARY_PATH stripping for the in-app updater, non-blocking refresh (background thread), concurrent-refresh guard, watchdog trigger after elapsed time, watchdog no-op when auto-refresh is disabled, and mtime-based file skipping for both the 5-hour window scan and usage aggregation.

### Packaging

Binaries (AppImage / macOS app / Windows exe) are built and released automatically on every merge to `main`. Download from the [Releases](https://github.com/michaelpeeters/claude-code-usage/releases) page.

### Contributing

`main` is protected — all changes go through a pull request. The `CI gate` check must be green before merging. A new release is created automatically after each successful merge.

---

## License

[MIT](LICENSE)
