#!/usr/bin/env python3
"""Independent exact-arithmetic oracle and merge-property check."""

from __future__ import annotations

import argparse
import json
import random
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
    body = json.dumps(payload(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text() != body:
            raise SystemExit("data/oracle.json is stale; run scripts/oracle.py")
        print("oracle fixture matches; 10,000 seeded partition/order cases passed")
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(body)
        print("wrote data/oracle.json; 10,000 seeded partition/order cases passed")


if __name__ == "__main__":
    main()
