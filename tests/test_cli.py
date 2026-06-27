"""Tests for claude_usage_cli — _build_report, _print_text, and --json output."""

import io
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_usage_cli import _build_report, _print_text, fmt_tokens


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _assistant_entry(
    ts: datetime,
    input_tokens: int,
    output_tokens: int,
    model: str = "claude-sonnet-4-6",
    session_id: str = "s1",
    cwd: str = "/home/user/myproject",
) -> dict:
    return {
        "type": "assistant",
        "timestamp": ts.isoformat(),
        "sessionId": session_id,
        "cwd": cwd,
        "message": {
            "model": model,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        },
    }


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


# ---------------------------------------------------------------------------
# _build_report
# ---------------------------------------------------------------------------


def test_build_report_today_stats(tmp_path):
    now = datetime.now(timezone.utc)
    jsonl = tmp_path / "proj" / "chat.jsonl"
    _write_jsonl(jsonl, [
        _assistant_entry(now, 200, 100, session_id="a"),
        _assistant_entry(now, 300, 150, session_id="b"),
    ])

    with (
        patch("claude_usage_cli.PROJECTS_DIR", tmp_path),
        patch("claude_usage_cli.STATS_CACHE", tmp_path / "none.json"),
    ):
        from claude_usage_cli import collect_usage, collect_5h_window, collect_live_contexts, load_rate_limits
        daily = collect_usage()
        report = _build_report(daily, collect_5h_window(), collect_live_contexts(), load_rate_limits())

    t = report["today"]
    assert t["messages"] == 2
    assert t["tokens"] == 750
    assert t["sessions"] == 2


def test_build_report_window_5h_real_data():
    """When rate-limit cache provides a real %, implied limit and plan are set."""
    fake_rl = {
        "five_hour": {"used_percentage": 25.0, "resets_at": None},
        "seven_day": {},
    }
    report = _build_report({}, 500_000, [], fake_rl)
    w = report["window_5h"]
    assert w["pct"] == 25.0
    assert w["used"] == 500_000
    assert w["limit"] == 2_000_000  # 500k / 0.25
    assert w["plan"] is not None
    assert w["estimated"] is False


def test_build_report_window_5h_estimated():
    """Without rate-limit data, window falls back to THROTTLE_ESTIMATE."""
    from claude_usage_cli import THROTTLE_ESTIMATE
    report = _build_report({}, 300_000, [], {})
    w = report["window_5h"]
    assert w["limit"] == THROTTLE_ESTIMATE
    assert w["estimated"] is True


def test_build_report_week_aggregates(tmp_path):
    now = datetime.now(timezone.utc)
    days = [(datetime.now(timezone.utc) - timedelta(days=i)) for i in range(7)]
    jsonl = tmp_path / "p" / "f.jsonl"
    _write_jsonl(jsonl, [_assistant_entry(d, 100, 50, session_id=f"s{i}") for i, d in enumerate(days)])

    with (
        patch("claude_usage_cli.PROJECTS_DIR", tmp_path),
        patch("claude_usage_cli.STATS_CACHE", tmp_path / "none.json"),
    ):
        from claude_usage_cli import collect_usage, collect_5h_window, collect_live_contexts, load_rate_limits
        daily = collect_usage()
        report = _build_report(daily, collect_5h_window(), collect_live_contexts(), load_rate_limits())

    wk = report["week_7d"]
    assert wk["messages"] == 7
    assert wk["used"] == 7 * 150
    assert wk["sessions"] == 7


def test_build_report_daily_rows_length():
    report = _build_report({}, 0, [], {})
    assert len(report["daily"]) == 7


def test_build_report_today_marked(tmp_path):
    report = _build_report({}, 0, [], {})
    today_rows = [d for d in report["daily"] if d["today"]]
    assert len(today_rows) == 1
    assert today_rows[0]["date"] == datetime.now().strftime("%Y-%m-%d")


def test_build_report_models_7d(tmp_path):
    now = datetime.now(timezone.utc)
    jsonl = tmp_path / "p" / "f.jsonl"
    _write_jsonl(jsonl, [
        _assistant_entry(now, 1000, 500, model="claude-sonnet-4-6"),
        _assistant_entry(now, 2000, 1000, model="claude-opus-4-8"),
    ])

    with (
        patch("claude_usage_cli.PROJECTS_DIR", tmp_path),
        patch("claude_usage_cli.STATS_CACHE", tmp_path / "none.json"),
    ):
        from claude_usage_cli import collect_usage, collect_5h_window, collect_live_contexts, load_rate_limits
        daily = collect_usage()
        report = _build_report(daily, collect_5h_window(), collect_live_contexts(), load_rate_limits())

    assert "Sonnet" in report["models_7d"]
    assert "Opus" in report["models_7d"]
    assert report["models_7d"]["Sonnet"] == 1500
    assert report["models_7d"]["Opus"] == 3000


def test_build_report_live_context_compact_soon(tmp_path):
    from claude_usage_cli import COMPACT_WARN_PCT
    now = datetime.now(timezone.utc)
    jsonl = tmp_path / "p" / "f.jsonl"
    # Use tokens that push pct above COMPACT_WARN_PCT (88%)
    inp = int(200_000 * (COMPACT_WARN_PCT + 1) / 100)
    entry = {
        "type": "assistant",
        "timestamp": now.isoformat(),
        "sessionId": "s",
        "cwd": "/home/user/bigproject",
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": inp, "output_tokens": 1000},
        },
    }
    _write_jsonl(jsonl, [entry])

    with patch("claude_usage_cli.PROJECTS_DIR", tmp_path):
        from claude_usage_cli import collect_usage, collect_5h_window, collect_live_contexts, load_rate_limits
        report = _build_report(
            collect_usage(), collect_5h_window(), collect_live_contexts(), load_rate_limits()
        )

    assert report["live_context"][0]["compact_soon"] is True


# ---------------------------------------------------------------------------
# _print_text
# ---------------------------------------------------------------------------


def _capture(report: dict) -> str:
    buf = io.StringIO()
    with patch("builtins.print", lambda *a, **k: buf.write(" ".join(str(x) for x in a) + "\n")):
        _print_text(report)
    return buf.getvalue()


def _minimal_report(**overrides) -> dict:
    base = {
        "generated_at": "2026-06-27T12:00:00",
        "live_context": [],
        "today": {"date": "2026-06-27", "messages": 10, "tokens": 5000, "sessions": 2},
        "window_5h": {"pct": 8.0, "used": 100_000, "limit": 1_250_000, "plan": "Pro", "resets_at": "20:00", "estimated": False},
        "week_7d": {"pct": 12.0, "used": 500_000, "limit": 4_000_000, "resets_at": "Thu 00:00", "messages": 50, "sessions": 5, "estimated": False},
        "models_7d": {"Sonnet": 400_000, "Opus": 100_000},
        "daily": [{"date": "2026-06-27", "tokens": 5000, "messages": 10, "sessions": 2, "today": True}],
    }
    base.update(overrides)
    return base


def test_print_text_contains_section_headers():
    out = _capture(_minimal_report())
    assert "LIVE CONTEXT" in out
    assert "TODAY" in out
    assert "WINDOW_5H" in out
    assert "WEEK_7D" in out
    assert "MODELS_7D" in out
    assert "DAILY" in out


def test_print_text_today_key_values():
    out = _capture(_minimal_report())
    assert "messages=10" in out
    assert "sessions=2" in out
    assert "tokens_raw=5000" in out


def test_print_text_window_key_values():
    out = _capture(_minimal_report())
    assert "pct=8" in out
    assert "plan=Pro" in out
    assert "resets_at=20:00" in out


def test_print_text_estimated_flag():
    r = _minimal_report()
    r["window_5h"]["estimated"] = True
    out = _capture(r)
    assert "estimated=true" in out


def test_print_text_live_context_compact_soon():
    r = _minimal_report(live_context=[
        {"project": "bigproj", "model": "Sonnet", "pct": 89.0, "used": 178_000, "limit": 200_000, "compact_soon": True}
    ])
    out = _capture(r)
    assert "compact_soon=true" in out
    assert "bigproj" in out


def test_print_text_live_context_none():
    out = _capture(_minimal_report(live_context=[]))
    assert "none" in out


def test_print_text_today_marker():
    r = _minimal_report()
    r["daily"] = [
        {"date": "2026-06-26", "tokens": 1000, "messages": 5, "sessions": 1, "today": False},
        {"date": "2026-06-27", "tokens": 5000, "messages": 10, "sessions": 2, "today": True},
    ]
    out = _capture(r)
    assert "today=true" in out


def test_print_text_models_sorted():
    r = _minimal_report(models_7d={"Sonnet": 400_000, "Opus": 100_000})
    out = _capture(r)
    sonnet_pos = out.index("Sonnet")
    opus_pos = out.index("Opus")
    assert sonnet_pos < opus_pos  # highest token count first


# ---------------------------------------------------------------------------
# --json flag via main()
# ---------------------------------------------------------------------------


def test_main_json_flag_produces_valid_json(tmp_path, capsys):
    from claude_usage_cli import main

    with (
        patch("claude_usage_cli.PROJECTS_DIR", tmp_path),
        patch("claude_usage_cli.STATS_CACHE", tmp_path / "none.json"),
        patch("sys.argv", ["claude_usage_cli.py", "--json"]),
    ):
        main()

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert "today" in parsed
    assert "window_5h" in parsed
    assert "week_7d" in parsed
    assert "daily" in parsed
    assert len(parsed["daily"]) == 7


def test_main_text_flag_produces_keyvalue(tmp_path, capsys):
    from claude_usage_cli import main

    with (
        patch("claude_usage_cli.PROJECTS_DIR", tmp_path),
        patch("claude_usage_cli.STATS_CACHE", tmp_path / "none.json"),
        patch("sys.argv", ["claude_usage_cli.py", "--text"]),
    ):
        main()

    captured = capsys.readouterr()
    assert "CLAUDE USAGE" in captured.out
    assert "messages=" in captured.out
    assert "{" not in captured.out


def test_main_default_is_human(tmp_path, capsys):
    from claude_usage_cli import main

    with (
        patch("claude_usage_cli.PROJECTS_DIR", tmp_path),
        patch("claude_usage_cli.STATS_CACHE", tmp_path / "none.json"),
        patch("sys.argv", ["claude_usage_cli.py"]),
    ):
        main()

    captured = capsys.readouterr()
    assert "Claude Usage" in captured.out
    assert "█" in captured.out  # bars rendered
    assert "{" not in captured.out


# ---------------------------------------------------------------------------
# _print_human
# ---------------------------------------------------------------------------


def _capture_human(report: dict) -> str:
    buf = io.StringIO()
    from claude_usage_cli import _print_human
    with patch("builtins.print", lambda *a, **k: buf.write(" ".join(str(x) for x in a) + "\n")):
        _print_human(report)
    return buf.getvalue()


def test_print_human_contains_bars():
    out = _capture_human(_minimal_report())
    assert "█" in out


def test_print_human_contains_sections():
    out = _capture_human(_minimal_report())
    for section in ("Live Context", "Today", "5-Hour Window", "Week", "Models", "Daily"):
        assert section in out


def test_print_human_today_marker():
    r = _minimal_report()
    r["daily"] = [
        {"date": "2026-06-26", "tokens": 1000, "messages": 5, "sessions": 1, "today": False},
        {"date": "2026-06-27", "tokens": 5000, "messages": 10, "sessions": 2, "today": True},
    ]
    out = _capture_human(r)
    assert "← today" in out


def test_print_human_compact_soon_warning():
    r = _minimal_report(live_context=[
        {"project": "big", "model": "Sonnet", "pct": 89.0, "used": 178_000, "limit": 200_000, "compact_soon": True}
    ])
    out = _capture_human(r)
    assert "compact soon" in out


def test_print_human_no_live_context():
    out = _capture_human(_minimal_report(live_context=[]))
    assert "no active sessions" in out
