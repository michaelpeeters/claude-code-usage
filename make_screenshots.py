#!/usr/bin/env python3
"""Generate synthetic README screenshots for three typical usage scenarios."""

import sys
import time
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

import claude_usage
claude_usage.APP_VERSION = "v1.1.0"  # set before importing UsageWindow so version label renders
from claude_usage import UsageWindow

# suppress update banner in screenshots
UsageWindow._check_for_update = lambda self: None

# isolated temp dir for settings/data — screenshots must not read real ~/.claude state
_TMPDIR = tempfile.mkdtemp()

OUTPUT = Path(__file__).parent / "packaging"

# today and the 6 days before it
TODAY = datetime.now().strftime("%Y-%m-%d")
DAYS = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

NEXT_WEEK_RESET = time.time() + 5 * 24 * 3600  # ~5 days from now (Wed)
NEXT_5H_RESET   = time.time() + 2 * 3600       # ~2 h from now


def _daily(token_days: list[int], msgs_per_1k: float = 0.6) -> dict:
    """Build a daily dict from a list of 7 token counts (oldest→newest)."""
    daily: dict = {}
    for d, toks in zip(DAYS, token_days):
        is_today = d == TODAY
        msgs = max(1, int(toks * msgs_per_1k / 1000))
        sessions = max(1, msgs // 8)
        daily[d] = {
            "messages": msgs,
            "tokens": toks,
            "sessions": sessions,
            "models": {"Sonnet": int(toks * 0.75), "Opus": int(toks * 0.20), "Haiku": int(toks * 0.05)},
        }
        if is_today:
            daily[d]["sessions"] = max(1, sessions // 3)
    return daily


LIVE_CONTEXTS_SAMPLE = [
    {"project": "opus-project", "model": "Opus", "used": 330_000, "limit": 1_000_000, "pct": 33.0},
    {"project": "my-app", "model": "Sonnet", "used": 176_000, "limit": 200_000, "pct": 88.0},
]

_ALL_COLLAPSED = {"context": False, "usage": True, "models": True}

SCENARIOS = [
    # (filename, daily, win_tokens, rl, live_contexts, collapsed)
    # Live context expanded, usage+models collapsed — compact default view
    (
        "screenshot_live_context.png",
        _daily([1_200_000, 980_000, 1_500_000, 750_000, 1_100_000, 600_000, 420_000]),
        1_140_000,
        {
            "five_hour": {"used_percentage": 38.0, "resets_at": NEXT_5H_RESET},
            "seven_day": {"used_percentage": 43.0, "resets_at": NEXT_WEEK_RESET},
        },
        LIVE_CONTEXTS_SAMPLE,
        _ALL_COLLAPSED,
    ),
    # Everything collapsed — minimal footprint
    (
        "screenshot_collapsed.png",
        _daily([1_200_000, 980_000, 1_500_000, 750_000, 1_100_000, 600_000, 420_000]),
        1_140_000,
        {
            "five_hour": {"used_percentage": 38.0, "resets_at": NEXT_5H_RESET},
            "seven_day": {"used_percentage": 43.0, "resets_at": NEXT_WEEK_RESET},
        },
        LIVE_CONTEXTS_SAMPLE,
        {"context": True, "usage": True, "models": True},
    ),
    # Usage expanded, no active sessions — Pro plan
    (
        "screenshot_pro_low.png",
        _daily([180_000, 95_000, 220_000, 310_000, 0, 140_000, 75_000]),
        240_000,
        {
            "five_hour": {"used_percentage": 16.0, "resets_at": NEXT_5H_RESET},
            "seven_day": {"used_percentage": 14.0, "resets_at": NEXT_WEEK_RESET},
        },
        [],
        {"context": False, "usage": False, "models": True},
    ),
    # Usage expanded — Max 20x high usage
    (
        "screenshot_max20x_high.png",
        _daily([4_800_000, 5_200_000, 3_900_000, 6_100_000, 4_400_000, 5_700_000, 2_100_000]),
        7_100_000,
        {
            "five_hour": {"used_percentage": 71.0, "resets_at": NEXT_5H_RESET},
            "seven_day": {"used_percentage": 82.0, "resets_at": NEXT_WEEK_RESET},
        },
        [],
        {"context": False, "usage": False, "models": True},
    ),
]


def shoot(app: QApplication, scenario: tuple) -> None:
    filename, daily, win_tokens, rl, live_contexts, collapsed = scenario
    _no_settings = Path(_TMPDIR) / f"{filename}.json"
    with (
        patch("claude_usage.SETTINGS_CACHE", _no_settings),
        patch("claude_usage.PROJECTS_DIR", Path(_TMPDIR)),
        patch("claude_usage.STATS_CACHE", Path(_TMPDIR) / "none.json"),
        patch("claude_usage.collect_live_contexts", return_value=[]),
    ):
        win = UsageWindow()
        # drain the initial background refresh while patches are still active
        deadline = time.time() + 3.0
        while win._refreshing and time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)

    win._live_contexts = live_contexts
    for key, val in collapsed.items():
        if val != win._collapsed.get(key, False):
            btn_map = {"context": win._ctx_hdr_btn, "usage": win._usage_hdr_btn, "models": win._models_hdr_btn}
            btn_map[key].click()
            app.processEvents()
    win._apply_refresh(daily, win_tokens, rl)
    win.show()
    app.processEvents()

    # slight delay so Qt finishes painting
    deadline = time.time() + 0.3
    while time.time() < deadline:
        app.processEvents()

    px = win.grab()
    out = OUTPUT / filename
    px.save(str(out))
    print(f"  saved {out}")
    win.close()
    app.processEvents()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Claude Usage")

    for scenario in SCENARIOS:
        shoot(app, scenario)

    print("Done.")


if __name__ == "__main__":
    main()
