# Forecast Lens

**Pitch:** A small Fe library and contract that compress binary forecasts into mergeable, exact integer scoring and calibration summaries instead of storing every forecast on chain.

## The problem

Prediction systems often need an auditable answer to a simple question: were the probabilities calibrated? Keeping every forecast and outcome in contract storage is expensive, while off-chain summaries are hard to combine safely if each worker rounds its own results.

Forecast Lens keeps additive integer sufficient statistics. Independent shards can be merged in any order and produce the same final scores and reliability bins, with rounding deferred until a query.

## Approach

The project records binary probabilities on a 0–1,000,000 integer scale. It provides two proper scoring rules, compact reliability bins with Wilson intervals, and a contract that stores only the aggregate state needed for those calculations.

The repository also contains a reproducible replay of settled public Kalshi markets and a gas comparison against a deliberately naive contract that stores every event.

## Fe highlight

The core math is generic over a `ScoringRule` trait, while contract storage is exposed as an explicit mutable effect. That separation makes the scoring functions pure and the state mutation visible in handler signatures.

```fe
// Filled in with the final, compiler-checked excerpt before submission.
```

## Architecture

- `src/scoring.fe` — proper integer scoring rules and the generic mergeable ledger.
- `src/reliability.fe` — fixed reliability bins and integer Wilson intervals.
- `src/contract.fe` — one message-group contract interface and aggregate storage.
- `src/tests.fe` — readable unit and integration tests.
- `scripts/` — independent oracle, public-data replay, and benchmark helpers.
- `data/` — compact, regenerated fixtures and measured outputs.

## Build and test

```sh
/path/to/fe --version
/path/to/fe fmt --check
/path/to/fe test
/path/to/fe build
python3 scripts/oracle.py --check
```

The contest build uses Fe 26.5.0. The README will contain the exact replay and gas commands once those measurements are frozen.

## Demo

The reproducible demo will print the calibration table for the frozen public Kalshi sample and the storage/gas comparison from the checked-in fixture.

## Limitations

Fe 26.5 is not production-ready. Forecast Lens is an audit and aggregation example, not a trading system. A calibration sample describes only the selected settled markets and does not establish trading profitability or future forecast quality.

## Declaration

- **Pre-existing work:** None of the Forecast Lens implementation predates the November 3, 2026 contest window. The repository starts from the contest starter's CI shape and Apache-2.0 license, and uses Fe's standard library.
- **Third-party code:** No third-party application code is copied into this project.
- **AI assistance:** See `AI_DISCLOSURE.md`.

## Team

Peeter Tsanev.

## License

Apache-2.0. See `LICENSE`.
