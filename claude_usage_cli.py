#!/usr/bin/env python3
"""Claude Code usage stats — CLI/text output, no GUI needed."""

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
STATS_CACHE = CLAUDE_DIR / "stats-cache.json"
PROJECTS_DIR = CLAUDE_DIR / "projects"
RATE_LIMITS_CACHE = CLAUDE_DIR / "rate-limits-cache.json"

LIVE_WINDOW_MIN = 30
THROTTLE_ESTIMATE = 1_500_000
WEEK_ESTIMATE = 7_500_000

# Claude Code auto-compacts before the full context window is consumed.
# Observed: compaction fires around 90% of the model's stated limit.
COMPACT_WARN_PCT = 80

MODEL_CONTEXT_LIMIT: dict[str, int] = {
    "claude-opus-4-8": 1_000_000,
    "claude-opus-4-7": 1_000_000,
}
_DEFAULT_CONTEXT_LIMIT = 200_000

MODEL_SHORT = {
    "claude-sonnet-4-6": "Sonnet",
    "claude-opus-4-7": "Opus",
    "claude-opus-4-8": "Opus",
    "claude-haiku-4-5-20251001": "Haiku",
    "claude-haiku-4-5": "Haiku",
}


def _infer_plan(ceiling_5h: int) -> str:
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
    if not RATE_LIMITS_CACHE.exists():
        return {}
    try:
        return json.loads(RATE_LIMITS_CACHE.read_text())
    except Exception:
        return {}


def collect_5h_window() -> int:
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


def collect_live_contexts() -> list[dict]:
    cutoff = time.time() - LIVE_WINDOW_MIN * 60
    results = []
    try:
        for jsonl_file in PROJECTS_DIR.glob("*/*.jsonl"):
            try:
                if jsonl_file.stat().st_mtime < cutoff:
                    continue
                with open(jsonl_file, "rb") as fh:
                    head = fh.read(4096).decode("utf-8", errors="replace")
                    fh.seek(0, 2)
                    file_size = fh.tell()
                    fh.seek(max(4096, file_size - 256 * 1024))
                    tail = fh.read().decode("utf-8", errors="replace")
                text = head + "\n" + tail
                last_usage_entry: dict | None = None
                cwd = ""
                for raw in text.splitlines():
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not cwd and obj.get("cwd"):
                        cwd = obj["cwd"]
                    if obj.get("type") != "assistant":
                        continue
                    if "input_tokens" in obj.get("message", {}).get("usage", {}):
                        last_usage_entry = obj
                if last_usage_entry is None:
                    continue
                usage = last_usage_entry["message"]["usage"]
                used = (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                )
                if not cwd and last_usage_entry.get("cwd"):
                    cwd = last_usage_entry["cwd"]
                raw_model = last_usage_entry.get("message", {}).get("model", "")
                if raw_model == "<synthetic>":
                    continue
                model = MODEL_SHORT.get(raw_model, raw_model.split("-")[1] if "-" in raw_model else raw_model)
                project = os.path.basename(cwd) if cwd else jsonl_file.parts[-2]
                limit = MODEL_CONTEXT_LIMIT.get(raw_model, _DEFAULT_CONTEXT_LIMIT)
                pct = used / limit * 100
                results.append({
                    "project": project, "model": model,
                    "used": used, "limit": limit, "pct": pct,
                    "compact_soon": pct >= COMPACT_WARN_PCT,
                })
            except Exception:
                continue
    except Exception:
        return []
    results.sort(key=lambda x: -x["pct"])
    return results[:6]


def collect_usage() -> dict:
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

    cache_cutoff = ""
    if STATS_CACHE.exists():
        try:
            cache = json.loads(STATS_CACHE.read_text())
            cache_cutoff = cache.get("lastComputedDate", "")
            for day in cache.get("dailyActivity", []):
                d = day["date"]
                daily[d]["messages"] += day.get("messageCount", 0)
                daily[d]["tools"] += day.get("toolCallCount", 0)
                daily[d]["sessions_count"] = daily[d].get("sessions_count", 0) + day.get("sessionCount", 0)
            for day in cache.get("dailyModelTokens", []):
                d = day["date"]
                for model, toks in day.get("tokensByModel", {}).items():
                    daily[d]["models"][MODEL_SHORT.get(model, model)] += toks
        except Exception:
            pass

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

    result = {}
    for d, v in daily.items():
        sc = len(v["sessions"]) if v["sessions"] else v.get("sessions_count", 0)
        real_tokens = v["input"] + v["output"]
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


def _bar(ratio: float, width: int = 20) -> str:
    filled = max(0, min(width, int(ratio * width)))
    return "█" * filled + "░" * (width - filled)


def _build_report(daily: dict, win_tokens: int, live_ctxs: list[dict], rl: dict) -> dict:
    """Assemble all stats into a plain dict (used by both text and JSON output)."""
    today = datetime.now().strftime("%Y-%m-%d")
    days_7 = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

    td = daily.get(today, {})
    today_stats = {
        "date": today,
        "messages": td.get("messages", 0),
        "tokens": td.get("tokens", 0),
        "sessions": td.get("sessions", 0),
    }

    fh = rl.get("five_hour", {})
    if fh and "used_percentage" in fh:
        fh_pct = fh["used_percentage"]
        reset_ts = fh.get("resets_at")
        implied = int(win_tokens / (fh_pct / 100)) if fh_pct > 0 and win_tokens > 0 else None
        window_5h = {
            "pct": round(fh_pct, 1),
            "used": win_tokens,
            "limit": implied,
            "plan": _infer_plan(implied) if implied else None,
            "resets_at": datetime.fromtimestamp(reset_ts).strftime("%H:%M") if reset_ts else None,
            "estimated": False,
        }
    else:
        ratio = min(1.0, win_tokens / THROTTLE_ESTIMATE)
        window_5h = {
            "pct": round(ratio * 100, 1),
            "used": win_tokens,
            "limit": THROTTLE_ESTIMATE,
            "plan": None,
            "resets_at": None,
            "estimated": True,
        }

    w_msgs = w_tokens = w_sessions = 0
    week_models: dict[str, int] = defaultdict(int)
    daily_rows = []
    for d in days_7:
        v = daily.get(d, {})
        toks = v.get("tokens", 0)
        msgs = v.get("messages", 0)
        sess = v.get("sessions", 0)
        w_msgs += msgs
        w_tokens += toks
        w_sessions += sess
        daily_rows.append(
            {"date": d, "tokens": toks, "messages": msgs, "sessions": sess, "today": d == today}
        )
        for model, t in v.get("models", {}).items():
            week_models[model] += t

    sd = rl.get("seven_day", {})
    if sd and "used_percentage" in sd:
        sd_pct = sd["used_percentage"]
        reset_ts = sd.get("resets_at")
        implied_w = int(w_tokens / (sd_pct / 100)) if sd_pct > 0 and w_tokens > 0 else None
        week_stats = {
            "pct": round(sd_pct, 1),
            "used": w_tokens,
            "limit": implied_w,
            "messages": w_msgs,
            "sessions": w_sessions,
            "resets_at": datetime.fromtimestamp(reset_ts).strftime("%a %H:%M") if reset_ts else None,
            "estimated": False,
        }
    else:
        ratio = min(1.0, w_tokens / WEEK_ESTIMATE)
        week_stats = {
            "pct": round(ratio * 100, 1),
            "used": w_tokens,
            "limit": WEEK_ESTIMATE,
            "messages": w_msgs,
            "sessions": w_sessions,
            "resets_at": None,
            "estimated": True,
        }

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "live_context": [
            {
                "project": c["project"],
                "model": c["model"],
                "pct": round(c["pct"], 1),
                "used": c["used"],
                "limit": c["limit"],
                "compact_soon": c["compact_soon"],
            }
            for c in live_ctxs
        ],
        "today": today_stats,
        "window_5h": window_5h,
        "week_7d": week_stats,
        "models_7d": {m: t for m, t in sorted(week_models.items(), key=lambda x: -x[1])},
        "daily": daily_rows,
    }


def _print_human(r: dict) -> None:
    print(f"Claude Usage  {r['generated_at']}")

    print()
    print("Live Context")
    if r["live_context"]:
        for c in r["live_context"]:
            bar = _bar(c["pct"] / 100)
            warn = "  ⚠ compact soon" if c["compact_soon"] else ""
            used_str = f"{fmt_tokens(c['used'])}/{fmt_tokens(c['limit'])}"
            print(f"  {c['project']} · {c['model']}  [{bar}] {c['pct']:3.0f}%  {used_str}{warn}")
    else:
        print("  no active sessions")

    print()
    t = r["today"]
    print(f"Today  {t['date']}")
    print(f"  Messages  {t['messages']}")
    print(f"  Tokens    {fmt_tokens(t['tokens'])}")
    print(f"  Sessions  {t['sessions']}")

    print()
    w = r["window_5h"]
    est = " (estimated)" if w["estimated"] else ""
    bar = _bar(w["pct"] / 100)
    limit_str = fmt_tokens(w["limit"]) if w["limit"] else "?"
    extras = "  ·  ".join(filter(None, [
        f"plan ~{w['plan']}" if w["plan"] else None,
        f"resets {w['resets_at']}" if w["resets_at"] else None,
    ]))
    print(f"5-Hour Window{est}")
    suffix = f"  ·  {extras}" if extras else ""
    print(f"  [{bar}] {w['pct']:3.0f}%   {fmt_tokens(w['used'])} / {limit_str}{suffix}")

    print()
    wk = r["week_7d"]
    est = " (estimated)" if wk["estimated"] else ""
    bar = _bar(wk["pct"] / 100)
    limit_str = fmt_tokens(wk["limit"]) if wk["limit"] else "?"
    reset_str = f"  ·  resets {wk['resets_at']}" if wk["resets_at"] else ""
    print(f"Week (7 days){est}")
    print(f"  [{bar}] {wk['pct']:3.0f}%   {fmt_tokens(wk['used'])} / {limit_str}{reset_str}")
    print(f"  Messages {wk['messages']}  ·  Sessions {wk['sessions']}")

    print()
    print("Models (7-day tokens)")
    if r["models_7d"]:
        max_toks = max(r["models_7d"].values())
        for model, toks in r["models_7d"].items():
            bar = _bar(toks / max_toks, width=16)
            print(f"  {model:<10}  [{bar}]  {fmt_tokens(toks):>6}")
    else:
        print("  no data")

    print()
    print("Daily (last 7 days)")
    max_toks = max((d["tokens"] for d in r["daily"]), default=1) or 1
    for d in r["daily"]:
        bar = _bar(d["tokens"] / max_toks, width=16)
        today_mark = "  ← today" if d["today"] else ""
        print(f"  {d['date']}  [{bar}]  {fmt_tokens(d['tokens']):>6}  {d['messages']:4d} msgs{today_mark}")


def _print_text(r: dict) -> None:
    def kv(*pairs) -> str:
        return "  " + "  ".join(f"{k}={v}" for k, v in pairs if v is not None)

    print(f"CLAUDE USAGE  {r['generated_at']}")

    print()
    print("LIVE CONTEXT")
    if r["live_context"]:
        for c in r["live_context"]:
            warn = "  compact_soon=true" if c["compact_soon"] else ""
            line = (
                f"  project={c['project']}  model={c['model']}  pct={c['pct']:.0f}"
                f"  used={fmt_tokens(c['used'])}  limit={fmt_tokens(c['limit'])}{warn}"
            )
            print(line)
    else:
        print("  none")

    print()
    t = r["today"]
    print(f"TODAY  date={t['date']}")
    print(kv(
        ("messages", t["messages"]), ("tokens", fmt_tokens(t["tokens"])),
        ("tokens_raw", t["tokens"]), ("sessions", t["sessions"]),
    ))

    print()
    w = r["window_5h"]
    est = "  estimated=true" if w["estimated"] else ""
    print(f"WINDOW_5H{est}")
    print(kv(
        ("pct", f"{w['pct']:.0f}"),
        ("used", fmt_tokens(w["used"])),
        ("used_raw", w["used"]),
        ("limit", fmt_tokens(w["limit"]) if w["limit"] else None),
        ("plan", w["plan"]),
        ("resets_at", w["resets_at"]),
    ))

    print()
    wk = r["week_7d"]
    est = "  estimated=true" if wk["estimated"] else ""
    print(f"WEEK_7D{est}")
    print(kv(
        ("pct", f"{wk['pct']:.0f}"),
        ("used", fmt_tokens(wk["used"])),
        ("used_raw", wk["used"]),
        ("limit", fmt_tokens(wk["limit"]) if wk["limit"] else None),
        ("resets_at", wk["resets_at"]),
    ))
    print(kv(("messages", wk["messages"]), ("sessions", wk["sessions"])))

    print()
    print("MODELS_7D")
    for model, toks in r["models_7d"].items():
        print(f"  model={model}  tokens={fmt_tokens(toks)}  tokens_raw={toks}")

    print()
    print("DAILY")
    for d in r["daily"]:
        today_mark = "  today=true" if d["today"] else ""
        print(
            f"  date={d['date']}  tokens={fmt_tokens(d['tokens'])}  tokens_raw={d['tokens']}"
            f"  messages={d['messages']}  sessions={d['sessions']}{today_mark}"
        )


def main() -> None:
    import sys
    args = sys.argv[1:]
    use_json = "--json" in args
    use_text = "--text" in args  # LLM-friendly key=value; default is human

    daily = collect_usage()
    win_tokens = collect_5h_window()
    live_ctxs = collect_live_contexts()
    rl = load_rate_limits()

    report = _build_report(daily, win_tokens, live_ctxs, rl)

    if use_json:
        print(json.dumps(report, indent=2))
    elif use_text:
        _print_text(report)
    else:
        _print_human(report)


if __name__ == "__main__":
    main()
