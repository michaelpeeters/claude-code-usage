#!/usr/bin/env python3
"""Generate synthetic README screenshots for three typical usage scenarios."""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

import claude_usage
claude_usage.APP_VERSION = "v1.0.9"  # set before importing UsageWindow so version label renders
from claude_usage import UsageWindow

# suppress update banner in screenshots
UsageWindow._check_for_update = lambda self: None

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


SCENARIOS = [
    # (filename, daily_tokens[7], win_tokens, rl_override)
    # Pro: 5h ceiling ~1.5M → 16% ≈ 240K in window
    (
        "screenshot_pro_low.png",
        _daily([180_000, 95_000, 220_000, 310_000, 0, 140_000, 75_000]),
        240_000,
        {
            "five_hour": {"used_percentage": 16.0, "resets_at": NEXT_5H_RESET},
            "seven_day": {"used_percentage": 14.0, "resets_at": NEXT_WEEK_RESET},
        },
    ),
    # Max 5x: 5h ceiling ~3M → 38% ≈ 1.14M in window
    (
        "screenshot_max5x_medium.png",
        _daily([1_200_000, 980_000, 1_500_000, 750_000, 1_100_000, 600_000, 420_000]),
        1_140_000,
        {
            "five_hour": {"used_percentage": 38.0, "resets_at": NEXT_5H_RESET},
            "seven_day": {"used_percentage": 43.0, "resets_at": NEXT_WEEK_RESET},
        },
    ),
    # Max 20x: 5h ceiling ~10M → 71% ≈ 7.1M in window
    (
        "screenshot_max20x_high.png",
        _daily([4_800_000, 5_200_000, 3_900_000, 6_100_000, 4_400_000, 5_700_000, 2_100_000]),
        7_100_000,
        {
            "five_hour": {"used_percentage": 71.0, "resets_at": NEXT_5H_RESET},
            "seven_day": {"used_percentage": 82.0, "resets_at": NEXT_WEEK_RESET},
        },
    ),
]


def shoot(app: QApplication, scenario: tuple) -> None:
    filename, daily, win_tokens, rl = scenario
    win = UsageWindow()
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
