"""Explicit, offline-first S&P reference-score build and read-only ranking.

No LLM code is imported or called. Building is an operator command, never a
side effect of a dashboard read, screen refresh, or individual analysis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone, timedelta
from pathlib import Path

from engine.config import load_config
from engine.edgar import EdgarClient
from engine.screen import _process_one
from engine.universe import load_tickers
from engine.reference_transport import ReferencePaused, yahoo_budget, retry_seconds

FIELDS = ("composite", "cat_reinvestment", "cat_quality", "cat_resilience", "cat_discipline", "cat_optionality")
CACHE = Path(".cache/universe/aggregate_ranks.json")
MIN_PEERS = 100
MAX_AGE_DAYS = 90
SCHEMA_VERSION = 2


def fingerprint(cfg: dict) -> str:
    # Whole-config fingerprint: a valuation or classification change can affect
    # scoring eligibility even when the durability-only hash is unchanged.
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16]


def reference(cfg: dict) -> tuple[list[str], str]:
    path = Path(cfg.get("universe", {}).get("file", "config/sp500_universe.txt"))
    raw = path.read_bytes()
    names = [t.upper() for t in load_tickers(path)]
    if len(names) != len(set(names)) or not names:
        raise ValueError("Reference ticker list empty or contains duplicates")
    return names, hashlib.sha256(raw).hexdigest()


def key(cfg: dict) -> dict:
    _, file_hash = reference(cfg)
    return {"schema": SCHEMA_VERSION, "version": cfg.get("universe", {}).get("version"), "config_hash": fingerprint(cfg), "file_hash": file_hash}


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, sort_keys=True))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _number(value, low=0, high=100):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def eligible(row):
    return (row is not None and _number(row.composite)
            and _number(row.completeness, .8, 1)
            and all(getattr(row, f) is None or _number(getattr(row, f)) for f in FIELDS))


def _valid_item(item):
    if not isinstance(item, dict):
        return False
    if not item:
        return True
    return (set(item) == set(FIELDS) | {"name", "completeness"}
            and (item["name"] is None or isinstance(item["name"], str))
            and _number(item["completeness"], .8, 1)
            and _number(item["composite"])
            and all(item[f] is None or _number(item[f]) for f in FIELDS))


def _date(value):
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    return date


def _valid(data, cfg):
    if not isinstance(data, dict) or data.get("key") != key(cfg) or data.get("status") != "complete":
        return False
    now = datetime.now(timezone.utc)
    started, built = _date(data["started_at"]), _date(data["built_at"])
    expires = _date(data["expires_at"])
    if not started <= built <= now < expires or expires != started + timedelta(days=MAX_AGE_DAYS):
        return False
    names, _ = reference(cfg)
    if any(type(data[k]) is not int for k in ("total", "processed", "scored")):
        return False
    if data["total"] != len(names) or data["processed"] != len(names):
        return False
    rows = data["rows"]
    if not isinstance(rows, dict) or set(rows) != set(names) or not all(_valid_item(v) for v in rows.values()):
        return False
    if data["scored"] != sum(bool(v) for v in rows.values()) or data["scored"] < max(MIN_PEERS, .60 * len(names)):
        return False
    exclusions = data["exclusions"]
    if not isinstance(exclusions, dict) or set(exclusions) != {t for t, v in rows.items() if not v}:
        return False
    if not all(isinstance(v, str) and v for v in exclusions.values()):
        return False
    if not isinstance(data["scores"], dict) or set(data["scores"]) != set(FIELDS):
        return False
    for field in FIELDS:
        series = data["scores"][field]
        if not isinstance(series, list) or len(series) < MIN_PEERS or not all(_number(x) for x in series):
            return False
        if series != sorted(item[field] for item in rows.values() if item and item[field] is not None):
            return False
    return True


def load(cfg: dict, cache: Path = CACHE) -> dict | None:
    try:
        data = json.loads(cache.read_text())
        return data if _valid(data, cfg) else None
    except (OSError, ValueError, KeyError, TypeError, OverflowError, AttributeError):
        return None


def rank(value: float | None, field: str, data: dict | None) -> dict:
    if data is None or field not in FIELDS:
        return {"percentile": None, "peers": 0}
    values = data["scores"][field]
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value) or len(values) < MIN_PEERS:
        return {"percentile": None, "peers": len(values)}
    # Midrank for ties: avoids 0th percentile for all names in an identical
    # distribution; the target is compared with the reference cohort itself.
    left, right = bisect_left(values, value), bisect_right(values, value)
    return {"percentile": round(100 * (left + (right - left) / 2) / len(values), 1), "peers": len(values)}


def leaderboard(data: dict | None, field: str = "composite", limit: int = 25) -> dict | None:
    """Rank scored reference names only; returns no list without a valid cache."""
    if data is None or field not in FIELDS or not isinstance(limit, int) or not 1 <= limit <= 50:
        return None
    values = data["scores"][field]
    entries = [(ticker, row) for ticker, row in data["rows"].items()
               if field in row and row[field] is not None]
    entries.sort(key=lambda pair: (-pair[1][field], pair[0]))
    return {"field": field, "as_of": data["started_at"], "expires_at": data["expires_at"], "version": data["key"]["version"],
            "peers": len(values), "scored": data["scored"], "total": data["total"],
            "rows": [{"ticker": ticker, "name": row.get("name"), "score": row[field],
                      "percentile": rank(row[field], field, data)["percentile"]}
                     for ticker, row in entries[:limit]]}


def _build(cfg: dict, cache: Path = CACHE, *, progress=None) -> dict:
    names, _ = reference(cfg)
    wanted = key(cfg)
    progress_path = cache.with_name(cache.stem + ".progress.json")
    done: dict[str, dict] = {}
    exclusions: dict[str, str] = {}
    build_started_at = datetime.now(timezone.utc).isoformat()
    try:
        checkpoint = json.loads(progress_path.read_text())
        if checkpoint.get("key") == wanted and checkpoint.get("total") == len(names):
            # Resume only a recent checkpoint. A stale run cannot be silently
            # completed and stamped as fresh using old constituents' scores.
            started = _date(checkpoint["started_at"])
            if 0 <= (datetime.now(timezone.utc) - started).total_seconds() <= 7 * 86400:
                candidate = checkpoint["rows"]
                reasons = checkpoint["exclusions"]
                if (isinstance(candidate, dict) and set(candidate) <= set(names)
                        and all(_valid_item(v) for v in candidate.values())
                        and isinstance(reasons, dict)
                        and set(reasons) == {t for t, v in candidate.items() if not v}
                        and all(isinstance(v, str) and v for v in reasons.values())):
                    done, exclusions = candidate, reasons
                    build_started_at = checkpoint["started_at"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    sec = cfg.get("sec", {})
    client = EdgarClient(user_agent=sec.get("user_agent", ""),
                         request_delay=max(.25, sec.get("request_delay_seconds", .2)),
                         cache_dir=cfg.get("cache", {}).get("dir", ".cache/edgar"),
                         cache_ttl_seconds=int(cfg.get("cache", {}).get("ttl_seconds", 86400)))
    if hasattr(client, "session"):
        sec_request = client.session.request
        def guarded_sec_request(*args, **kwargs):
            response = sec_request(*args, **kwargs)
            if response.status_code in (403, 429):
                raise ReferencePaused(f"SEC HTTP {response.status_code}: access limited",
                                      max(900, retry_seconds(response.headers.get("Retry-After"))))
            return response
        client.session.request = guarded_sec_request
    _atomic_json(progress_path, {"key": wanted, "total": len(names), "processed": len(done), "started_at": build_started_at, "rows": done, "exclusions": exclusions})
    for index, ticker in enumerate(names, 1):
        if ticker not in done:
            reason = "unscorable"
            try:
                row, _fund = _process_one(ticker, client, cfg, cfg.get("report", {}).get("history_years", 15))
                reason = ("fund" if _fund is not None else
                          getattr(row, "flag", "") or "missing score or completeness below 80%")
            except Exception as exc:
                row = None
                reason = "error:" + type(exc).__name__
            if eligible(row):
                done[ticker] = {**{f: getattr(row, f) for f in FIELDS}, "name": row.name,
                                "completeness": row.completeness}
            else:
                done[ticker] = {}  # failures are visible in counts, not fictitious zeros
                exclusions[ticker] = reason
            _atomic_json(progress_path, {"key": wanted, "total": len(names), "processed": index, "started_at": build_started_at, "rows": done, "exclusions": exclusions})
        if progress:
            progress(index, len(names), ticker, sum(bool(v) for v in done.values()))
    scores = {f: sorted(v[f] for v in done.values() if f in v and v[f] is not None and math.isfinite(v[f])) for f in FIELDS}
    scored = sum(bool(v) for v in done.values())
    result = {"status": "complete", "key": wanted, "total": len(names), "processed": len(names),
              "scored": scored, "built_at": datetime.now(timezone.utc).isoformat(), "started_at": build_started_at,
              "expires_at": (_date(build_started_at) + timedelta(days=MAX_AGE_DAYS)).isoformat(),
              "scores": scores, "rows": done, "exclusions": exclusions}
    if scored < MIN_PEERS or scored < .60 * len(names) or any(len(v) < MIN_PEERS for v in scores.values()):
        raise ValueError(f"Reference coverage insufficient: {scored}/{len(names)} companies scored; progress retained")
    if not _valid(result, cfg):
        raise ValueError("Reference validation failed; progress retained")
    _atomic_json(cache, result)
    progress_path.unlink(missing_ok=True)
    return result


def build(cfg: dict, cache: Path = CACHE, *, progress=None) -> dict:
    retry_path = cache.with_name(cache.stem + ".retry.json")
    strikes = 0
    if retry_path.exists():
        retry = json.loads(retry_path.read_text())
        remaining = (_date(retry["retry_at"]) - datetime.now(timezone.utc)).total_seconds()
        strikes = retry.get("strikes", 0)
        if remaining > 0:
            raise ReferencePaused("Cooldown active until " + retry["retry_at"], remaining)
    try:
        with yahoo_budget() as budget:
            try:
                result = _build(cfg, cache, progress=progress)
            finally:
                print(f"Yahoo HTTP requests this run: {budget.requests} (minimum interval 1.05s)", flush=True)
    except ReferencePaused as exc:
        delay = max(exc.retry_after, min(86400, 900 * 2 ** min(strikes, 7)))
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        _atomic_json(retry_path, {"retry_at": retry_at.isoformat(), "strikes": strikes + 1, "reason": str(exc)})
        raise ReferencePaused(f"{exc}; checkpoint retained; retry after {retry_at.isoformat()}", delay) from None
    retry_path.unlink(missing_ok=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit S&P reference-score build (EDGAR + market quote only; no LLM)")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    cfg = load_config(Path(args.config))
    print("Reference build: Yahoo <= 1 request/1.05s; SEC <= 4 requests/s; paid calls disabled by route", flush=True)
    try:
        data = build(cfg, progress=lambda n, total, ticker, scored: print(f"{n}/{total} {ticker}: {scored} scored", flush=True))
    except ReferencePaused as exc:
        print(f"PAUSED: {exc}", flush=True)
        raise SystemExit(75)
    print(f"Ready: {data['scored']}/{data['total']} scored; {data['built_at']}")


if __name__ == "__main__":
    main()
