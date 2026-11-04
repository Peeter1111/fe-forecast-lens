#!/usr/bin/env python3
"""Fetch and freeze the Forecast Lens real-market calibration sample.

Selection is deliberately narrow and reproducible: settled KXBTC15M binary
markets closing from 2026-09-01 00:00 UTC through 2026-11-04 10:00 UTC,
with a YES/NO result, positive traded volume, and an interior final trade
price. Kalshi's settled-market `last_price_dollars` is used as the final trade
before close. A deterministic trade-tape spot check verifies that interpretation.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import time
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "kalshi_btc15m.json"
FE_FIXTURE = ROOT / "src" / "kalshi_fixture.fe"
BASE = "https://api.elections.kalshi.com/trade-api/v2"
UA = "forecast-lens-fe-contest/2026-11-04"
SERIES = "KXBTC15M"
START = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
END = dt.datetime(2026, 11, 4, 10, tzinfo=dt.timezone.utc)
SCALE = 1_000_000


def get_bytes(url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(request, timeout=40) as response:
                return response.read()
        except Exception as exc:  # retry only network/public-API failures
            last = exc
            if attempt == 4:
                raise
            time.sleep(0.4 * (attempt + 1))
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
        body = get_bytes(url)
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
        price = Decimal(str(market.get("last_price_dollars", "0")))
        if not Decimal(0) < price < Decimal(1):
            continue
        micro = int(price * SCALE)
        if Decimal(micro) / SCALE != price:
            raise ValueError(f"price not exact at 1e-6 scale: {market['ticker']} {price}")
        selected.append(
            {
                "ticker": market["ticker"],
                "close_time": market["close_time"],
                "probability_micro": micro,
                "outcome": 1 if market["result"] == "yes" else 0,
            }
        )
    selected.sort(key=lambda row: (row["close_time"], row["ticker"]))
    return selected


def spotcheck_trades(rows: list[dict], raw_dir: Path, count: int = 24) -> dict:
    if len(rows) < count:
        indices = list(range(len(rows)))
    else:
        indices = [round(i * (len(rows) - 1) / (count - 1)) for i in range(count)]
    matches = 0
    checked = []
    trade_dir = raw_dir / "trade-checks"
    trade_dir.mkdir(parents=True, exist_ok=True)
    for index in indices:
        row = rows[index]
        url = BASE + "/markets/trades?" + urllib.parse.urlencode(
            {"ticker": row["ticker"], "limit": 1}
        )
        body = get_bytes(url)
        (trade_dir / f"{index:05d}.json").write_bytes(body)
        trades = json.loads(body).get("trades", [])
        ok = False
        trade_time = None
        if trades:
            trade = trades[0]
            micro = int(Decimal(trade["yes_price_dollars"]) * SCALE)
            trade_time = trade.get("created_time")
            ok = micro == row["probability_micro"] and trade_time <= row["close_time"]
        matches += int(ok)
        checked.append(
            {"index": index, "ticker": row["ticker"], "trade_time": trade_time, "match": ok}
        )
    return {"sample_count": len(indices), "matches": matches, "checks": checked}


def build_fixture(rows: list[dict], manifest: list[dict], spotcheck: dict) -> dict:
    encoded = [row["probability_micro"] * 2 + row["outcome"] for row in rows]
    frequencies = sorted(collections.Counter(encoded).items())
    canonical_rows = "\n".join(
        f"{row['ticker']}|{row['close_time']}|{row['probability_micro']}|{row['outcome']}"
        for row in rows
    ).encode()
    return {
        "source": BASE + "/markets",
        "series": SERIES,
        "window": {"min_close": START.isoformat(), "max_close": END.isoformat()},
        "selection": (
            "settled binary markets; result yes/no; positive volume; 0 < last_price_dollars < 1; "
            "probability is exact final YES last_price_dollars on the 1e6 scale"
        ),
        "count": len(rows),
        "first_close": rows[0]["close_time"],
        "last_close": rows[-1]["close_time"],
        "source_pages": len(manifest),
        "selection_sha256": hashlib.sha256(canonical_rows).hexdigest(),
        "last_trade_spotcheck": {
            "sample_count": spotcheck["sample_count"],
            "matches": spotcheck["matches"],
        },
        "encoding": "[encoded_event,count], encoded_event = probability_micro * 2 + outcome_yes_bit",
        "frequencies": frequencies,
    }


def fe_fixture(fixture: dict) -> str:
    frequencies = fixture["frequencies"]
    codes = "\n".join(f"    {code}," for code, _ in frequencies)
    counts = ", ".join(str(count) for _, count in frequencies)
    return (
        "// Generated by scripts/fetch_kalshi.py. Do not edit by hand.\n"
        f"pub const KALSHI_EVENT_COUNT: u256 = {fixture['count']}\n"
        f"pub const KALSHI_UNIQUE_COUNT: usize = {len(frequencies)}\n"
        f"pub const KALSHI_CODES: [u256; {len(frequencies)}] = [\n{codes}\n]\n"
        f"pub const KALSHI_COUNTS: [u256; {len(frequencies)}] = [{counts}]\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / ".cache" / "kalshi")
    args = parser.parse_args()

    rows, manifest = paged_markets(args.raw_dir)
    selected = select(rows)
    if len(selected) < 5_000:
        raise SystemExit(f"selection has only {len(selected)} markets; need >= 5000")
    spotcheck = spotcheck_trades(selected, args.raw_dir)
    if spotcheck["matches"] != spotcheck["sample_count"]:
        raise SystemExit("market last_price disagrees with latest-trade spot check")
    fixture = build_fixture(selected, manifest, spotcheck)
    body = json.dumps(fixture, separators=(",", ":"), sort_keys=True) + "\n"
    fe_body = fe_fixture(fixture)
    (args.raw_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (args.raw_dir / "spotcheck.json").write_text(json.dumps(spotcheck, indent=2) + "\n")

    if args.check:
        if not FIXTURE.exists() or FIXTURE.read_text() != body:
            raise SystemExit("data/kalshi_btc15m.json is stale")
        if not FE_FIXTURE.exists() or FE_FIXTURE.read_text() != fe_body:
            raise SystemExit("src/kalshi_fixture.fe is stale")
        print(f"fixture matches: {len(selected)} markets; {spotcheck['matches']}/{spotcheck['sample_count']} trade checks")
    else:
        FIXTURE.write_text(body)
        FE_FIXTURE.write_text(fe_body)
        print(f"wrote {len(selected)} markets; {spotcheck['matches']}/{spotcheck['sample_count']} latest-trade checks matched")


if __name__ == "__main__":
    main()
