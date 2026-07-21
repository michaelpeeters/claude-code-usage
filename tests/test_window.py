"""Integration tests for UsageWindow — requires QApplication, runs offscreen."""

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("DISPLAY", ":99")

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

from claude_usage import MiniBarChart, PaceBar, UsageWindow, collect_live_contexts, fmt_tokens


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _wait_for_refresh(win, qapp, timeout: float = 3.0) -> None:
    """Pump the Qt event loop until the background refresh thread finishes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if not win._refreshing:
            return
        time.sleep(0.02)
    raise TimeoutError("refresh() did not complete within timeout")


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
        _wait_for_refresh(win, qapp)  # initial refresh from __init__
        win.refresh()
        _wait_for_refresh(win, qapp)
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
        _wait_for_refresh(win, qapp)
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


def test_check_for_update_emits_signal(qapp, tmp_path):
    """_check_for_update should emit _update_available when a newer version exists.
    Mocks the network call so the test is offline-safe."""
    import json
    from unittest.mock import MagicMock

    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({"tag_name": "v9.9.9"}).encode()
    fake_response.__enter__ = lambda s: s
    fake_response.__exit__ = MagicMock(return_value=False)

    received: list[str] = []

    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
        patch("claude_usage.APP_VERSION", "v0.0.1"),
        patch("claude_usage.urllib.request.urlopen", return_value=fake_response),
    ):
        win = UsageWindow()
        win._update_available.connect(received.append)
        win._check_for_update()  # run synchronously in test

    assert received == ["v9.9.9"]
    win.close()


@pytest.mark.skipif(sys.platform == "win32", reason="CA paths are Unix-only")
def test_check_for_update_uses_system_ca(tmp_path):
    """_check_for_update should pass the system CA bundle to ssl.create_default_context."""
    import json
    from unittest.mock import MagicMock

    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({"tag_name": "v0.0.1"}).encode()
    fake_response.__enter__ = lambda s: s
    fake_response.__exit__ = MagicMock(return_value=False)

    ctx_created_with: list = []

    def fake_create_default_context(cafile=None):
        ctx_created_with.append(cafile)
        return MagicMock()

    # Simulate only /etc/ssl/cert.pem existing (Arch/Manjaro)
    def fake_path_exists(self):
        return str(self) == "/etc/ssl/cert.pem"

    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
        patch("claude_usage.APP_VERSION", "v0.0.1"),
        patch("claude_usage.urllib.request.urlopen", return_value=fake_response),
        patch("claude_usage.ssl.create_default_context", side_effect=fake_create_default_context),
        patch("claude_usage.Path.exists", fake_path_exists),
    ):
        win = UsageWindow()
        win._check_for_update()

    assert "/etc/ssl/cert.pem" in ctx_created_with
    win.close()


@pytest.mark.skipif(sys.platform != "linux", reason="LD_LIBRARY_PATH stripping is Linux/AppImage-specific")
def test_trigger_update_strips_ld_library_path(qapp, tmp_path):
    """_trigger_update must not pass LD_LIBRARY_PATH to curl — AppImage injects an
    incompatible bundled libssl that breaks system curl on Manjaro/Arch."""
    from unittest.mock import MagicMock

    captured_envs: list[dict] = []

    def fake_run(args, **kwargs):
        captured_envs.append(kwargs.get("env", {}))
        return MagicMock(returncode=0)

    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
        patch("claude_usage.os.environ", {**os.environ, "LD_LIBRARY_PATH": "/bad/path", "APPIMAGE": ""}),
        patch("claude_usage.subprocess.run", side_effect=fake_run),
    ):
        win = UsageWindow()
        win._trigger_update()
        # Give the thread a moment to run
        import time

        time.sleep(0.5)

    assert captured_envs, "subprocess.run was never called"
    assert "LD_LIBRARY_PATH" not in captured_envs[0], "LD_LIBRARY_PATH must be stripped from curl env"
    assert "LD_PRELOAD" not in captured_envs[0]
    win.close()


def test_window_shows_update_banner(qapp, tmp_path):
    """_show_update_banner should make the update button visible with version text."""
    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
    ):
        win = UsageWindow()
        assert win._update_btn.isHidden()
        win._show_update_banner("v9.9.9")
        assert not win._update_btn.isHidden()
        assert "v9.9.9" in win._update_btn.text()
        win.close()


def test_refresh_is_non_blocking(qapp, tmp_path):
    """refresh() must return immediately and set _refreshing=True while work runs."""
    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
    ):
        win = UsageWindow()
        _wait_for_refresh(win, qapp)  # drain initial refresh
        win.refresh()
        # _refreshing should be True immediately (thread not done yet) OR the thread
        # was so fast it already cleared it — either way the label updates eventually.
        _wait_for_refresh(win, qapp)
        assert not win._refreshing
        assert "Updated" in win.updated_label.text()
        win.close()


def test_refresh_guard_prevents_overlap(qapp, tmp_path):
    """A second refresh() call while one is in flight must be a no-op."""
    barrier_entered = threading.Event()
    barrier_release = threading.Event()

    original_collect = __import__("claude_usage").collect_usage

    def slow_collect():
        barrier_entered.set()
        barrier_release.wait(timeout=2.0)
        return original_collect()

    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
        patch("claude_usage.collect_usage", side_effect=slow_collect),
    ):
        win = UsageWindow()
        _wait_for_refresh(win, qapp)  # drain initial

        barrier_release.clear()
        win.refresh()
        barrier_entered.wait(timeout=2.0)
        assert win._refreshing

        # Second call while first is blocked must be skipped.
        win.refresh()
        qapp.processEvents()
        assert win._refreshing  # still the original thread, not a new one

        barrier_release.set()
        _wait_for_refresh(win, qapp)
        win.close()


def test_watchdog_triggers_refresh_after_elapsed_time(qapp, tmp_path):
    """_watchdog must call refresh() when wall-clock time since last refresh exceeds 5 min."""
    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
    ):
        win = UsageWindow()
        _wait_for_refresh(win, qapp)
        # Pretend the last refresh happened 6 minutes ago.
        win._last_refresh = time.time() - 6 * 60
        win.auto_btn.setChecked(True)
        win._watchdog()
        assert win._refreshing  # watchdog triggered a refresh
        _wait_for_refresh(win, qapp)
        win.close()


def test_watchdog_skips_when_auto_off(qapp, tmp_path):
    """_watchdog must not trigger a refresh when the auto-refresh button is unchecked."""
    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
    ):
        win = UsageWindow()
        _wait_for_refresh(win, qapp)
        win.auto_btn.setChecked(False)
        win._last_refresh = time.time() - 6 * 60
        win._watchdog()
        assert not win._refreshing
        win.close()


def _live_entry(inp: int, cache_create: int = 0, cache_read: int = 0, model: str = "claude-opus-4-8") -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    return {
        "type": "assistant",
        "timestamp": ts,
        "sessionId": "s1",
        "cwd": "/home/user/myproject",
        "message": {
            "model": model,
            "usage": {
                "input_tokens": inp,
                "output_tokens": 1000,
                "cache_creation_input_tokens": cache_create,
                "cache_read_input_tokens": cache_read,
            },
        },
    }


def test_collect_live_contexts_pct_and_limit(tmp_path):
    """collect_live_contexts reads the last assistant usage and computes pct against model limit."""
    jsonl = tmp_path / "myproj" / "session.jsonl"
    jsonl.parent.mkdir(parents=True)
    # Opus 4.8 limit = 1_000_000; used = 100k + 50k + 200k + 1k output = 351k → 35.1%
    jsonl.write_text(json.dumps(_live_entry(100_000, cache_create=50_000, cache_read=200_000)) + "\n")

    with patch("claude_usage.PROJECTS_DIR", tmp_path):
        results = collect_live_contexts()

    assert len(results) == 1
    r = results[0]
    assert r["project"] == "myproject"
    assert r["model"] == "Opus"
    assert r["used"] == 351_000
    assert r["limit"] == 1_000_000
    assert abs(r["pct"] - 35.1) < 0.1


def test_collect_live_contexts_ignores_old_files(tmp_path):
    """Files with mtime older than LIVE_WINDOW_MIN minutes must be ignored."""
    jsonl = tmp_path / "old" / "session.jsonl"
    jsonl.parent.mkdir(parents=True)
    jsonl.write_text(json.dumps(_live_entry(100_000)) + "\n")
    # Backdate mtime to 2 hours ago
    old_time = time.time() - 2 * 3600
    os.utime(jsonl, (old_time, old_time))

    with patch("claude_usage.PROJECTS_DIR", tmp_path):
        results = collect_live_contexts()

    assert results == []


def test_collect_live_contexts_sonnet_limit(tmp_path):
    """Sonnet sessions use the default 200k context limit."""
    jsonl = tmp_path / "proj" / "chat.jsonl"
    jsonl.parent.mkdir(parents=True)
    jsonl.write_text(json.dumps(_live_entry(100_000, model="claude-sonnet-4-6")) + "\n")

    with patch("claude_usage.PROJECTS_DIR", tmp_path):
        results = collect_live_contexts()

    assert len(results) == 1
    assert results[0]["limit"] == 200_000
    # 100k input + 1k output = 101k / 200k = 50.5%
    assert abs(results[0]["pct"] - 50.5) < 0.1


def test_collect_live_contexts_skips_synthetic_model(tmp_path):
    """Entries with model == '<synthetic>' (login sessions) must be skipped."""
    jsonl = tmp_path / "proj" / "chat.jsonl"
    jsonl.parent.mkdir(parents=True)
    jsonl.write_text(json.dumps(_live_entry(100_000, model="<synthetic>")) + "\n")

    with patch("claude_usage.PROJECTS_DIR", tmp_path):
        results = collect_live_contexts()

    assert results == []


def test_section_collapse_and_persist(qapp, tmp_path):
    """Clicking a section header hides its container and persists the state."""
    settings_file = tmp_path / "settings.json"
    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
        patch("claude_usage.SETTINGS_CACHE", settings_file),
    ):
        win = UsageWindow()
        # Default on first startup: all sections collapsed
        assert win._ctx_container.isHidden()
        assert win._usage_container.isHidden()
        assert win._models_container.isHidden()

        # Toggle context section expanded
        win._ctx_hdr_btn.click()
        assert not win._ctx_container.isHidden()
        assert settings_file.exists()
        saved = json.loads(settings_file.read_text())
        assert saved["collapsed"]["context"] is False

        # New window reads persisted state: context expanded, others still collapsed
        win2 = UsageWindow()
        assert not win2._ctx_container.isHidden()
        assert win2._usage_container.isHidden()
        assert win2._models_container.isHidden()

        win.close()
        win2.close()


def test_extra_usage_label_hidden_without_data(qapp, tmp_path):
    """Without extra_usage in the rate-limits cache the label stays hidden."""
    _make_jsonl(tmp_path, [_entry(1, 100, 50)])
    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
        patch("claude_usage.load_rate_limits", return_value={}),
    ):
        win = UsageWindow()
        _wait_for_refresh(win, qapp)
        assert not win.extra_lbl.isVisibleTo(win)
        win.close()


def test_extra_usage_label_shows_credits(qapp, tmp_path):
    """extra_usage from the statusline cache renders used/limit in dollars (cents in)."""
    _make_jsonl(tmp_path, [_entry(1, 100, 50)])
    fake_rl = {
        "five_hour": {"used_percentage": 10.0, "resets_at": None},
        "seven_day": {},
        "extra_usage": {
            "is_enabled": True,
            "monthly_limit": 2500,  # cents
            "used_credits": 321,  # cents
            "utilization": 12.84,
        },
    }
    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
        patch("claude_usage.load_rate_limits", return_value=fake_rl),
    ):
        win = UsageWindow()
        _wait_for_refresh(win, qapp)
        assert win.extra_lbl.isVisibleTo(win)
        assert "$3.21" in win.extra_lbl.text()
        assert "$25" in win.extra_lbl.text()
        win.close()


def test_week_cost_label_from_transcripts(qapp, tmp_path):
    """The API-rate cost line reflects local transcript usage."""
    _make_jsonl(tmp_path, [_entry(1, 1_000_000, 0)])  # sonnet input → $3.00
    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
        patch("claude_usage.load_rate_limits", return_value={}),
    ):
        win = UsageWindow()
        _wait_for_refresh(win, qapp)
        assert win.week_cost_lbl.isVisibleTo(win)
        assert "$3.00" in win.week_cost_lbl.text()
        win.close()
