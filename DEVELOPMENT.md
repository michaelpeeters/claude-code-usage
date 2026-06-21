# Development

## Run from source

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

## Tests and linting

```bash
pip install pytest ruff mypy PyQt6
pytest                             # unit tests
QT_QPA_PLATFORM=offscreen pytest   # headless (same as CI)
ruff check claude_usage.py tests/
ruff format --check claude_usage.py tests/
mypy claude_usage.py
```

CI runs lint + type checks + tests on Linux (Python 3.10–3.13), macOS, and Windows. CodeQL SAST runs on every PR and weekly.

## Packaging

Binaries (AppImage / macOS `.app` / Windows `.exe`) are built and published automatically on every push to `main`. Download from the [Releases](https://github.com/michaelpeeters/claude-code-usage/releases) page.

## Contributing

`main` is protected — all changes go through a pull request. The `CI gate` check must be green before merging.

## Architecture notes

**Data source** — reads `~/.claude/projects/**/*.jsonl` directly; no API calls. The stats-cache (`~/.claude/stats-cache.json`) is used as a seed for historical data; live JSONL files overlay it for today and any dates after the cache cutoff.

**Refresh** — a background thread runs `collect_usage()`, `collect_5h_window()`, and `collect_live_contexts()` every 5 minutes (or on demand). A 30 s watchdog checks elapsed wall-clock time and fires immediately after system wake-from-sleep. If a refresh thread hangs for >60 s the watchdog clears the in-flight flag so the next tick can start fresh.

**Live context** — scans session JSONL files modified in the last 30 min. Reads the last 256 KB of each file to find the most recent assistant entry with `usage.input_tokens`; `used = input_tokens + cache_creation_input_tokens + cache_read_input_tokens`. Context limits: Opus 4.7/4.8 → 1 M tokens, all others → 200 K.

**Settings persistence** — window position in `~/.claude/claude-usage-pos.json`; section collapse state in `~/.claude/claude-usage-settings.json`.

**AppImage quirks (Manjaro/Arch)** — the updater strips `LD_LIBRARY_PATH` and `LD_PRELOAD` before spawning `curl` (AppImage injects its own bundled `libssl` which breaks system `curl`). After install, the new AppImage is launched via a Qt signal on the main thread to avoid broken Qt state in the child process.

**Wayland** — `WindowStaysOnTopHint` is unsupported by most Wayland compositors; the Pin button is hidden automatically. System tray requires a StatusNotifierItem panel (KDE Plasma works out of the box; GNOME needs the [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/)).
