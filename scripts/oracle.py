#!/usr/bin/env python3
"""Independent exact-arithmetic oracle and merge-property check."""

from __future__ import annotations

import argparse
import collections
import json
import random
from decimal import Decimal, getcontext
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "oracle.json"
SCALE = 1_000_000


def brier(p: Fraction, y: int) -> Fraction:
    return (p - y) ** 2


def quartic(p: Fraction, y: int) -> Fraction:
    d = abs(p - y)
    return 4 * d**3 - 3 * d**4


def half_up_micro(value: Fraction) -> int:
    scaled = value * SCALE
    return (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)


def summarize(events: list[tuple[int, int]]) -> dict:
    bins = [[0, 0, 0] for _ in range(5)]
    brier_total = Fraction(0)
    quartic_total = Fraction(0)
    for probability, outcome in events:
        p = Fraction(probability, SCALE)
        brier_total += brier(p, outcome)
        quartic_total += quartic(p, outcome)
        index = min(4, probability // 200_000)
        bins[index][0] += 1
        bins[index][1] += probability
        bins[index][2] += outcome
    n = len(events)
    return {
        "count": n,
        "brier_micro": half_up_micro(brier_total / n) if n else 0,
        "quartic_micro": half_up_micro(quartic_total / n) if n else 0,
        "brier_fraction": [brier_total.numerator, brier_total.denominator],
        "quartic_fraction": [quartic_total.numerator, quartic_total.denominator],
        "bins": bins,
    }


def merge(parts: list[dict]) -> dict:
    count = sum(p["count"] for p in parts)
    brier_total = sum((Fraction(*p["brier_fraction"]) for p in parts), Fraction(0))
    quartic_total = sum((Fraction(*p["quartic_fraction"]) for p in parts), Fraction(0))
    bins = [[0, 0, 0] for _ in range(5)]
    for part in parts:
        for i, values in enumerate(part["bins"]):
            for j in range(3):
                bins[i][j] += values[j]
    return {
        "count": count,
        "brier_micro": half_up_micro(brier_total / count) if count else 0,
        "quartic_micro": half_up_micro(quartic_total / count) if count else 0,
        "brier_fraction": [brier_total.numerator, brier_total.denominator],
        "quartic_fraction": [quartic_total.numerator, quartic_total.denominator],
        "bins": bins,
    }


def property_check(cases: int = 10_000) -> None:
    rng = random.Random(20261104)
    for case in range(cases):
        n = rng.randint(1, 24)
        events = [(rng.randrange(SCALE + 1), rng.randrange(2)) for _ in range(n)]
        direct = summarize(events)

        shard_count = rng.randint(1, min(7, n))
        shards = [[] for _ in range(shard_count)]
        for event in events:
            shards[rng.randrange(shard_count)].append(event)
        pieces = [summarize(shard) for shard in shards]
        rng.shuffle(pieces)
        reduced = merge(pieces)
        if reduced != direct:
            raise AssertionError(f"merge mismatch in seeded case {case}")


def check_public_fixture() -> int:
    fixture = json.loads((ROOT / "data" / "kalshi_btc15m.json").read_text())
    reported = json.loads((ROOT / "data" / "calibration.json").read_text())
    stride = 2 * (SCALE + 1)
    event_ids = [value // stride for value in fixture["events"]]
    codes = [value % stride for value in fixture["events"]]
    if len(event_ids) != len(set(event_ids)) or event_ids != sorted(event_ids):
        raise AssertionError("event identities are repeated or not chronological")
    if sorted(collections.Counter(codes).items()) != [tuple(row) for row in fixture["frequencies"]]:
        raise AssertionError("frequency rows disagree with chronological events")
    events = [(code // 2, code % 2) for code in codes]
    result = summarize(events)
    if not events or len(events) != fixture["count"] or len(events) != reported["count"]:
        raise AssertionError("market count mismatch")
    for field in ("brier_micro", "quartic_micro"):
        if result[field] != reported[field]:
            raise AssertionError(f"independent {field} mismatch")
    if Fraction(*result["brier_fraction"]) * SCALE**2 != reported["brier_sum"]:
        raise AssertionError("raw Brier numerator mismatch")
    if Fraction(*result["quartic_fraction"]) * SCALE**4 != reported["quartic_sum"]:
        raise AssertionError("raw quartic numerator mismatch")

    getcontext().prec = 60
    z = Decimal("1.96")
    for index, (n, psum, positives) in enumerate(result["bins"]):
        row = reported["bins"][index]
        expected = {
            "count": n,
            "positives": positives,
            "probability_sum": psum,
            "mean_quote_micro": (2 * psum + n) // (2 * n) if n else 0,
            "yes_rate_micro": (2 * positives * SCALE + n) // (2 * n) if n else 0,
        }
        for field, value in expected.items():
            if row[field] != value:
                raise AssertionError(f"bin {index} {field} mismatch")
        if n:
            phat = Decimal(positives) / n
            d = 1 + z**2 / n
            c = (phat + z**2 / (2 * n)) / d
            radius = z * (phat * (1 - phat) / n + z**2 / (4 * n**2)).sqrt() / d
            for field, value in (
                ("wilson_lower_micro", max(Decimal(0), c - radius)),
                ("wilson_upper_micro", min(Decimal(1), c + radius)),
            ):
                if abs(Decimal(row[field]) - value * SCALE) > 2:
                    raise AssertionError(f"bin {index} {field} mismatch")
    return len(events)


def payload() -> dict:
    vectors = [
        [(500_000, 1)],
        [(1_000_000, 1), (0, 0)],
        [(100_000, 1), (100_000, 0)],
        [(250_000, 1), (750_000, 0), (500_000, 1)],
    ]
    return {
        "scale": SCALE,
        "seed": 20261104,
        "property_cases": 10_000,
        "vectors": [{"events": events, "summary": summarize(events)} for events in vectors],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    property_check()
    public_count = check_public_fixture()
    body = json.dumps(payload(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text() != body:
            raise SystemExit("data/oracle.json is stale; run scripts/oracle.py")
        print(f"oracle fixture matches; 10,000 merge cases and {public_count} Kalshi quotes verified")
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(body)
        print(f"wrote data/oracle.json; 10,000 merge cases and {public_count} Kalshi quotes verified")


if __name__ == "__main__":
    main()
