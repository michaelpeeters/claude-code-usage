# <img src="packaging/claude-usage.png" width="32" align="center"> claude-code-usage

> **Unofficial tool — not made by, affiliated with, or endorsed by Anthropic.**  
> "Claude" and the Claude logo are trademarks of Anthropic, PBC.

A lightweight desktop widget that shows your [Claude Code](https://claude.ai/code) usage at a glance — no API key required.

| ![pro low](packaging/screenshot_pro_low.png) | ![max5x medium](packaging/screenshot_max5x_medium.png) | ![max20x high](packaging/screenshot_max20x_high.png) |
|:---:|:---:|:---:|
| Pro — light day | Max 5x — medium day | Max 20x — heavy day |

**What it shows:**
- **Live context window** per active session — see which conversations are nearing auto-compact before sending a large request
- Today's messages, tokens, and sessions
- Rolling 5-hour token window with implied ceiling and inferred plan (~Pro / ~Max 5x / ~Max 20x)
- Current-week bar chart and totals
- Per-model token breakdown (Sonnet / Opus / Haiku)
- Exact rate-limit % and reset times (when the [Claude Code statusline](https://github.com/michaelpeeters/claude-code-usage) script is running)
- Collapsible sections — state persists across restarts

---

## Install

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/michaelpeeters/claude-code-usage/main/install.sh | bash
```

Re-run anytime to update. Use `./install.sh --uninstall` to remove.

### Manjaro / Arch (AUR)

```bash
yay -S claude-code-usage        # stable release
yay -S claude-code-usage-git    # latest git HEAD
```

### Windows

```powershell
powershell -ExecutionPolicy Bypass -c "iwr https://raw.githubusercontent.com/michaelpeeters/claude-code-usage/main/install.ps1 | iex"
```

---

## Platform support

| Platform | Status | Notes |
|---|---|---|
| Linux (X11) | ✅ Full | AppImage, system tray, always-on-top pin |
| Linux (Wayland) | ✅ Works | Tray works on KDE; pin button hidden (not supported by compositors) |
| macOS | ✅ Full | Native tray, `.app` bundle |
| Windows | ✅ Full | Native tray, `.exe` |

---

## Usage tips

**Sections are collapsed by default** — click any header (▸ LIVE CONTEXT, ▸ USAGE, ▸ MODELS) to expand it. Your layout is saved across restarts.

**Live context** updates on every refresh (every 5 min, or click ↻). Sessions inactive for more than 30 minutes are not shown. A ⚠ compact soon warning appears when a context reaches ~83% — `/compact` that session before sending a large prompt.

**Auto-refresh** re-reads data every 5 minutes and catches up immediately after the system wakes from sleep. The "Updated" timestamp shows when the last scan ran; counts only change when Claude Code actually writes new data.

**In-app update** — when a new version is available, a banner appears at the bottom. Click it to download and restart automatically.

---

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for build instructions, tests, and architecture notes.

---

## License

[MIT](LICENSE)
