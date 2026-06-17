#!/usr/bin/env python3
"""Claude Code usage monitor — reads local ~/.claude data, no API needed."""

import json
import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

APP_VERSION = "dev"
_RELEASES_API = "https://api.github.com/repos/michaelpeeters/claude-code-usage/releases/latest"

CLAUDE_DIR = Path.home() / ".claude"
STATS_CACHE = CLAUDE_DIR / "stats-cache.json"
PROJECTS_DIR = CLAUDE_DIR / "projects"
RATE_LIMITS_CACHE = CLAUDE_DIR / "rate-limits-cache.json"
POS_CACHE = CLAUDE_DIR / "claude-usage-pos.json"

ACCENT = "#d97706"  # amber
BG = "#1a1a1a"
BG2 = "#242424"
FG = "#e5e5e5"
FG2 = "#a3a3a3"
BAR_COLOR = "#d97706"
BAR_TODAY = "#f59e0b"

# Estimated token threshold before Claude Code starts throttling.
# Based on observed heavy days; adjust if your personal limit differs.
THROTTLE_ESTIMATE = 1_500_000
WEEK_ESTIMATE = 7_500_000  # ~5 heavy days

MODEL_SHORT = {
    "claude-sonnet-4-6": "Sonnet",
    "claude-opus-4-7": "Opus",
    "claude-opus-4-8": "Opus",
    "claude-haiku-4-5-20251001": "Haiku",
    "claude-haiku-4-5": "Haiku",
}


def _infer_plan(ceiling_5h: int) -> str:
    """Guess the Claude plan from the implied 5-hour token ceiling."""
    if ceiling_5h >= 10_000_000:
        return "Max 20x"
    if ceiling_5h >= 3_000_000:
        return "Max 5x"
    return "Pro"


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def load_rate_limits() -> dict:
    """Load cached rate limits written by the statusline script. Returns {} if unavailable."""
    if not RATE_LIMITS_CACHE.exists():
        return {}
    try:
        return json.loads(RATE_LIMITS_CACHE.read_text())
    except Exception:
        return {}


def collect_5h_window() -> int:
    """Sum real tokens (input+output) from the last 5 hours across all JSONL files."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=5)
    cutoff_ts = cutoff.timestamp()
    total = 0
    for jsonl_file in PROJECTS_DIR.glob("*/*.jsonl"):
        if jsonl_file.stat().st_mtime < cutoff_ts:
            continue
        try:
            with open(jsonl_file) as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    obj = json.loads(raw)
                    if obj.get("type") != "assistant":
                        continue
                    ts = obj.get("timestamp", "")
                    if not ts:
                        continue
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                    usage = obj.get("message", {}).get("usage", {})
                    total += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        except Exception:
            continue
    return total


def collect_usage() -> dict:
    """Aggregate usage from stats-cache and live project JSONL files."""
    daily: dict[str, dict] = defaultdict(
        lambda: {
            "messages": 0,
            "sessions": set(),
            "tools": 0,
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_create": 0,
            "models": defaultdict(int),
        }
    )

    # Seed from stats-cache (fast, but may lag)
    cache_cutoff = ""
    if STATS_CACHE.exists():
        try:
            cache = json.loads(STATS_CACHE.read_text())
            cache_cutoff = cache.get("lastComputedDate", "")
            for day in cache.get("dailyActivity", []):
                d = day["date"]
                daily[d]["messages"] += day.get("messageCount", 0)
                daily[d]["tools"] += day.get("toolCallCount", 0)
                # sessions from cache are counts, not IDs — store as int sentinel
                daily[d]["sessions_count"] = daily[d].get("sessions_count", 0) + day.get("sessionCount", 0)
            for day in cache.get("dailyModelTokens", []):
                d = day["date"]
                for model, toks in day.get("tokensByModel", {}).items():
                    daily[d]["models"][MODEL_SHORT.get(model, model)] += toks
        except Exception:
            pass

    # Overlay with live JSONL data (covers dates after cache cutoff too)
    # Skip files whose mtime predates the cache cutoff — they can't have new data.
    cutoff_mtime = datetime.strptime(cache_cutoff, "%Y-%m-%d").timestamp() if cache_cutoff else 0.0
    seen_sessions: set[str] = set()
    for jsonl_file in sorted(PROJECTS_DIR.glob("*/*.jsonl")):
        if cache_cutoff and jsonl_file.stat().st_mtime < cutoff_mtime:
            continue
        try:
            with open(jsonl_file) as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    obj = json.loads(raw)
                    if obj.get("type") != "assistant":
                        continue
                    ts = obj.get("timestamp", "")
                    if not ts:
                        continue
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    d = dt.strftime("%Y-%m-%d")
                    # Only overlay dates the cache didn't already cover fully,
                    # OR always include today (cache may be stale intraday)
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    if d <= cache_cutoff and d != today_str:
                        continue
                    msg = obj.get("message", {})
                    usage = msg.get("usage", {})
                    if not usage:
                        continue
                    sid = obj.get("sessionId", "")
                    daily[d]["messages"] += 1
                    if sid and sid not in seen_sessions:
                        seen_sessions.add(sid)
                        daily[d]["sessions"].add(sid)
                    inp = usage.get("input_tokens", 0)
                    out = usage.get("output_tokens", 0)
                    daily[d]["input"] += inp
                    daily[d]["output"] += out
                    daily[d]["cache_read"] += usage.get("cache_read_input_tokens", 0)
                    daily[d]["cache_create"] += usage.get("cache_creation_input_tokens", 0)
                    raw_model = msg.get("model", "")
                    if not raw_model or raw_model.startswith("<"):
                        continue
                    model = MODEL_SHORT.get(
                        raw_model,
                        raw_model.split("-")[1] if "-" in raw_model else raw_model,
                    )
                    daily[d]["models"][model] += inp + out
        except Exception:
            continue

    # Resolve sessions to counts
    result = {}
    for d, v in daily.items():
        sc = len(v["sessions"]) if v["sessions"] else v.get("sessions_count", 0)
        real_tokens = v["input"] + v["output"]  # exclude cache reads from headline
        result[d] = {
            "messages": v["messages"],
            "sessions": sc,
            "tools": v["tools"],
            "tokens": real_tokens,
            "output": v["output"],
            "cache_read": v["cache_read"],
            "models": dict(v["models"]),
        }
    return result


def make_usage_icon(pct: float, size: int = 128) -> QIcon:
    """Tray icon: horizontal fill bar using full icon height."""
    if pct < 75:
        accent = QColor("#22c55e")
    elif pct < 90:
        accent = QColor(ACCENT)
    else:
        accent = QColor("#ef4444")

    draw_size = size * 2
    px = QPixmap(draw_size, draw_size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    h_mg = max(2, draw_size // 16)  # horizontal margin
    v_mg = max(6, draw_size // 5)  # vertical margin — centres + shrinks bar
    bar_x = h_mg
    bar_y = v_mg
    bar_w = draw_size - 2 * h_mg
    bar_h = draw_size - 2 * v_mg
    r = max(3, bar_h // 6)

    p.setPen(QPen(QColor("#555555"), max(1, draw_size // 48)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, r, r)

    fill_w = max(0, int(bar_w * pct / 100))
    if fill_w:
        border = max(2, draw_size // 32)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.setClipRect(bar_x + border, bar_y + border, bar_w - 2 * border, bar_h - 2 * border)
        p.drawRoundedRect(
            bar_x + border,
            bar_y + border,
            fill_w - border,
            bar_h - 2 * border,
            max(1, r - border),
            max(1, r - border),
        )
        p.setClipping(False)

    p.end()
    return QIcon(
        px.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )


class MiniBarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: list[tuple[str, int, bool]] = []  # (label, value, is_today)
        self.setMinimumHeight(60)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, data):
        self.data = data
        self.update()

    def paintEvent(self, event):
        if not self.data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        max_val = max(v for _, v, _ in self.data) or 1
        bar_w = w / len(self.data)
        pad = 2
        for i, (label, val, is_today) in enumerate(self.data):
            bar_h = int((val / max_val) * (h - 18))
            x = int(i * bar_w + pad)
            bw = int(bar_w - pad * 2)
            y = h - 14 - bar_h
            color = QColor(BAR_TODAY if is_today else BAR_COLOR)
            if not is_today:
                color.setAlphaF(0.65)
            p.fillRect(x, y, bw, bar_h, color)
            p.setPen(QColor(FG2))
            p.setFont(QFont("monospace", 7))
            day_lbl = f"{int(label[8:])}/{int(label[5:7])}"
            p.drawText(x, h - 2, day_lbl)
        p.end()


class PaceBar(QWidget):
    """Horizontal progress bar for the 5-hour rolling token window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._maximum = THROTTLE_ESTIMATE
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: int, maximum: int = THROTTLE_ESTIMATE):
        self._value = value
        self._maximum = maximum or THROTTLE_ESTIMATE
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        ratio = min(1.0, self._value / self._maximum)
        p.fillRect(0, 0, w, h, QColor(BG2))
        fill_w = int(w * ratio)
        if fill_w > 0:
            if ratio < 0.75:
                color = QColor("#22c55e")
            elif ratio < 0.90:
                color = QColor(ACCENT)
            else:
                color = QColor("#ef4444")
            p.fillRect(0, 0, fill_w, h, color)
        p.end()


class UsageWindow(QWidget):
    _update_available = pyqtSignal(str)
    _restart_app = pyqtSignal(str)  # emitted from install thread → main thread relaunches
    _refresh_done = pyqtSignal(dict, int, dict)  # daily, win_tokens, rate_limits

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Claude™ Usage")
        self.setMinimumWidth(280)
        self.always_on_top = True
        self._apply_flags()
        self._build_ui()
        self._tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(self)
            self._tray.setToolTip("Claude Usage · unofficial tool, not by Anthropic")
            self._tray.activated.connect(self._tray_clicked)
            self._tray.show()
        self._update_available.connect(self._show_update_banner)
        self._restart_app.connect(self._do_restart)
        self._refresh_done.connect(self._apply_refresh)
        self._refreshing = False
        self._last_refresh = 0.0  # wall-clock seconds (time.time()), so sleep counts
        self.refresh()
        # Watchdog fires every 30s and triggers a refresh if >5 min of wall-clock time
        # have elapsed since the last completed refresh. Because time.time() advances
        # during system sleep while CLOCK_MONOTONIC (used by QTimer internally) does not,
        # the watchdog fires immediately after wake-from-sleep when the regular timer
        # would still be waiting out its pre-sleep remaining interval.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._watchdog)
        self._timer.start(30_000)
        threading.Thread(target=self._check_for_update, daemon=True).start()

    def _check_for_update(self):
        if APP_VERSION == "dev":
            return
        try:
            # PyInstaller bundles its own OpenSSL without a CA store; point at the system bundle.
            ctx = ssl.create_default_context()
            for ca in (
                "/etc/ssl/cert.pem",  # Arch/Manjaro
                "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
                "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL/Fedora
                "/etc/ssl/ca-bundle.pem",  # openSUSE
            ):
                if Path(ca).exists():
                    ctx = ssl.create_default_context(cafile=ca)
                    break

            req = urllib.request.Request(_RELEASES_API, headers={"User-Agent": "claude-code-usage"})
            for attempt in range(2):
                try:
                    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                        data = json.loads(resp.read())
                    break
                except TimeoutError:
                    if attempt == 0:
                        continue
                    raise
            latest = data.get("tag_name", "")
            if latest and latest != APP_VERSION:
                self._update_available.emit(latest)
        except Exception:
            pass

    def _show_update_banner(self, latest: str):
        self._update_btn.setText(f"↑ {latest} available — click to update")
        self._update_btn.setVisible(True)

    def _do_restart(self, appimage: str):
        """Called on the main thread after install completes — launch new binary then quit."""
        subprocess.Popen([appimage])
        QApplication.quit()

    def _trigger_update(self):
        self._update_btn.setText("Downloading update…")
        self._update_btn.setEnabled(False)
        raw = "https://raw.githubusercontent.com/michaelpeeters/claude-code-usage/main"
        appimage = os.environ.get("APPIMAGE", "")

        def _install():
            # Strip AppImage-injected library paths so system curl/bash use system libs.
            clean_env = {k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
            if sys.platform == "win32":
                subprocess.Popen(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-Command", f"irm {raw}/install.ps1 | iex"],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            elif sys.platform == "darwin":
                cmd = f"curl -fsSL {raw}/install.sh | bash"
                subprocess.run(["bash", "-c", cmd], check=False, env=clean_env)
                subprocess.Popen(["open", "-a", "Claude Usage"])
                QApplication.quit()
            else:
                cmd = f"curl -fsSL {raw}/install.sh | bash"
                subprocess.run(["bash", "-c", cmd], check=False, env=clean_env)
                if appimage:
                    # Emit signal so the main thread launches the new binary and quits.
                    self._restart_app.emit(appimage)

        threading.Thread(target=_install, daemon=False).start()

    def _watchdog(self):
        if not self.auto_btn.isChecked():
            return
        if time.time() - self._last_refresh >= 5 * 60:
            self.refresh()

    def _toggle_auto(self):
        pass  # watchdog reads auto_btn state directly

    def _tray_clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.setVisible(not self.isVisible())

    def _apply_flags(self):
        flags = (
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
            if self.always_on_top
            else Qt.WindowType.Window
        )
        self.setWindowFlags(flags)

    def _build_ui(self):
        self.setStyleSheet(f"""
            QWidget {{ background: {BG}; color: {FG};
                       font-family: 'Noto Sans', sans-serif; font-size: 12px; }}
            QLabel {{ background: transparent; }}
            QPushButton {{
                background: {BG2}; color: {FG2}; border: 1px solid #333;
                border-radius: 4px; padding: 3px 8px; font-size: 11px;
            }}
            QPushButton:hover {{ background: #333; color: {FG}; }}
            QPushButton:checked {{ background: {ACCENT}; color: #000; border-color: {ACCENT}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(6)

        # ── header ──────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Claude Usage")
        title.setFont(QFont("sans", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {ACCENT};")
        hdr.addWidget(title)
        hdr.addStretch()

        self.pin_btn = QPushButton("📌 Pin")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setChecked(True)
        self.pin_btn.clicked.connect(self._toggle_pin)
        # WindowStaysOnTopHint is ignored on Wayland; hide the button there
        if QGuiApplication.platformName() != "wayland":
            hdr.addWidget(self.pin_btn)

        self.auto_btn = QPushButton("↺ 5m")
        self.auto_btn.setCheckable(True)
        self.auto_btn.setChecked(True)
        self.auto_btn.setToolTip("Auto-refresh every 5 minutes")
        self.auto_btn.clicked.connect(self._toggle_auto)
        hdr.addWidget(self.auto_btn)

        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedWidth(26)
        refresh_btn.clicked.connect(self.refresh)
        hdr.addWidget(refresh_btn)
        root.addLayout(hdr)

        sub = QHBoxLayout()
        sub.setContentsMargins(0, 0, 0, 0)
        disclaimer = QLabel("Unofficial · not by Anthropic")
        disclaimer.setStyleSheet("color: #555; font-size: 9px;")
        self._plan_lbl = QLabel("")
        self._plan_lbl.setStyleSheet("color: #555; font-size: 9px;")
        self._plan_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        sub.addWidget(disclaimer)
        sub.addStretch()
        sub.addWidget(self._plan_lbl)
        root.addLayout(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        root.addWidget(sep)

        # ── today ────────────────────────────────────────────────────────
        self.today_label = QLabel("TODAY")
        self.today_label.setStyleSheet(
            f"color: {FG2}; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
        )
        root.addWidget(self.today_label)

        grid = QHBoxLayout()
        self.today_msgs = self._stat_box("Messages", "—")
        self.today_tokens = self._stat_box("Tokens", "—")
        self.today_sessions = self._stat_box("Sessions", "—")
        grid.addWidget(self.today_msgs[0])
        grid.addWidget(self.today_tokens[0])
        grid.addWidget(self.today_sessions[0])
        root.addLayout(grid)

        # ── 5-hour window ────────────────────────────────────────────────
        win_hdr = QHBoxLayout()
        win_lbl = QLabel("5-HOUR WINDOW")
        win_lbl.setStyleSheet(f"color: {FG2}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        win_hdr.addWidget(win_lbl)
        win_hdr.addStretch()
        self.win_pct_lbl = QLabel("—")
        self.win_pct_lbl.setStyleSheet(f"color: {FG2}; font-size: 10px; font-family: monospace;")
        win_hdr.addWidget(self.win_pct_lbl)
        root.addLayout(win_hdr)

        self.pace_bar = PaceBar()
        root.addWidget(self.pace_bar)

        self.win_detail_lbl = QLabel("—")
        self.win_detail_lbl.setStyleSheet(f"color: {FG2}; font-size: 10px;")
        self.win_detail_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        root.addWidget(self.win_detail_lbl)

        # ── week ─────────────────────────────────────────────────────────
        week_hdr = QHBoxLayout()
        week_lbl = QLabel("LAST 7 DAYS")
        week_lbl.setStyleSheet(f"color: {FG2}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        week_hdr.addWidget(week_lbl)
        week_hdr.addStretch()
        self.week_pct_lbl = QLabel("—")
        self.week_pct_lbl.setStyleSheet(f"color: {FG2}; font-size: 10px; font-family: monospace;")
        week_hdr.addWidget(self.week_pct_lbl)
        root.addLayout(week_hdr)

        self.week_pace_bar = PaceBar()
        root.addWidget(self.week_pace_bar)

        self.week_detail_lbl = QLabel("—")
        self.week_detail_lbl.setStyleSheet(f"color: {FG2}; font-size: 10px;")
        self.week_detail_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        root.addWidget(self.week_detail_lbl)

        self.chart = MiniBarChart()
        root.addWidget(self.chart)

        grid2 = QHBoxLayout()
        self.week_msgs = self._stat_box("Messages", "—")
        self.week_tokens = self._stat_box("Tokens", "—")
        self.week_sessions = self._stat_box("Sessions", "—")
        grid2.addWidget(self.week_msgs[0])
        grid2.addWidget(self.week_tokens[0])
        grid2.addWidget(self.week_sessions[0])
        root.addLayout(grid2)

        # ── model breakdown ──────────────────────────────────────────────
        model_lbl = QLabel("MODELS (7d tokens)")
        model_lbl.setStyleSheet(f"color: {FG2}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        root.addWidget(model_lbl)

        self.model_box = QVBoxLayout()
        self.model_box.setSpacing(2)
        root.addLayout(self.model_box)

        # ── footer ───────────────────────────────────────────────────────
        self._update_btn = QPushButton()
        self._update_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            " color: #22c55e; font-size: 10px; text-align: left; padding: 0; }"
            " QPushButton:hover { text-decoration: underline; }"
        )
        self._update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_btn.clicked.connect(self._trigger_update)
        self._update_btn.setVisible(False)
        root.addWidget(self._update_btn)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        ver_lbl = QLabel(APP_VERSION if APP_VERSION != "dev" else "")
        ver_lbl.setStyleSheet("color: #555; font-size: 10px;")
        self.updated_label = QLabel()
        self.updated_label.setStyleSheet("color: #555; font-size: 10px;")
        self.updated_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        footer.addWidget(ver_lbl)
        footer.addStretch()
        footer.addWidget(self.updated_label)
        root.addLayout(footer)

    def _stat_box(self, label: str, value: str):
        box = QWidget()
        box.setStyleSheet(f"background: {BG2}; border-radius: 6px;")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(1)
        val_lbl = QLabel(value)
        val_lbl.setFont(QFont("monospace", 13, QFont.Weight.Bold))
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {FG2}; font-size: 10px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(val_lbl)
        lay.addWidget(lbl)
        return box, val_lbl

    def _toggle_pin(self):
        self.always_on_top = self.pin_btn.isChecked()
        geo = self.geometry()
        self._apply_flags()
        self.show()
        self.setGeometry(geo)

    def refresh(self):
        if self._refreshing:
            return
        self._refreshing = True
        self.updated_label.setText("Refreshing…")

        def _worker():
            try:
                daily = collect_usage()
                win_tokens = collect_5h_window()
                rl = load_rate_limits()
                self._refresh_done.emit(daily, win_tokens, rl)
            except Exception as e:
                self._refreshing = False
                self.updated_label.setText(f"Error: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_refresh(self, daily: dict, win_tokens: int, rl: dict):
        self._refreshing = False
        self._last_refresh = time.time()

        # 5-hour window — prefer real % from statusline cache, fall back to estimate
        fh = rl.get("five_hour", {})
        sd_for_tip = rl.get("seven_day", {})
        if fh and "used_percentage" in fh:
            fh_pct = fh["used_percentage"]
            reset_ts = fh.get("resets_at")
            reset_str = datetime.fromtimestamp(reset_ts).strftime("resets %H:%M") if reset_ts else "real data"
            # Derive the real ceiling from (tokens / pct) when we have both; otherwise fall back
            if fh_pct > 0 and win_tokens > 0:
                implied_limit = int(win_tokens / (fh_pct / 100))
                self.pace_bar.set_value(win_tokens, implied_limit)
                self.win_detail_lbl.setText(
                    f"{reset_str} · {fmt_tokens(win_tokens)} / {fmt_tokens(implied_limit)}"
                )
                self._plan_lbl.setText("~" + _infer_plan(implied_limit))
            else:
                self.pace_bar.set_value(int(fh_pct), 100)
                self.win_detail_lbl.setText(f"{reset_str} · {fmt_tokens(win_tokens)} in last 5h")
            self.win_pct_lbl.setText(f"{fh_pct:.0f}%")
            icon_pct = fh_pct
        else:
            ratio = min(1.0, win_tokens / THROTTLE_ESTIMATE)
            pct = int(ratio * 100)
            self.pace_bar.set_value(win_tokens, THROTTLE_ESTIMATE)
            self.win_pct_lbl.setText(f"{pct}%")
            self.win_detail_lbl.setText(f"{fmt_tokens(win_tokens)} / ~{fmt_tokens(THROTTLE_ESTIMATE)} est.")
            icon_pct = pct

        icon = make_usage_icon(icon_pct)
        self.setWindowIcon(icon)
        if self._tray:
            sd_pct = sd_for_tip.get("used_percentage", 0)
            self._tray.setIcon(icon)
            self._tray.setToolTip(f"Claude Usage\n5h: {icon_pct:.0f}%  ·  7d: {sd_pct:.0f}%")

        today = datetime.now().strftime("%Y-%m-%d")
        days_7 = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

        # today stats
        td = daily.get(today, {})
        self.today_msgs[1].setText(str(td.get("messages", 0)))
        self.today_tokens[1].setText(fmt_tokens(td.get("tokens", 0)))
        self.today_sessions[1].setText(str(td.get("sessions", 0)))

        # week stats + chart data
        w_msgs = w_tokens = w_sessions = 0
        chart_data = []
        week_models: dict[str, int] = defaultdict(int)
        for d in days_7:
            v = daily.get(d, {})
            w_msgs += v.get("messages", 0)
            w_tokens += v.get("tokens", 0)
            w_sessions += v.get("sessions", 0)
            chart_data.append((d, v.get("tokens", 0), d == today))
            for model, toks in v.get("models", {}).items():
                week_models[model] += toks

        self.week_msgs[1].setText(str(w_msgs))
        self.week_tokens[1].setText(fmt_tokens(w_tokens))
        self.week_sessions[1].setText(str(w_sessions))
        sd = rl.get("seven_day", {})
        if sd and "used_percentage" in sd:
            sd_pct = sd["used_percentage"]
            reset_ts = sd.get("resets_at")
            reset_str = (
                datetime.fromtimestamp(reset_ts).strftime("resets %a %H:%M") if reset_ts else "real data"
            )
            if sd_pct > 0 and w_tokens > 0:
                implied_week_limit = int(w_tokens / (sd_pct / 100))
                self.week_pace_bar.set_value(w_tokens, implied_week_limit)
                self.week_detail_lbl.setText(
                    f"{reset_str} · {fmt_tokens(w_tokens)} / {fmt_tokens(implied_week_limit)}"
                )
            else:
                self.week_pace_bar.set_value(int(sd_pct), 100)
                self.week_detail_lbl.setText(f"{reset_str} · {fmt_tokens(w_tokens)} this week")
            self.week_pct_lbl.setText(f"{sd_pct:.0f}%")
        else:
            w_pct = int(min(1.0, w_tokens / WEEK_ESTIMATE) * 100)
            self.week_pace_bar.set_value(w_tokens, WEEK_ESTIMATE)
            self.week_pct_lbl.setText(f"{w_pct}%")
            self.week_detail_lbl.setText(f"{fmt_tokens(w_tokens)} / ~{fmt_tokens(WEEK_ESTIMATE)} est.")
        self.chart.set_data(chart_data)

        # model breakdown
        while self.model_box.count():
            item = self.model_box.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        for model, toks in sorted(week_models.items(), key=lambda x: -x[1]):
            row = QHBoxLayout()
            lbl = QLabel(model)
            lbl.setStyleSheet(f"color: {FG2};")
            val = QLabel(fmt_tokens(toks))
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            val.setStyleSheet(f"color: {FG}; font-family: monospace;")
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(val)
            w = QWidget()
            w.setLayout(row)
            self.model_box.addWidget(w)

        self.updated_label.setText(f"Updated {datetime.now().strftime('%H:%M:%S')}")

    def closeEvent(self, event):
        _save_position(self.pos())
        super().closeEvent(event)


def _save_position(pos) -> None:
    try:
        POS_CACHE.write_text(json.dumps({"x": pos.x(), "y": pos.y()}))
    except Exception:
        pass


def _load_position():
    """Return (x, y) from cache if on-screen, else None."""
    try:
        data = json.loads(POS_CACHE.read_text())
        x, y = int(data["x"]), int(data["y"])
        screens = QGuiApplication.screens()
        if any(s.availableGeometry().contains(x + 10, y + 10) for s in screens):
            return x, y
    except Exception:
        pass
    return None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Claude Usage")
    win = UsageWindow()
    pos = _load_position()
    if pos:
        win.move(*pos)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
