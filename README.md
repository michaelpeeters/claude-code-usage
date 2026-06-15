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

**Update / uninstall:**

```bash
./install.sh --update
./install.sh --uninstall
```

### Windows

```powershell
powershell -ExecutionPolicy Bypass -c "iwr https://raw.githubusercontent.com/michaelpeeters/claude-code-usage/main/install.ps1 | iex"
```

Or download and run manually:

```powershell
.\install.ps1           # install
.\install.ps1 -Update   # update
.\install.ps1 -Uninstall
```

The installer downloads the pre-built `.exe` from the [latest release](https://github.com/michaelpeeters/claude-code-usage/releases/latest) and adds a Start Menu shortcut.

---

## Platform support

| Platform | Status | Notes |
|---|---|---|
| Linux (X11) | ✅ Full | AppImage, system tray, always-on-top |
| Linux (Wayland) | ✅ Works | See [Wayland notes](#wayland) below |
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
- **Always-on-top (Pin)** — silently ignored on most Wayland compositors; the app still works.
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
pip install PyQt6        # or: python -m venv .venv && source .venv/bin/activate && pip install PyQt6
python claude_usage.py
```

### Tests

```bash
pip install pytest
pytest                             # local
QT_QPA_PLATFORM=offscreen pytest   # headless (same as CI)
```

CI runs on Linux (Python 3.10 – 3.13), macOS, and Windows via GitHub Actions.

### Packaging

**AppImage (Linux) / macOS app / Windows exe** are built automatically when a `v*` tag is pushed, via [`.github/workflows/release.yml`](.github/workflows/release.yml). Download from the [Releases](https://github.com/michaelpeeters/claude-code-usage/releases) page.

**Flatpak** — a manifest is in [`packaging/com.github.michaelpeeters.ClaudeUsage.yml`](packaging/com.github.michaelpeeters.ClaudeUsage.yml). Not yet published to Flathub; PRs welcome.

---

## License

[MIT](LICENSE)
