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
- Exact rate-limit % and reset times (when the [Claude Code statusline](https://github.com/anthropics/claude-code) script is running)
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

**Sections** — click any header to expand or collapse (▾ / ▸). Your layout is saved across restarts; sections start collapsed on a fresh install.

**Live context** updates on every refresh (every 5 min, or click ↻). Sessions inactive for more than 30 minutes are not shown. A ⚠ compact soon warning appears when a context reaches ~83% — `/compact` that session before sending a large prompt.

**Auto-refresh** re-reads data every 5 minutes and catches up immediately after the system wakes from sleep. The "Updated" timestamp shows when the last scan ran; counts only change when Claude Code actually writes new data.

**In-app update** — when a new version is available, a banner appears at the bottom. Click it to download and restart automatically.

---

## CLI / text output

`claude_usage_cli.py` prints the same stats as the GUI — no PyQt6 required.
Useful for piping into AI tools (Claude Code, OpenCode, Hermes) or shell scripts.

```bash
python claude_usage_cli.py          # human + LLM-readable key=value text
python claude_usage_cli.py --json   # fully structured JSON
```

**Sample output:**

```
CLAUDE USAGE  2026-06-27T16:24:07

LIVE CONTEXT
  project=claude-code-usage  model=Sonnet  pct=30  used=60K  limit=200K
  project=proxmox-maintenance  model=Sonnet  pct=28  used=56K  limit=200K

TODAY  date=2026-06-27
  messages=768  tokens=524K  tokens_raw=523894  sessions=3

WINDOW_5H
  pct=19  used=366K  used_raw=366339  limit=1.9M  plan=Pro  resets_at=20:00

WEEK_7D
  pct=15  used=2.3M  used_raw=2298565  limit=15.3M  resets_at=Thu 00:00
  messages=3418  sessions=21

MODELS_7D
  model=Sonnet  tokens=1.7M  tokens_raw=1732646
  model=Opus  tokens=491K  tokens_raw=491499
  model=Haiku  tokens=74K  tokens_raw=74420

DAILY
  date=2026-06-21  tokens=1.1M  tokens_raw=1109221  messages=1687  sessions=9
  date=2026-06-22  tokens=185K  tokens_raw=184704  messages=341  sessions=3
  ...
  date=2026-06-27  tokens=524K  tokens_raw=523894  messages=768  sessions=3  today=true
```

Every stat has a named `key=value` field so any tool can extract it by name.
Raw token counts (`tokens_raw`, `used_raw`) are included alongside human-formatted values.
`--json` produces the same data as a single object, ready for `jq` or direct parsing.

---

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for build instructions, tests, and architecture notes.

---

## License

[MIT](LICENSE)
