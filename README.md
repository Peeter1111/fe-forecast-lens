# Forecast Lens

**Pitch:** Exact, mergeable forecast calibration in Fe using six storage words instead of storing every forecast.

**Headline:** 32,259 gas/record steady median versus 48,935 for a store-every-event control; real-data replay covers 6,113 settled Kalshi markets.

## The problem

Prediction systems need an auditable answer to “were these probabilities calibrated?” Raw on-chain history is expensive, while off-chain summaries can disagree if shards round before merging.

Forecast Lens stores additive integer sufficient statistics. Any partition or merge order produces the same result, and division happens only when a score is queried.

## Approach

- Probabilities use an integer `0..1_000_000` scale.
- `ScoringRule` has exact Brier loss plus an exact strictly proper quartic loss, `4d³ - 3d⁴`.
- `Ledger<R: ScoringRule>` accumulates exact numerators; no floating point or per-shard rounding.
- Five reliability bins return count, mean quote, observed rate, and nominal-95% Wilson bounds.
- The contract persists Brier plus those five bins in **six packed `u256` words**. Quartic stays in the pure library so it does not add another SSTORE per forecast.

For the quartic loss, the expected-loss derivative is `12p(1-p)(p-q)`, so the true probability `q` is the unique interior minimum with the correct boundary minima. The formula is exact on the fixed-point grid and needs no logarithm table or approximation.

The score word packs a 64-bit event count beside the Brier numerator; each bin word packs a 64-bit count, 64-bit positive count, and 128-bit probability sum. Those widths remain safe through `2^64 - 1` events and make the persistent update touch only the score word and one bin word.

## Fe highlight

Pure generic math and persistent mutation are visibly separated by Fe’s type/effect system:

```fe
pub trait ScoringRule: Copy {
    fn denominator() -> u256
    fn loss_numerator(_ probability: u256, _ outcome: bool) -> u256
}

pub struct Ledger<R: ScoringRule> { rule: R, count: u256, loss_sum: u256 }

fn record_store(_ probability: u256, _ outcome: bool) -> u256
uses (store: mut ForecastStore)
```

The contract exposes one typed message group: `Record`, `Scores`, and `BinView`.

## Real Kalshi replay

The fixture is **6,113 settled `KXBTC15M` markets** closing from 2026-09-01 00:00 UTC through 2026-11-04 10:00 UTC. Selection requires a YES/NO result, positive volume, and an interior final YES trade price. A deterministic 24-market public trade-tape check matched Kalshi’s settled `last_price_dollars` in all 24 cases.

| Final YES-price bin | n | Mean final quote | Observed YES | Wilson 95% |
| --- | ---: | ---: | ---: | ---: |
| 0.0–0.2 | 3,082 | 0.001016 | 0.000000 | [0.000000, 0.001245] |
| 0.2–0.4 | 0 | — | — | — |
| 0.4–0.6 | 0 | — | — | — |
| 0.6–0.8 | 0 | — | — | — |
| 0.8–1.0 | 3,031 | 0.998990 | 1.000000 | [0.998734, 1.000000] |

Overall Brier loss is `0.000001`. The result is deliberately narrow: these are **terminal prices**, so the near-perfect extremes are a sanity check, not evidence of advance forecasting skill or trading profit.

The exact 6,113 price/outcome pairs compress to 11 frequency rows; the Fe test expands them and sends every record through the contract.

## Gas result

`scripts/gas_bench.py` runs the compiled Fe bytecode with eth-tester 0.13.0b1 and PyEVM 0.12.1b1 / PragueVM, one transaction per forecast. The control stores every raw event in a `StorageMap`.

| Metric | Forecast Lens | Store every event |
| --- | ---: | ---: |
| Deployment | 350,251 | 93,136 |
| First record | 66,366 | 65,971 |
| Median record, last 50/100 | **32,259** | 48,935 |
| Mean record, 100 | **33,288** | 49,079 |

Steady median recording gas is **34.1% lower**. Recording-only cumulative gas becomes cheaper at record **6**; including deployment, lifecycle gas becomes cheaper at record **21**.

## Architecture

- `src/scoring.fe` — proper rules and generic mergeable ledger.
- `src/reliability.fe` — five bins and integer Wilson intervals.
- `src/summary.fe` — pure mergeable full summary.
- `src/board.fe` — six-word packed contract state and message group.
- `src/tests.fe`, `src/kalshi_replay_tests.fe` — 10,000-case merge property plus 6,113-market contract replay.
- `bench/naive/`, `scripts/`, `data/` — gas control, independent Fraction oracle, public-data fetch/replay, and frozen outputs.

## Build and test

Built with **`fe 26.5.0 (3dab95f)`**.

```sh
fe --version
fe fmt --check && fe test && fe build
python3 scripts/oracle.py --check
python3 scripts/replay.py
python3 scripts/fetch_kalshi.py --check --raw-dir .cache/kalshi  # network
fe build bench/naive
uv run --script scripts/gas_bench.py
```

The Fe suite runs 10,000 seeded merge-order cases. `scripts/oracle.py` independently uses Python `Fraction` arithmetic for another 10,000 randomized partition/order cases.

Python 3.11+ is enough for the oracle, replay, and fetch scripts. The gas benchmark uses `uv` to install its declared PyEVM dependencies in an isolated environment.

## Demo

The shortest reproducible demo uses the checked-in public-data fixture:

```sh
python3 scripts/replay.py
```

It prints the 6,113-market calibration table and the two exact integer scores. `uv run --script scripts/gas_bench.py` then reproduces the aggregate-versus-raw-storage gas table from the freshly built Fe bytecode.

## Limitations

- The real sample is one high-frequency Kalshi series and final trades leave all middle calibration bins empty.
- Wilson bounds use fixed bins and nominal z=1.96; they do not correct for dependence or multiple testing.
- Gas is a local PragueVM measurement and can differ on another EVM fork or chain.
- The on-chain contract persists Brier only; Quartic is intentionally library-only.
- Fe 26.5 is evolving software; this is a compact demonstration, not audited production infrastructure.

## Declaration

- **Pre-existing work:** None of the Forecast Lens implementation predates November 3, 2026. Commit `7f0a4d6` is the clean baseline. Only the contest starter CI/license shape and Fe standard library were reused.
- **Third-party code:** No third-party application code is copied. The benchmark declares `eth-tester`, `py-evm`, and `eth-utils`; the replay reads Kalshi’s anonymous public REST API.
- **AI assistance:** ChatGPT worker chats assisted with research, implementation, tests, data analysis, and documentation; Claude review was also used. See `AI_DISCLOSURE.md` for the human-review note.

## Team

Peeter Tsanev.

## License

Apache-2.0. See `LICENSE`.
