# <img src="packaging/claude-usage.png" width="32" align="center"> claude-code-usage

> **Unofficial tool — not made by, affiliated with, or endorsed by Anthropic.**  
> "Claude" and the Claude logo are trademarks of Anthropic, PBC.

A lightweight PyQt6 desktop widget that shows your [Claude Code](https://claude.ai/code) token consumption at a glance — no API key required. Reads the local `~/.claude/` data written by the CLI.

![screenshot](screenshot.png)

**What it shows:**
- Today's messages, tokens, and sessions
- Rolling 5-hour window gauge (throttle risk indicator)
- 7-day bar chart and totals
- Per-model token breakdown (Sonnet / Opus / Haiku)
- Real rate-limit percentages when the Claude Code statusline script is running
- In-app notification when a newer version is available

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

Tests cover: token formatting, JSONL aggregation, stats-cache seeding, window instantiation, label refresh, implied-limit calculation, paint events for bar/chart widgets, update-check signal emission, and system CA bundle selection.

### Packaging

Binaries (AppImage / macOS app / Windows exe) are built and released automatically on every merge to `main`. Download from the [Releases](https://github.com/michaelpeeters/claude-code-usage/releases) page.

### Contributing

`main` is protected — all changes go through a pull request. The `CI gate` check must be green before merging. A new release is created automatically after each successful merge.

---

## License

[MIT](LICENSE)
