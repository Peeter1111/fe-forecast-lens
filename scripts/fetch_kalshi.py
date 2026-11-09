#!/usr/bin/env python3
"""Freeze one full day of KXBTC15M forecasts from five minutes before close.

Every eligible settled market in the fixed UTC window is considered, without
filtering by quoted probability or its result. The last YES trade at or before
close minus five minutes is used. Markets without that trade are counted and
excluded. Anonymous public API responses are saved outside the source tree.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "kalshi_btc15m.json"
FE_FIXTURE = ROOT / "src" / "kalshi_fixture.fe"
BASE = "https://api.elections.kalshi.com/trade-api/v2"
UA = "forecast-lens-fe-contest/2026-11-04"
SERIES = "KXBTC15M"
START = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
END = dt.datetime(2026, 11, 2, tzinfo=dt.timezone.utc)
SCALE = 1_000_000
LEAD_SECONDS = 300
EVENT_STRIDE = (SCALE + 1) * 2
_last_request_started: float | None = None


def get_bytes(url: str, cache_dir: Path) -> bytes:
    global _last_request_started
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    if cached.exists():
        return cached.read_bytes()
    last: Exception | None = None
    for attempt in range(5):
        try:
            if _last_request_started is not None:
                time.sleep(max(0.0, 1.0 - (time.monotonic() - _last_request_started)))
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            _last_request_started = time.monotonic()
            with urllib.request.urlopen(request, timeout=40) as response:
                body = response.read()
            cached.write_bytes(body)
            return body
        except Exception as exc:  # retry only network/public-API failures
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                raise SystemExit("Kalshi throttled the fetch; stopped without retrying") from exc
            last = exc
            if attempt == 4:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(last)


def paged_markets(raw_dir: Path) -> tuple[list[dict], list[dict]]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    cursor = None
    rows: list[dict] = []
    manifest: list[dict] = []
    page = 0
    while True:
        params = {
            "series_ticker": SERIES,
            "status": "settled",
            "limit": 1000,
            "min_close_ts": int(START.timestamp()),
            "max_close_ts": int(END.timestamp()),
        }
        if cursor:
            params["cursor"] = cursor
        url = BASE + "/markets?" + urllib.parse.urlencode(params)
        body = get_bytes(url, raw_dir / ".http-cache")
        path = raw_dir / f"markets-{page:02d}.json"
        path.write_bytes(body)
        manifest.append(
            {
                "path": path.name,
                "url": url,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
        payload = json.loads(body)
        batch = payload.get("markets", [])
        rows.extend(batch)
        cursor = payload.get("cursor")
        page += 1
        if not cursor or not batch:
            break
    return rows, manifest


def select(rows: list[dict]) -> list[dict]:
    selected = []
    for market in rows:
        if market.get("market_type") != "binary":
            continue
        if market.get("result") not in {"yes", "no"}:
            continue
        if Decimal(str(market.get("volume_fp", "0"))) <= 0:
            continue
        close = dt.datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
        if not START <= close < END:
            continue
        selected.append(
            {
                "ticker": market["ticker"],
                "close_time": market["close_time"],
                "event_id": int(close.timestamp()),
                "outcome": 1 if market["result"] == "yes" else 0,
            }
        )
    selected.sort(key=lambda row: (row["close_time"], row["ticker"]))
    if len({row["event_id"] for row in selected}) != len(selected):
        raise ValueError("close timestamps are not unique in this one-series sample")
    return selected


def preclose_quotes(rows: list[dict], raw_dir: Path) -> tuple[list[dict], dict, list[dict]]:
    selected = []
    skipped = collections.Counter()
    manifest = []
    trade_dir = raw_dir / "trades"
    trade_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        cutoff = row["event_id"] - LEAD_SECONDS
        url = BASE + "/markets/trades?" + urllib.parse.urlencode(
            {"ticker": row["ticker"], "limit": 1, "max_ts": cutoff}
        )
        body = get_bytes(url, raw_dir / ".http-cache")
        path = trade_dir / (row["ticker"] + ".json")
        path.write_bytes(body)
        manifest.append(
            {"path": "trades/" + path.name, "url": url, "sha256": hashlib.sha256(body).hexdigest()}
        )
        trades = json.loads(body).get("trades", [])
        if not trades:
            skipped["no_trade_before_cutoff"] += 1
            continue
        trade = trades[0]
        trade_time = dt.datetime.fromisoformat(trade["created_time"].replace("Z", "+00:00"))
        if trade_time.timestamp() > cutoff:
            raise ValueError(f"API returned trade after cutoff: {row['ticker']}")
        price = Decimal(str(trade["yes_price_dollars"]))
        micro = int(price * SCALE)
        if not Decimal(0) <= price <= Decimal(1) or Decimal(micro) / SCALE != price:
            skipped["invalid_quote"] += 1
            continue
        selected.append({**row, "probability_micro": micro, "trade_time": trade["created_time"]})
    return selected, dict(skipped), manifest


def build_fixture(rows: list[dict], eligible: int, skipped: dict, manifest: list[dict]) -> dict:
    encoded = [row["probability_micro"] * 2 + row["outcome"] for row in rows]
    frequencies = sorted(collections.Counter(encoded).items())
    events = [row["event_id"] * EVENT_STRIDE + code for row, code in zip(rows, encoded)]
    canonical_rows = "\n".join(
        f"{row['ticker']}|{row['event_id']}|{row['trade_time']}|{row['probability_micro']}|{row['outcome']}"
        for row in rows
    ).encode()
    return {
        "source": BASE,
        "series": SERIES,
        "window": {"min_close_inclusive": START.isoformat(), "max_close_exclusive": END.isoformat()},
        "selection": "settled binary YES/NO positive-volume markets; last YES trade at least 300 seconds before close",
        "eligible": eligible,
        "skipped": skipped,
        "lead_seconds": LEAD_SECONDS,
        "count": len(rows),
        "first_close": rows[0]["close_time"],
        "last_close": rows[-1]["close_time"],
        "raw_responses": len(manifest),
        "selection_sha256": hashlib.sha256(canonical_rows).hexdigest(),
        "encoding": "[encoded_event,count], encoded_event = probability_micro * 2 + outcome_yes_bit",
        "event_encoding": "close_unix_seconds * 2000002 + encoded_event; sorted chronologically",
        "frequencies": frequencies,
        "events": events,
    }


def fe_fixture(fixture: dict) -> str:
    frequencies = fixture["frequencies"]
    codes = "\n".join(f"    {code}," for code, _ in frequencies)
    events = "\n".join(f"    {code}," for code in fixture["events"])
    counts = "\n".join(f"    {count}," for _, count in frequencies)
    return (
        "// Generated by scripts/fetch_kalshi.py. Do not edit by hand.\n"
        f"pub const KALSHI_EVENT_COUNT: u256 = {fixture['count']}\n"
        f"pub const KALSHI_UNIQUE_COUNT: usize = {len(frequencies)}\n"
        f"pub const KALSHI_CODES: [u256; {len(frequencies)}] = [\n{codes}\n]\n"
        f"pub const KALSHI_COUNTS: [u256; {len(frequencies)}] = [\n{counts}\n]\n"
        f"pub const KALSHI_EVENTS: [u256; {fixture['count']}] = [\n{events}\n]\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--raw-dir", type=Path, default=Path(tempfile.gettempdir()) / "forecast-lens-raw"
    )
    args = parser.parse_args()

    rows, manifest = paged_markets(args.raw_dir)
    selected = select(rows)
    quoted, skipped, trade_manifest = preclose_quotes(selected, args.raw_dir)
    if not quoted:
        raise SystemExit("no preclose trades in fixed window")
    fixture = build_fixture(quoted, len(selected), skipped, manifest + trade_manifest)
    body = json.dumps(fixture, separators=(",", ":"), sort_keys=True) + "\n"
    fe_body = fe_fixture(fixture)
    (args.raw_dir / "manifest.json").write_text(
        json.dumps(manifest + trade_manifest, indent=2) + "\n"
    )

    if args.check:
        if not FIXTURE.exists() or FIXTURE.read_text() != body:
            raise SystemExit("data/kalshi_btc15m.json is stale")
        if not FE_FIXTURE.exists() or FE_FIXTURE.read_text() != fe_body:
            raise SystemExit("src/kalshi_fixture.fe is stale")
        print(f"fixture matches: {len(quoted)}/{len(selected)} markets, skipped {skipped}")
    else:
        FIXTURE.write_text(body)
        FE_FIXTURE.write_text(fe_body)
        print(f"wrote {len(quoted)}/{len(selected)} preclose quotes; skipped {skipped}")


if __name__ == "__main__":
    main()
