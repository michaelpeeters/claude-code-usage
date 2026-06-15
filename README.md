# claude-code-usage

A small PyQt6 desktop widget that shows your [Claude Code](https://claude.ai/code) token consumption at a glance — today's messages/tokens/sessions, the rolling 5-hour window gauge (so you can see throttle risk in real time), a 7-day bar chart, and a per-model breakdown.

![screenshot](screenshot.png)

---

## Trademark notice

"Claude" and the Claude logo are trademarks of Anthropic, PBC.  
This project is an independent, unofficial tool and is **not** affiliated with, endorsed by, or sponsored by Anthropic.

---

## Requirements

- Python 3.10+
- [Claude Code CLI](https://claude.ai/code) installed and used at least once (the widget reads `~/.claude/`)

```
pip install PyQt6
```

---

## Run

```bash
python claude_usage.py
```

The window stays on top by default (toggle with **Pin**) and auto-refreshes every 5 minutes (toggle with **↺ 5m**). A system-tray icon is shown when your desktop supports it.

---

## Optional: rate-limit percentages

If you run the [Claude Code statusline](https://github.com/anthropics/claude-code/blob/main/docs/statusline.md) script, it writes real rate-limit percentages to `~/.claude/rate-limits-cache.json`. The widget picks those up automatically and shows exact `%` values instead of estimates.

---

## Install as a desktop app (Linux)

1. Note the full path to the script, e.g. `/home/you/claude-code-usage/claude_usage.py`.
2. Create `~/.local/share/applications/claude-usage.desktop`:

```ini
[Desktop Entry]
Name=Claude Usage
Comment=Monitor Claude Code token usage
Exec=python3 /home/you/claude-code-usage/claude_usage.py
Icon=utilities-system-monitor
Type=Application
Categories=Utility;
StartupNotify=false
```

3. Refresh the launcher cache:

```bash
update-desktop-database ~/.local/share/applications/
```

---

## Development

```bash
# Run tests
pip install pytest
pytest
```

---

## License

[MIT](LICENSE)
