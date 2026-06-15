#!/usr/bin/env bash
# install.sh — install or update claude-code-usage from GitHub releases
# Usage:
#   ./install.sh              install, or update if already installed
#   ./install.sh --uninstall  remove everything
#   ./install.sh --source     install from local source (dev / no release yet)
set -euo pipefail

REPO="michaelpeeters/claude-code-usage"
INSTALL_DIR="$HOME/.local/share/claude-usage"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
VERSION_FILE="$INSTALL_DIR/.version"

# ── helpers ────────────────────────────────────────────────────────────────

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '  %s\n' "$*"; }

need() { command -v "$1" >/dev/null 2>&1 || { red "Error: '$1' not found. $2"; exit 1; }; }

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
    rm -rf  "$INSTALL_DIR"
    rm -f   "$BIN_DIR/claude-usage"
    rm -f   "$DESKTOP_DIR/claude-usage.desktop"
    command -v update-desktop-database >/dev/null 2>&1 \
        && update-desktop-database "$DESKTOP_DIR/" 2>/dev/null || true
    green "Done."
    exit 0
fi

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
printf '  Remove   : ./install.sh --uninstall\n\n'
