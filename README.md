# Forecast Lens

**Pitch:** Exact, mergeable forecast calibration in Fe using eight storage words instead of storing every forecast.

**Headline:** 37,578 gas/record steady median versus 71,247 for a store-every-event control; 96 real Kalshi quotes are scored five minutes before close.

## The problem

Prediction systems need an auditable answer to “were these probabilities calibrated?” Raw on-chain history is expensive, while off-chain summaries can disagree if shards round before merging.

Forecast Lens stores additive integer sufficient statistics. Any partition or merge order produces the same result, and division happens only when a score is queried. One designated reporter may append events, and a rolling hash lets an observer compare the stored summary against a supplied event list.

## Approach

- Probabilities use an integer `0..1_000_000` scale.
- `ScoringRule` has exact Brier loss plus an exact strictly proper quartic loss, `4d³ - 3d⁴`.
- `Ledger<R: ScoringRule>` accumulates exact numerators; no floating point or per-shard rounding.
- Five reliability bins return count, mean quote, observed rate, and nominal-95% Wilson bounds.
- The contract persists Brier plus those five bins in **six packed `u256` words**, a fixed reporter in one word, and a rolling hash in one word: **eight storage words** total. Quartic stays in the pure library so it does not add another SSTORE per forecast.

For the quartic loss, the expected-loss derivative is `12p(1-p)(p-q)`, so the true probability `q` is the unique interior minimum with the correct boundary minima. The formula is exact on the fixed-point grid and needs no logarithm table or approximation.

The score word packs a 64-bit event count beside the Brier numerator; each bin word packs a 64-bit count, 64-bit positive count, and 128-bit probability sum. Those widths remain safe through `2^64 - 1` events. A record updates the score word, one bin word, and the hash word.

The deployment caller becomes the permanent reporter. A record contains a nonzero `event_id`, the probability, and the settled outcome. The rolling hash starts at zero and advances as `keccak256(abi.encode(previous_hash, event_id, probability_micro, outcome_bit))`, with four full 32-byte words. `audit()` returns the count and hash. Anyone with the ordered raw records can recompute the hash, Brier, and reliability table. The contract does **not** independently verify outcomes, chronology, or uniqueness of event IDs.

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

The contract exposes one typed message group: `Record`, `Scores`, `BinView`, and `Audit`.

## Real Kalshi replay

The fixture covers **all 96 settled `KXBTC15M` markets closing during November 1, 2026 UTC** (00:00 through 23:45). Selection requires a binary YES/NO result and positive volume. For each market, the probability is the **last public YES trade no later than five minutes before close**; the script queries Kalshi's trades endpoint with `max_ts = close_unix - 300` and checks the returned timestamp. No markets lacked such a trade: **96 eligible, 96 scored, zero skipped**. Prices and outcomes are not used to select markets.

| Five-minute-prior YES-price bin | n | Mean quote | Observed YES | Wilson 95% |
| --- | ---: | ---: | ---: | ---: |
| 0.0–0.2 | 29 | 0.076034 | 0.034483 | [0.006113, 0.171759] |
| 0.2–0.4 | 19 | 0.294737 | 0.368421 | [0.191492, 0.589609] |
| 0.4–0.6 | 3 | 0.476667 | 0.666667 | [0.207654, 0.938510] |
| 0.6–0.8 | 10 | 0.679000 | 0.700000 | [0.396773, 0.892211] |
| 0.8–1.0 | 35 | 0.922086 | 0.942857 | [0.813926, 0.984188] |

Overall Brier loss is **0.105328**. All five bins contain trades, although the center bin has only three. This is a small, single-day descriptive sample of *trade prices*, not calibrated probabilities issued by one independent forecaster. It does not establish Kalshi-wide forecast quality, a trading edge, or profitability.

The 96 quote/outcome pairs compress to 76 frequency rows. The fixture also preserves chronological event IDs (market-close Unix seconds) so the Fe test and independent Python audit can verify the rolling hash. The generated Fe fixture is 257 lines, including both representations.

## Gas result

`scripts/gas_bench.py` runs the compiled Fe bytecode with eth-tester 0.13.0b1 and PyEVM 0.12.1b1 / PragueVM, one transaction per forecast. The control stores each full event ID and probability/outcome in two `StorageMap` entries. The reporter and rolling hash are implemented on Forecast Lens, but not on the deliberately simple archival control, so this comparison measures different storage designs rather than functionally identical contracts.

| Metric | Forecast Lens | Store every event |
| --- | ---: | ---: |
| Deployment | 435,382 | 98,544 |
| First record | 88,781 | 88,309 |
| Median record, last 50/100 | **37,578** | 71,247 |
| Mean record, 100 | **38,780** | 71,417 |

Steady median recording gas is **47.3% lower** on this fixed 100-record pattern. Recording-only cumulative gas becomes cheaper at record **2**; including deployment, at record **14**. Both break-even counts depend on the input pattern and the local EVM configuration. The median uses the average of the two middle observations for the even-sized last-50 sample.

## Architecture

- `src/scoring.fe` — proper rules and generic mergeable ledger.
- `src/reliability.fe` — five bins and integer Wilson intervals.
- `src/summary.fe` — pure mergeable full summary.
- `src/board.fe` — eight-word reporter-controlled, hash-chained contract and message group.
- `src/tests.fe`, `src/kalshi_replay_tests.fe` — 10,000-case merge property plus 96-market contract replay.
- `bench/naive/`, `scripts/`, `data/` — gas control, independent Fraction oracle, public-data fetch/replay, and frozen outputs.

## Build and test

Built with **`fe 26.5.0 (3dab95f)`**.

```sh
fe --version
fe fmt --check && fe check && fe build && fe test
python3 scripts/oracle.py --check
python3 scripts/replay.py
python3 scripts/fetch_kalshi.py --check --raw-dir /tmp/forecast-lens-raw  # network
fe build bench/naive
uv run --script scripts/audit_demo.py
uv run --script scripts/gas_bench.py
```

The Fe suite runs 10,000 seeded merge-order cases. `scripts/oracle.py` independently uses Python `Fraction` arithmetic for another 10,000 randomized partition/order cases.

Python 3.11+ is enough for the oracle, replay, and fetch scripts. The two EVM scripts use `uv` to install their declared PyEVM dependencies in an isolated environment. The fetch script saves raw API responses and checksums to the chosen external directory, not the repository.

## Demo

The shortest reproducible demo uses the checked-in public-data fixture:

```sh
python3 scripts/replay.py
```

It prints the 96-market calibration table and two fixed-point scores. `uv run --script scripts/audit_demo.py` replays those markets through the contract and independently checks every bin and the hash; changing a raw outcome makes the hash comparison fail. `uv run --script scripts/gas_bench.py` reproduces the gas table from fresh Fe bytecode.

## Limitations

- The public sample is one day from one high-frequency Kalshi series and only three quotes fall in the middle bin. Kalshi trade prices are not independent forecast submissions.
- The reporter is trusted to supply outcomes and distinct event IDs; the hash detects disagreement with a supplied ordered list, not false input or an omitted event.
- Wilson bounds use fixed bins and nominal z=1.96; they do not correct for dependence or multiple testing.
- Gas is a local PragueVM measurement and can differ on another EVM fork or chain.
- The raw-storage control has no reporter or hash, and the break-even counts depend on the fixed transaction pattern.
- The on-chain contract persists Brier only; Quartic is intentionally library-only.
- Fe 26.5 is evolving software; this is a compact demonstration, not audited production infrastructure.

## Declaration

- **Earlier work and reuse:** An internal Forecast Lens attempt started November 3, 2026, within the build window; its `w710-sequence-guard` revision was made November 4. This project started from that mathematics and reused its Brier error block, Newton integer square root, and Wilson calculations. The contract was rewritten using a scoring trait, generic ledger, mergeable summaries, compact five-bin storage, and typed messages. The starter CI structure and Apache license were also reused. Commit `7f0a4d6` starts this smaller repository's history.
- **Third-party code:** No third-party application code is copied. The benchmark declares `eth-tester`, `py-evm`, and `eth-utils`; the replay reads Kalshi’s anonymous public REST API.
- **AI assistance:** ChatGPT worker chats assisted with research, implementation, tests, data analysis, and documentation; Claude review was also used. See `AI_DISCLOSURE.md` for the human-review note.

## Team

Peeter Tsanev.

## License

Apache-2.0. See `LICENSE`.
