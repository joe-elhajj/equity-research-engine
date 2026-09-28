"""Public, derived-score-only release of an explicitly built reference cohort.

Never uploads. The operator publishes the exported JSON as the
``universe-ranks.json`` asset on the dedicated ``equity-ranks`` GitHub release.
The reader is read-only, bounded, and rejects mismatched scoring assumptions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests

from engine import universe_ranks as U
from engine.config import load_config

API = "https://api.github.com/repos/joe-elhajj/equity-research-engine/releases/tags/equity-ranks"
ASSET = "universe-ranks.json"
DOWNLOADED = Path(".cache/universe/published-ranks.json")
CHECK_SECONDS = 6 * 3600
MAX_BYTES = 512 * 1024
# These sections affect scoring. Local SEC contact, cache, web, paid-model,
# and operational settings deliberately do not affect compatibility.
SCORE_SECTIONS = ("universe", "classification", "valuation", "durability", "peers", "report")
_checked_at = float("-inf")


def score_fingerprint(cfg: dict) -> str:
    relevant = {k: cfg.get(k) for k in SCORE_SECTIONS}
    # universe.file is a machine-local path; the file's bytes are already
    # checked separately by file_hash. Paths must not invalidate a clone.
    relevant["universe"] = {k: v for k, v in (cfg.get("universe") or {}).items() if k != "file"}
    relevant["report"] = {"history_years": (cfg.get("report") or {}).get("history_years", 15)}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, default=str).encode()).hexdigest()


def export(cfg: dict, output: Path, cache: Path = U.CACHE) -> dict:
    """Export from a complete, current local build; never trigger a rebuild."""
    if output.resolve() in (cache.resolve(), Path(cfg.get("universe", {}).get("file", "config/sp500_universe.txt")).resolve()):
        raise ValueError("Export must not overwrite source data")
    data = U.load(cfg, cache)
    if data is None:
        raise ValueError("No validated, complete local reference build to export")
    payload = {
        "schema": 2, "source_schema": U.SCHEMA_VERSION, "version": data["key"]["version"],
        "file_hash": data["key"]["file_hash"],
        "scoring_hash": score_fingerprint(cfg), "built_at": data["built_at"],
        "started_at": data["started_at"], "expires_at": data["expires_at"],
        "total": data["total"], "scored": data["scored"],
        "rows": {ticker: ({f: row[f] for f in (*U.FIELDS, "completeness")} if row else {})
                 for ticker, row in data["rows"].items()},
        "scores": {f: list(data["scores"][f]) for f in U.FIELDS},
        "peer_counts": {f: len(data["scores"][f]) for f in U.FIELDS},
    }
    # No quote, market cap, price, shares, company name, SEC contact, or
    # config dump travels in the release. Check the exact serialized shape.
    validated = validate(cfg, payload)
    if validated is None:
        raise ValueError("Release payload failed validation")
    U._atomic_json(output, payload)
    return payload


def validate(cfg: dict, payload: dict) -> dict | None:
    """Allowlisted public format, then the SAME hardened local-cache validator."""
    try:
        if type(payload) is not dict or set(payload) != {
            "schema", "source_schema", "version", "file_hash", "scoring_hash",
            "built_at", "started_at", "expires_at", "total", "scored", "rows", "scores", "peer_counts",
        } or type(payload["schema"]) is not int or payload["schema"] != 2:
            return None
        if type(payload["source_schema"]) is not int or payload["source_schema"] != U.SCHEMA_VERSION:
            return None
        expected = U.key(cfg)
        if (payload["version"] != expected["version"] or payload["file_hash"] != expected["file_hash"]
                or payload["scoring_hash"] != score_fingerprint(cfg)):
            return None
        rows = payload["rows"]
        if type(rows) is not dict or type(payload["peer_counts"]) is not dict or set(payload["peer_counts"]) != set(U.FIELDS):
            return None
        if any(type(r) is not dict or (r and set(r) != set(U.FIELDS) | {"completeness"}) for r in rows.values()):
            return None
        # Names and exclusion narratives are private-local extras, not eligibility
        # evidence. Completeness is a derived score and must travel with each row;
        # never invent .80 eligibility when importing a prototype release.
        data = {"key": expected, "status": "complete", "built_at": payload["built_at"],
                "started_at": payload["started_at"], "expires_at": payload["expires_at"],
                "total": payload["total"], "processed": payload["total"], "scored": payload["scored"],
                "rows": {t: {**r, "name": None} if r else {} for t, r in rows.items()},
                "scores": payload["scores"],
                "exclusions": {t: "Not eligible in published reference" for t, r in rows.items() if not r}}
        if not U._valid(data, cfg):
            return None
        if any(type(payload["peer_counts"][f]) is not int or payload["peer_counts"][f] != len(data["scores"][f]) for f in U.FIELDS):
            return None
        return data
    except (OSError, KeyError, ValueError, TypeError, OverflowError, AttributeError):
        return None


def _get_json_bounded(session: requests.Session, url: str, *, asset: bool = False) -> dict:
    allowed = ({"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
               if asset else {"api.github.com"})
    deadline = time.monotonic() + 15
    for _ in range(5):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("Unexpected release URL or redirect")
        with session.get(url, timeout=(2, 4), stream=True, allow_redirects=False,
                         headers={"Accept": "application/json"}) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers["Location"])
                continue
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > MAX_BYTES or time.monotonic() > deadline:
                    raise ValueError("Release response exceeds size/time limit")
            return json.loads(data)
    raise ValueError("Too many release redirects")


def refresh(cfg: dict, cache: Path = DOWNLOADED, session: requests.Session | None = None) -> dict | None:
    """Fetch latest dedicated release metadata, but only a named JSON asset."""
    owned = session is None
    session = session or requests.Session()
    try:
        release = _get_json_bounded(session, API)
        if (type(release) is not dict or type(release.get("assets")) is not list
            or len(release["assets"]) > 100 or release.get("tag_name") != "equity-ranks"
            or release.get("draft") is True or release.get("prerelease") is True):
            return None
        matches = [a for a in release["assets"] if type(a) is dict
                   and a.get("name") == ASSET and a.get("state") == "uploaded"]
        if (len(matches) != 1 or type(matches[0].get("size")) is not int
            or not 0 < matches[0]["size"] <= MAX_BYTES):
            return None
        url = matches[0]["browser_download_url"]
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname != "github.com"
            or parsed.path != "/joe-elhajj/equity-research-engine/releases/download/equity-ranks/" + ASSET):
            return None
        payload = _get_json_bounded(session, url, asset=True)
        data = validate(cfg, payload)
        if data is None:
            return None
        try:
            previous = validate(cfg, json.loads(cache.read_text())) if cache.stat().st_size <= MAX_BYTES else None
        except (OSError, ValueError):
            previous = None
        if previous and (U._date(previous["started_at"]), U._date(previous["built_at"])) >= (U._date(data["started_at"]), U._date(data["built_at"])):
            return previous
        U._atomic_json(cache, payload)
        return data
    except (requests.RequestException, OSError, ValueError, KeyError, TypeError, OverflowError):
        return None
    finally:
        if owned:
            session.close()


def load_reference(cfg: dict, *, local: Path = U.CACHE,
                   downloaded: Path = DOWNLOADED, session: requests.Session | None = None) -> dict | None:
    """Validated local and published cohorts; newest compatible build wins.

    Never interrupts an explicit build. Network checks happen only when
    neither local nor downloaded data validates, at most once per process
    per six hours. Failure leaves a valid local build intact.
    """
    global _checked_at
    local_data = U.load(cfg, local)
    try:
        public_data = validate(cfg, json.loads(downloaded.read_text())) if downloaded.stat().st_size <= MAX_BYTES else None
    except (OSError, ValueError, TypeError):
        public_data = None
    now = time.monotonic()
    # A valid local build is already usable offline. A previously downloaded
    # public build can be selected if newer, without any network request.
    if not local_data and public_data is None and now - _checked_at >= CHECK_SECONDS:
        _checked_at = now
        fetched = refresh(cfg, downloaded, session)
        if fetched is not None:
            public_data = fetched
    if local_data and public_data:
        return max((local_data, public_data), key=lambda d: (U._date(d["started_at"]), U._date(d["built_at"])))
    return local_data or public_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Export validated, derived-only reference ranks")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output", default="/tmp/universe-ranks.json")
    parser.add_argument("--download", action="store_true", help="Explicitly check/download a compatible published release; never upload")
    args = parser.parse_args()
    if args.download:
        result = refresh(load_config(Path(args.config)))
        if result is None:
            raise SystemExit("No compatible release downloaded; existing local data preserved")
        print(f"Validated published reference: {result['scored']}/{result['total']}")
        return
    result = export(load_config(Path(args.config)), Path(args.output))
    print(f"Exported {result['scored']}/{result['total']} derived scores to {args.output}; no upload performed")


if __name__ == "__main__":
    main()
