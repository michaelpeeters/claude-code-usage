"""Integration tests for UsageWindow — requires QApplication, runs offscreen."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("DISPLAY", ":99")

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

from claude_usage import MiniBarChart, PaceBar, UsageWindow, fmt_tokens


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_jsonl(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "proj" / "chat.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return p


def _entry(hours_ago: float, inp: int, out: int) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "type": "assistant",
        "timestamp": ts,
        "sessionId": "s1",
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": inp, "output_tokens": out},
        },
    }


def test_window_instantiates(qapp, tmp_path):
    """Window should construct and show without errors."""
    _make_jsonl(tmp_path, [_entry(1, 100, 50)])
    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
    ):
        win = UsageWindow()
        win.show()
        assert win.isVisible()
        win.close()


def test_window_refresh_updates_labels(qapp, tmp_path):
    """refresh() should populate today's message count from live JSONL data."""
    _make_jsonl(tmp_path, [_entry(0.5, 200, 100), _entry(1.5, 50, 25)])
    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
    ):
        win = UsageWindow()
        win.refresh()
        assert win.today_msgs[1].text() == "2"
        assert win.today_tokens[1].text() == fmt_tokens(375)
        win.close()


def test_refresh_implied_limit_detail(qapp, tmp_path):
    """When real rate-limit % and token count are both non-zero, the detail
    line should show 'tokens / implied_ceiling' rather than the fallback text."""
    _make_jsonl(tmp_path, [_entry(0.5, 300_000, 200_000)])  # 500K tokens in last 5h
    fake_rl = {"five_hour": {"used_percentage": 25.0, "resets_at": None}, "seven_day": {}}
    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
        patch("claude_usage.load_rate_limits", return_value=fake_rl),
    ):
        win = UsageWindow()
        win.refresh()
        detail = win.win_detail_lbl.text()
        # implied ceiling = 500K / 0.25 = 2M; detail must contain both counts
        assert "500K" in detail or "2.0M" in detail  # tokens shown
        assert "/" in detail  # format is "X / Y"
        assert "est." not in detail  # not the fallback
        win.close()


def test_paint_pace_bar(qapp):
    """PaceBar.paintEvent should not crash at various fill levels."""
    bar = PaceBar()
    bar.resize(200, 8)
    px = QPixmap(QSize(200, 8))
    for value, maximum in [(0, 100), (50, 100), (100, 100), (1_500_000, 1_500_000)]:
        bar.set_value(value, maximum)
        p = QPainter(px)
        bar.render(p)
        p.end()


def test_paint_mini_bar_chart(qapp):
    """MiniBarChart.paintEvent should not crash with typical and edge-case data."""
    chart = MiniBarChart()
    chart.resize(280, 60)
    px = QPixmap(QSize(280, 60))
    for data in [
        [],  # empty
        [("2026-06-10", 0, False)],  # all-zero values
        [("2026-06-10", 1_000_000, False), ("2026-06-11", 500_000, True)],
    ]:
        chart.set_data(data)
        p = QPainter(px)
        chart.render(p)
        p.end()


def test_window_shows_update_banner(qapp, tmp_path):
    """_show_update_banner should make the update label visible with version text."""
    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
    ):
        win = UsageWindow()
        assert win._update_lbl.isHidden()
        win._show_update_banner("v9.9.9")
        assert not win._update_lbl.isHidden()
        assert "v9.9.9" in win._update_lbl.text()
        win.close()
