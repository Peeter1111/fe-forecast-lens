#!/usr/bin/env python3
"""Replay the frozen Kalshi fixture and print its calibration table."""

from __future__ import annotations

import json
from math import isqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "kalshi_btc15m.json"
OUTPUT = ROOT / "data" / "calibration.json"
SCALE = 1_000_000


def wilson(positives: int, count: int, upper: bool) -> int:
    if count == 0:
        return SCALE if upper else 0
    q, z2 = 10_000, 38_416
    variance = 4 * positives * (count - positives) * q
    radicand = z2 * (z2 * count + variance) * SCALE * SCALE // count
    radius = isqrt(radicand) + 1
    center = (2 * positives * q + z2) * SCALE
    denominator = 2 * (count * q + z2)
    if upper:
        return min(SCALE, (center + radius + denominator - 1) // denominator)
    if center <= radius:
        return 0
    return (center - radius) // denominator


def half_up(numerator: int, denominator: int) -> int:
    return (numerator + denominator // 2) // denominator


def replay() -> dict:
    fixture = json.loads(FIXTURE.read_text())
    bins = [[0, 0, 0] for _ in range(5)]
    brier_sum = 0
    quartic_sum = 0
    for encoded, frequency in fixture["frequencies"]:
        outcome = encoded & 1
        probability = encoded // 2
        error = abs(probability - (SCALE if outcome else 0))
        brier_sum += frequency * error * error
        quartic_sum += frequency * error**3 * (4 * SCALE - 3 * error)
        index = min(4, probability // 200_000)
        bins[index][0] += frequency
        bins[index][1] += frequency * probability
        bins[index][2] += frequency * outcome

    count = fixture["count"]
    table = []
    for index, (n, probability_sum, positives) in enumerate(bins):
        table.append(
            {
                "bin": index,
                "range": [index * 200_000, SCALE if index == 4 else (index + 1) * 200_000],
                "count": n,
                "mean_quote_micro": half_up(probability_sum, n) if n else 0,
                "yes_rate_micro": half_up(positives * SCALE, n) if n else 0,
                "wilson_lower_micro": wilson(positives, n, False),
                "wilson_upper_micro": wilson(positives, n, True),
                "positives": positives,
                "probability_sum": probability_sum,
            }
        )
    return {
        "source_fixture": FIXTURE.name,
        "count": count,
        "brier_micro": half_up(brier_sum, count * SCALE),
        "quartic_micro": half_up(quartic_sum, count * SCALE**3),
        "brier_sum": brier_sum,
        "quartic_sum": quartic_sum,
        "bins": table,
    }


def main() -> None:
    result = replay()
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
    print(f"markets: {result['count']}")
    print(f"Brier: {result['brier_micro'] / SCALE:.6f}  Quartic: {result['quartic_micro'] / SCALE:.6f}")
    print("bin       n    mean quote   yes rate    Wilson 95%")
    for row in result["bins"]:
        lo = row["range"][0] / SCALE
        hi = row["range"][1] / SCALE
        print(
            f"{lo:.1f}-{hi:.1f}  {row['count']:5d}  "
            f"{row['mean_quote_micro']/SCALE:10.3f}  {row['yes_rate_micro']/SCALE:8.3f}  "
            f"[{row['wilson_lower_micro']/SCALE:.3f}, {row['wilson_upper_micro']/SCALE:.3f}]"
        )


if __name__ == "__main__":
    main()
