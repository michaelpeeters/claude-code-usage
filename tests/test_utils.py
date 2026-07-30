"""Unit tests for pure utility functions in claude_usage."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is importable without a QApplication for pure-function tests.
# PyQt6 is imported at module level in claude_usage, so we need to satisfy it.
os.environ.setdefault("DISPLAY", ":99")  # headless-safe fallback

from claude_usage import collect_5h_window, collect_usage, fmt_tokens

# ---------------------------------------------------------------------------
# fmt_tokens
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n, expected",
    [
        (0, "0"),
        (999, "999"),
        (1_000, "1K"),
        (42_500, "42K"),  # :.0f truncates, not rounds
        (999_999, "1000K"),
        (1_000_000, "1.0M"),
        (1_500_000, "1.5M"),
        (10_000_000, "10.0M"),
    ],
)
def test_fmt_tokens(n, expected):
    assert fmt_tokens(n) == expected


# ---------------------------------------------------------------------------
# collect_5h_window
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _assistant_entry(ts: datetime, input_tokens: int, output_tokens: int, session_id: str = "s1") -> dict:
    return {
        "type": "assistant",
        "timestamp": ts.isoformat(),
        "sessionId": session_id,
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        },
    }


def test_collect_5h_window_counts_recent(tmp_path):
    now = datetime.now(timezone.utc)
    recent = now - timedelta(hours=2)
    old = now - timedelta(hours=6)

    jsonl = tmp_path / "proj" / "chat.jsonl"
    _write_jsonl(
        jsonl,
        [
            _assistant_entry(recent, 100, 50),  # within 5h -> counted
            _assistant_entry(old, 9999, 9999),  # outside 5h -> ignored
        ],
    )

    with patch("claude_usage.PROJECTS_DIR", tmp_path):
        total = collect_5h_window()

    assert total == 150


def test_collect_5h_window_empty(tmp_path):
    with patch("claude_usage.PROJECTS_DIR", tmp_path):
        assert collect_5h_window() == 0


def test_collect_5h_window_skips_non_assistant(tmp_path):
    now = datetime.now(timezone.utc)
    jsonl = tmp_path / "p" / "f.jsonl"
    _write_jsonl(
        jsonl,
        [
            {
                "type": "human",
                "timestamp": now.isoformat(),
                "message": {"usage": {"input_tokens": 500}},
            },
        ],
    )
    with patch("claude_usage.PROJECTS_DIR", tmp_path):
        assert collect_5h_window() == 0


# ---------------------------------------------------------------------------
# collect_usage
# ---------------------------------------------------------------------------


def test_collect_usage_today_live(tmp_path):
    """Live JSONL entries for today are aggregated correctly."""
    today = datetime.now(timezone.utc)
    jsonl = tmp_path / "proj" / "s.jsonl"
    _write_jsonl(
        jsonl,
        [
            _assistant_entry(today, 200, 100, session_id="sess-a"),
            _assistant_entry(today, 300, 150, session_id="sess-b"),
        ],
    )

    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "nonexistent.json"),
    ):
        daily = collect_usage()

    date_str = today.strftime("%Y-%m-%d")
    assert date_str in daily
    d = daily[date_str]
    assert d["messages"] == 2
    assert d["tokens"] == 750  # (200+100) + (300+150)
    assert d["sessions"] == 2


def test_collect_usage_ignores_placeholder_models(tmp_path):
    """Entries with model='<thinking>' or similar are skipped for model tally."""
    today = datetime.now(timezone.utc)
    jsonl = tmp_path / "p" / "f.jsonl"
    entry = {
        "type": "assistant",
        "timestamp": today.isoformat(),
        "sessionId": "s",
        "message": {
            "model": "<thinking>",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    }
    jsonl.parent.mkdir(parents=True)
    jsonl.write_text(json.dumps(entry) + "\n")

    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "nonexistent.json"),
    ):
        daily = collect_usage()

    date_str = today.strftime("%Y-%m-%d")
    assert daily[date_str]["models"] == {}


def test_collect_usage_cache_seeds_older_days(tmp_path):
    """Stats-cache data for days before cache_cutoff is seeded into results."""
    cache = {
        "lastComputedDate": "2026-06-14",
        "dailyActivity": [
            {
                "date": "2026-06-10",
                "messageCount": 50,
                "toolCallCount": 10,
                "sessionCount": 3,
            },
        ],
        "dailyModelTokens": [],
    }
    cache_file = tmp_path / "stats-cache.json"
    cache_file.write_text(json.dumps(cache))

    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", cache_file),
    ):
        daily = collect_usage()

    assert daily["2026-06-10"]["messages"] == 50
    assert daily["2026-06-10"]["sessions"] == 3  # cache count is resolved into "sessions"


def test_collect_5h_window_skips_stale_files(tmp_path):
    """Files not modified in the last 5 hours are skipped without being opened."""
    now = datetime.now(timezone.utc)
    recent = now - timedelta(hours=2)

    jsonl = tmp_path / "proj" / "chat.jsonl"
    _write_jsonl(jsonl, [_assistant_entry(recent, 100, 50)])

    # Back-date mtime to 6 hours ago so the mtime guard skips the file.
    stale_ts = (now - timedelta(hours=6)).timestamp()
    os.utime(jsonl, (stale_ts, stale_ts))

    with patch("claude_usage.PROJECTS_DIR", tmp_path):
        total = collect_5h_window()

    assert total == 0  # file skipped via mtime, no tokens counted


def test_collect_usage_skips_files_before_cache_cutoff(tmp_path):
    """JSONL files with mtime before the cache cutoff date are not read."""
    cache_cutoff = "2026-06-14"
    cache = {
        "lastComputedDate": cache_cutoff,
        "dailyActivity": [],
        "dailyModelTokens": [],
    }
    cache_file = tmp_path / "stats-cache.json"
    cache_file.write_text(json.dumps(cache))

    # A JSONL file for a date before the cutoff, with a matching old mtime.
    old_ts = datetime(2026, 6, 10, tzinfo=timezone.utc)
    jsonl = tmp_path / "proj" / "old.jsonl"
    _write_jsonl(jsonl, [_assistant_entry(old_ts, 500, 500)])
    stale_mtime = old_ts.timestamp()
    os.utime(jsonl, (stale_mtime, stale_mtime))

    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", cache_file),
    ):
        daily = collect_usage()

    # Old file skipped; no live overlay for that date.
    assert daily.get("2026-06-10", {}).get("messages", 0) == 0


# ---------------------------------------------------------------------------
# estimate_cost / cost aggregation
# ---------------------------------------------------------------------------

from claude_usage import estimate_cost, fmt_cost  # noqa: E402


def test_estimate_cost_sonnet_all_buckets():
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "cache_read_input_tokens": 1_000_000,
        "cache_creation_input_tokens": 1_000_000,
    }
    # sonnet: $3 in, $15 out, cache read 0.1×3, cache write 1.25×3
    expected = 3.0 + 15.0 + 0.3 + 3.75
    assert estimate_cost("claude-sonnet-5", usage) == pytest.approx(expected)


def test_estimate_cost_unknown_model_is_zero():
    assert estimate_cost("gpt-oss", {"input_tokens": 1_000_000}) == 0.0


def test_estimate_cost_prefix_specificity():
    usage = {"input_tokens": 1_000_000}
    assert estimate_cost("claude-opus-4-8", usage) == pytest.approx(5.0)
    assert estimate_cost("claude-opus-4-1", usage) == pytest.approx(15.0)
    assert estimate_cost("claude-fable-5", usage) == pytest.approx(10.0)


def test_fmt_cost():
    assert fmt_cost(0.5) == "$0.50"
    assert fmt_cost(99.994) == "$99.99"
    assert fmt_cost(1234.0) == "$1,234"


def test_collect_usage_accumulates_week_cost(tmp_path):
    now = datetime.now(timezone.utc)
    jsonl = tmp_path / "proj" / "chat.jsonl"
    entry = _assistant_entry(now - timedelta(hours=1), 1_000_000, 0)
    old_entry = _assistant_entry(now - timedelta(days=10), 1_000_000, 0)
    _write_jsonl(jsonl, [entry, old_entry])

    with (
        patch("claude_usage.PROJECTS_DIR", tmp_path),
        patch("claude_usage.STATS_CACHE", tmp_path / "none.json"),
    ):
        daily = collect_usage()

    today = now.strftime("%Y-%m-%d")
    # sonnet 4.6 input at $3/MTok; the 10-day-old entry is outside the week window
    assert daily[today]["cost"] == pytest.approx(3.0)
    total_cost = sum(v.get("cost", 0.0) for v in daily.values())
    assert total_cost == pytest.approx(3.0)
