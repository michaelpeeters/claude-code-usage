# claude-code-usage

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

## Platform support

| Platform | Status | Notes |
|---|---|---|
| Linux (X11) | ✅ Full | System tray, always-on-top |
| Linux (Wayland) | ✅ Works | See [Wayland notes](#wayland) below |
| macOS | ✅ Full | Native tray via QSystemTrayIcon |
| Windows | ✅ Full | Native tray; paths resolved via `Path.home()` |

---

## Requirements

- Python 3.10+
- [Claude Code CLI](https://claude.ai/code) installed and used at least once

```
pip install PyQt6
```

---

## Run

```bash
python claude_usage.py
```

The window stays on top by default (**Pin** button toggles this) and auto-refreshes every 5 minutes (**↺ 5m** button toggles).

---

## Optional: real rate-limit percentages

If you run the Claude Code statusline script it writes live rate-limit data to `~/.claude/rate-limits-cache.json`. When present, the widget shows exact percentages and reset times instead of estimates.

---

## Install as a desktop app

### Linux

1. Note the full path to the script, e.g. `/home/you/claude-code-usage/claude_usage.py`
2. Copy and edit the desktop entry:

```bash
cp packaging/claude-usage.desktop ~/.local/share/applications/
# Edit Exec= to point at your script path
nano ~/.local/share/applications/claude-usage.desktop
update-desktop-database ~/.local/share/applications/
```

### macOS

Add a shell alias or use **Automator** to create an Application wrapper:

```bash
echo 'alias claude-usage="python3 /path/to/claude_usage.py"' >> ~/.zshrc
```

### Windows

Create a shortcut targeting `pythonw.exe claude_usage.py` (use `pythonw` to suppress the console window).

---

## Wayland

The widget works on Wayland with no extra setup — PyQt6 auto-selects the Wayland backend when `WAYLAND_DISPLAY` is set.

```bash
QT_QPA_PLATFORM=wayland python claude_usage.py   # force Wayland
QT_QPA_PLATFORM=xcb python claude_usage.py        # force XWayland / X11
```

**Known limitations on Wayland:**
- **Always-on-top (Pin)** is silently ignored on most compositors — the window still works, the hint just has no effect.
- **System tray** requires a StatusNotifierItem-aware compositor or panel. Works on KDE Plasma; on GNOME you need the [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/). The app detects unavailability gracefully (`QSystemTrayIcon.isSystemTrayAvailable()`) and skips the tray when it isn't supported.

---

## Packaging

### AppImage (Linux)

Built automatically on tagged releases via [`.github/workflows/release.yml`](.github/workflows/release.yml).  
Download from the [Releases](https://github.com/michaelpeeters/claude-code-usage/releases) page.

To build locally:

```bash
pip install PyInstaller PyQt6
pyinstaller --onedir --windowed --name claude-usage claude_usage.py
# Then use appimagetool or appimage-builder on the dist/ directory
```

### Flatpak

A manifest is provided in [`packaging/com.github.michaelpeeters.ClaudeUsage.yml`](packaging/com.github.michaelpeeters.ClaudeUsage.yml).

```bash
# Install runtime (once)
flatpak install flathub org.kde.Platform//6.9 org.kde.Sdk//6.9

# Build and install locally
flatpak-builder --install --user build-dir \
    packaging/com.github.michaelpeeters.ClaudeUsage.yml
```

> The Flatpak manifest is a starting point and has not been tested in CI yet. PRs welcome.

---

## Development

```bash
pip install PyQt6 pytest
pytest                          # local
QT_QPA_PLATFORM=offscreen pytest   # headless (same as CI)
```

CI runs on Linux (Python 3.10 – 3.13), macOS, and Windows.

---

## License

[MIT](LICENSE)
