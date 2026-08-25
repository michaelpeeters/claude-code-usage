#!/usr/bin/env bash
# install.sh — install or update claude-code-usage from GitHub releases
# Usage:
#   ./install.sh                    install, or update if already installed —
#                                    prompts to wire up the statusLine bridge
#                                    (exact rate-limit %) unless one is already set
#   ./install.sh --uninstall        remove everything
#   ./install.sh --source           install from local source (dev / no release yet)
#   ./install.sh --with-statusline  wire up the statusLine bridge without prompting
#                                    (combine with --source, e.g.
#                                    ./install.sh --source --with-statusline; also
#                                    what to pass through a curl|bash pipe, e.g.
#                                    curl -fsSL .../install.sh | bash -s -- --with-statusline)
#   ./install.sh --no-statusline    skip the statusLine bridge without prompting
set -euo pipefail

REPO="michaelpeeters/claude-code-usage"
INSTALL_DIR="$HOME/.local/share/claude-usage"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
VERSION_FILE="$INSTALL_DIR/.version"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

WITH_STATUSLINE=0
NO_STATUSLINE=0
for arg in "$@"; do
    [[ "$arg" == "--with-statusline" ]] && WITH_STATUSLINE=1
    [[ "$arg" == "--no-statusline" ]] && NO_STATUSLINE=1
done

# ── helpers ────────────────────────────────────────────────────────────────

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '  %s\n' "$*"; }

need() { command -v "$1" >/dev/null 2>&1 || { red "Error: '$1' not found. $2"; exit 1; }; }

# A statusLine command is "ours" if it invokes our own --statusline bridge —
# either the bundled binary (AppImage / macOS .app, no python3 needed at
# runtime) or, for --source installs, claude_usage_cli.py via a venv python.
# Shared between setup_statusline/statusline_status/remove_statusline so a
# command built by any past version of this script is still recognized.
_IS_OURS_PY='
def is_ours(cmd):
    return "--statusline" in cmd and (
        "claude_usage_cli.py" in cmd
        or "claude-usage.AppImage" in cmd
        or "Claude Usage.app" in cmd
    )
'

# Writes the `statusLine` entry in ~/.claude/settings.json so Claude Code
# feeds real rate_limits to the widget instead of it estimating from local
# token counts. Never touches a statusLine that isn't ours. Backs up
# settings.json before any write. Takes the full command to run, e.g.
# '"/path/to/claude-usage.AppImage" --statusline'.
setup_statusline() {
    local command="$1" python_bin
    python_bin=$(command -v python3 2>/dev/null) || {
        red "  python3 not found — skipping statusline setup (only needed for the installer to edit settings.json, not at runtime)."
        return
    }
    mkdir -p "$(dirname "$CLAUDE_SETTINGS")"
    "$python_bin" - "$CLAUDE_SETTINGS" "$command" <<PYEOF
import json, os, shutil, sys
$_IS_OURS_PY
settings_file, command = sys.argv[1], sys.argv[2]

try:
    with open(settings_file) as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    settings = {}

existing = settings.get("statusLine")
if isinstance(existing, dict) and existing.get("command") and not is_ours(existing["command"]):
    print(f"  statusLine already configured ({existing['command']!r}) — leaving it alone.")
    print("  To get exact rate-limit %, add this to your own statusLine script:")
    print("    read rate_limits from stdin JSON, write it to ~/.claude/rate-limits-cache.json")
    sys.exit(0)

if os.path.exists(settings_file):
    shutil.copy2(settings_file, settings_file + ".bak")

settings["statusLine"] = {"type": "command", "command": command}
tmp = settings_file + ".tmp"
with open(tmp, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
os.replace(tmp, settings_file)
print(f"  statusLine configured in {settings_file} (previous version backed up to .bak)")
PYEOF
}

# Prints "none" (no statusLine set), "ours" (already our bridge), or
# "foreign" (some other custom statusLine — never overwrite it).
statusline_status() {
    local python_bin
    python_bin=$(command -v python3 2>/dev/null) || { echo "none"; return; }
    [[ -f "$CLAUDE_SETTINGS" ]] || { echo "none"; return; }
    "$python_bin" - "$CLAUDE_SETTINGS" <<PYEOF
import json, sys
$_IS_OURS_PY
try:
    with open(sys.argv[1]) as f:
        settings = json.load(f)
except Exception:
    print("none")
    sys.exit()

sl = settings.get("statusLine")
if not isinstance(sl, dict) or not sl.get("command"):
    print("none")
elif is_ours(sl["command"]):
    print("ours")
else:
    print("foreign")
PYEOF
}

# Asks (via /dev/tty, so it still works under `curl | bash`) whether to wire
# up the statusLine bridge, unless --with-statusline/--no-statusline already
# decided it, or a statusLine is already configured either way. Silently
# skips the prompt (defaults to no) if there's no interactive terminal.
maybe_prompt_statusline() {
    [[ "$WITH_STATUSLINE" == "1" || "$NO_STATUSLINE" == "1" ]] && return
    local status
    status=$(statusline_status)
    [[ "$status" != "none" ]] && return
    # `test -r/-w /dev/tty` only checks the device file's permission bits (always
    # true — it's world RW), not whether this process actually has a controlling
    # terminal (e.g. launched from a GUI subprocess, as the in-app updater does).
    # Try to actually write to it instead: printf isn't a POSIX "special builtin"
    # (unlike exec/eval/source), so a redirection failure here just makes printf
    # exit non-zero — caught by `|| return` — instead of killing the whole shell
    # under set -e the way a failed `exec 3<>/dev/tty` redirection would.
    # `return` (bare) would return printf's own failing exit status here, which
    # then aborts the *caller* under set -e — must be an explicit `return 0`.
    printf 'Set up exact rate-limit %% via Claude Code statusLine? [Y/n] ' > /dev/tty 2>/dev/null || return 0
    local ans=""
    read -r ans < /dev/tty 2>/dev/null || true
    case "$ans" in
        [nN]*) ;;
        *) WITH_STATUSLINE=1 ;;
    esac
}

remove_statusline() {
    local python_bin
    python_bin=$(command -v python3 2>/dev/null) || return 0
    [[ -f "$CLAUDE_SETTINGS" ]] || return 0
    "$python_bin" - "$CLAUDE_SETTINGS" <<PYEOF
import json, sys
$_IS_OURS_PY
settings_file = sys.argv[1]
try:
    with open(settings_file) as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    sys.exit(0)

sl = settings.get("statusLine")
if isinstance(sl, dict) and is_ours(sl.get("command") or ""):
    del settings["statusLine"]
    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("  Removed claude-usage's statusLine entry from settings.json")
PYEOF
}

# ── detect OS / arch ──────────────────────────────────────────────────────

OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
    Linux)  PLATFORM=linux ;;
    Darwin) PLATFORM=macos ;;
    *)      red "Unsupported OS: $OS. Use install.ps1 on Windows."; exit 1 ;;
esac

# ── uninstall ──────────────────────────────────────────────────────────────

if [[ "${1:-}" == "--uninstall" ]]; then
    bold "Uninstalling claude-code-usage…"
    remove_statusline
    rm -rf  "$INSTALL_DIR"
    rm -f   "$BIN_DIR/claude-usage"
    rm -f   "$DESKTOP_DIR/claude-usage.desktop"
    command -v update-desktop-database >/dev/null 2>&1 \
        && update-desktop-database "$DESKTOP_DIR/" 2>/dev/null || true
    green "Done."
    exit 0
fi

# ── statusLine bridge: prompt if undecided and nothing is configured yet ──

maybe_prompt_statusline

# ── source install (dev / no release available) ───────────────────────────

if [[ "${1:-}" == "--source" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    bold "Installing from source in $SCRIPT_DIR…"
    need python3 "Install Python 3.10+ first."

    find_python() {
        for c in python3 python3.13 python3.12 python3.11 python3.10; do
            b=$(command -v "$c" 2>/dev/null) || continue
            v=$("$b" -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')" 2>/dev/null) || continue
            [[ "$v" -ge 310 ]] && { echo "$b"; return; }
        done
        red "Python 3.10+ not found."; exit 1
    }
    PYTHON=$(find_python)
    VENV="$SCRIPT_DIR/.venv"
    "$PYTHON" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet PyQt6

    LAUNCHER="$SCRIPT_DIR/run.sh"
    printf '#!/usr/bin/env bash\nexec "%s/bin/python" "%s/claude_usage.py" "$@"\n' \
        "$VENV" "$SCRIPT_DIR" > "$LAUNCHER"
    chmod +x "$LAUNCHER"

    mkdir -p "$BIN_DIR"
    ln -sf "$LAUNCHER" "$BIN_DIR/claude-usage"

    if [[ "$PLATFORM" == "linux" ]]; then
        mkdir -p "$DESKTOP_DIR"
        sed "s|Exec=.*|Exec=$LAUNCHER|" \
            "$SCRIPT_DIR/packaging/claude-usage.desktop" \
            > "$DESKTOP_DIR/claude-usage.desktop"
        command -v update-desktop-database >/dev/null 2>&1 \
            && update-desktop-database "$DESKTOP_DIR/" 2>/dev/null || true
    fi
    if [[ "$WITH_STATUSLINE" == "1" ]]; then
        bold "Wiring up Claude Code statusLine…"
        setup_statusline "\"$VENV/bin/python\" \"$SCRIPT_DIR/claude_usage_cli.py\" --statusline"
    fi

    green "Source install done. Run: claude-usage"
    exit 0
fi

# ── fetch latest release info from GitHub API ─────────────────────────────

need curl "Install curl and re-run."

bold "Fetching latest release from github.com/$REPO…"

RELEASE_JSON=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
    || { red "Failed to reach GitHub API. Check your internet connection."; exit 1; })

LATEST_TAG=$(printf '%s' "$RELEASE_JSON" | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')
[[ -z "$LATEST_TAG" ]] && { red "No release found for $REPO."; exit 1; }

CURRENT_TAG=""
[[ -f "$VERSION_FILE" ]] && CURRENT_TAG=$(cat "$VERSION_FILE")

if [[ -n "$CURRENT_TAG" ]] && [[ "$CURRENT_TAG" == "$LATEST_TAG" ]]; then
    green "Already up to date ($LATEST_TAG)."
    exit 0
fi

info "Latest release : $LATEST_TAG"
[[ -n "$CURRENT_TAG" ]] && info "Installed       : $CURRENT_TAG" || info "Fresh install"

# ── pick the right asset ──────────────────────────────────────────────────

ASSETS=$(printf '%s' "$RELEASE_JSON" \
    | grep '"browser_download_url"' \
    | sed 's/.*"browser_download_url": *"\([^"]*\)".*/\1/')

pick_asset() {
    local pattern="$1"
    printf '%s\n' "$ASSETS" | grep "$pattern" | head -1
}

if [[ "$PLATFORM" == "linux" ]]; then
    case "$ARCH" in
        x86_64)  ASSET_URL=$(pick_asset "x86_64\.AppImage") ;;
        aarch64) ASSET_URL=$(pick_asset "aarch64\.AppImage") ;;
        *)       red "Unsupported architecture: $ARCH"; exit 1 ;;
    esac
    [[ -z "$ASSET_URL" ]] && { red "No Linux AppImage found in release $LATEST_TAG."; exit 1; }
elif [[ "$PLATFORM" == "macos" ]]; then
    ASSET_URL=$(pick_asset "macos\.zip")
    [[ -z "$ASSET_URL" ]] && { red "No macOS zip found in release $LATEST_TAG."; exit 1; }
fi

# ── download ───────────────────────────────────────────────────────────────

mkdir -p "$INSTALL_DIR"
TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE"' EXIT

bold "Downloading $ASSET_URL…"
curl -fL --progress-bar -o "$TMPFILE" "$ASSET_URL"

# ── install ────────────────────────────────────────────────────────────────

if [[ "$PLATFORM" == "linux" ]]; then
    APPIMAGE="$INSTALL_DIR/claude-usage.AppImage"
    mv "$TMPFILE" "$APPIMAGE"
    chmod +x "$APPIMAGE"

    mkdir -p "$BIN_DIR"
    ln -sf "$APPIMAGE" "$BIN_DIR/claude-usage"

    # Extract app icon and install into hicolor theme
    ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
    mkdir -p "$ICON_DIR"
    ICON_TMP=$(mktemp -d)
    "$APPIMAGE" --appimage-extract utilities-system-monitor.png 2>/dev/null \
        && cp squashfs-root/utilities-system-monitor.png "$ICON_DIR/claude-usage.png" \
        || true
    rm -rf squashfs-root "$ICON_TMP"
    command -v gtk-update-icon-cache >/dev/null 2>&1 \
        && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor/" 2>/dev/null || true

    # .desktop entry pointing at the AppImage
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/claude-usage.desktop" <<DESK
[Desktop Entry]
Name=Claude Usage
GenericName=Token Usage Monitor
Comment=Monitor Claude Code token consumption (unofficial, not by Anthropic)
Exec=$APPIMAGE
Icon=claude-usage
Type=Application
Categories=Utility;Monitor;
Keywords=claude;tokens;usage;
StartupNotify=false
DESK
    command -v update-desktop-database >/dev/null 2>&1 \
        && update-desktop-database "$DESKTOP_DIR/" 2>/dev/null || true

elif [[ "$PLATFORM" == "macos" ]]; then
    need unzip "Install unzip and re-run."
    APPS_DIR="$HOME/Applications"
    mkdir -p "$APPS_DIR"
    # Remove old version first
    rm -rf "$APPS_DIR/Claude Usage.app"
    unzip -q "$TMPFILE" -d "$APPS_DIR"

    # Create a thin CLI wrapper so 'claude-usage' works in the terminal too
    mkdir -p "$BIN_DIR"
    cat > "$BIN_DIR/claude-usage" <<'WRAP'
#!/usr/bin/env bash
open -a "Claude Usage"
WRAP
    chmod +x "$BIN_DIR/claude-usage"
fi

# ── statusLine bridge (exact rate-limit %, decided above by flag or prompt) ─
#
# The bridge is baked into the shipped binary itself (claude_usage.py
# handles `--statusline` before touching Qt/a display, see main()) — no
# separate script to fetch, no python3 needed at runtime, works the same
# under bash or zsh since Claude Code just execs the command directly.

if [[ "$WITH_STATUSLINE" == "1" ]]; then
    bold "Wiring up Claude Code statusLine…"
    if [[ "$PLATFORM" == "linux" ]]; then
        setup_statusline "\"$APPIMAGE\" --statusline"
    elif [[ "$PLATFORM" == "macos" ]]; then
        MACOS_BIN="$APPS_DIR/Claude Usage.app/Contents/MacOS/Claude Usage"
        setup_statusline "\"$MACOS_BIN\" --statusline"
    fi
fi

# ── record installed version ──────────────────────────────────────────────

printf '%s\n' "$LATEST_TAG" > "$VERSION_FILE"

# ── PATH reminder ──────────────────────────────────────────────────────────

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        [[ -f "$rc" ]] || continue
        printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc"
    done
    red "Note: $BIN_DIR was not in PATH — added it to shell rc files. Restart your shell."
fi

# ── done ───────────────────────────────────────────────────────────────────

bold "Installed $LATEST_TAG!"
if [[ "$PLATFORM" == "linux" ]]; then
    printf '\n  Terminal : claude-usage\n'
    printf '  Launcher : search your app menu for "Claude Usage"\n'
elif [[ "$PLATFORM" == "macos" ]]; then
    printf '\n  Terminal : claude-usage  (or open -a "Claude Usage")\n'
    printf '  Launcher : ~/Applications/Claude Usage.app\n'
fi
printf '  Update   : ./install.sh\n'
printf '  Remove   : ./install.sh --uninstall\n'
[[ "$WITH_STATUSLINE" != "1" ]] \
    && printf '  Exact %%  : re-run with --with-statusline for real (not estimated) rate-limit %%\n'
[[ "$WITH_STATUSLINE" == "1" ]] \
    && printf '  Exact %%  : statusLine wired up — restart Claude Code sessions to pick it up\n'
printf '\n'
