#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["eth-tester==0.13.0b1", "py-evm==0.12.1b1", "eth-hash[pycryptodome]==0.7.1", "eth-utils==5.3.0"]
# ///
"""Measure transaction gas for Forecast Lens versus raw-event storage.

This runs both Fe bytecodes in the same in-memory PyEVM chain and sends one
transaction per forecast. It reports deployment gas, per-record gas, cumulative
recording gas, and the first event count at which Forecast Lens' cumulative
recording gas is lower than the naive store-every-event control.
"""

from __future__ import annotations

import json
import hashlib
import importlib.metadata
from pathlib import Path

from eth_tester import EthereumTester
from eth_utils import keccak

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "gas.json"
AGG_BIN = ROOT / "out" / "ForecastLens.bin"
NAIVE_BIN = ROOT / "bench" / "naive" / "out" / "NaiveArchive.bin"


def deploy(tester: EthereumTester, sender: str, path: Path) -> tuple[str, int]:
    bytecode = path.read_text().strip()
    tx = tester.send_transaction(
        {"from": sender, "gas": 15_000_000, "data": "0x" + bytecode}
    )
    receipt = tester.get_transaction_receipt(tx)
    if receipt["status"] != 1:
        raise RuntimeError(f"deployment failed for {path}")
    return receipt["contract_address"], receipt["gas_used"]


def calldata(probability: int, outcome: int) -> str:
    selector = keccak(text="record(uint256,bool)")[:4]
    body = probability.to_bytes(32, "big") + outcome.to_bytes(32, "big")
    return "0x" + (selector + body).hex()


def send_record(tester: EthereumTester, sender: str, address: str, probability: int, outcome: int) -> int:
    tx = tester.send_transaction(
        {
            "from": sender,
            "to": address,
            "gas": 3_000_000,
            "data": calldata(probability, outcome),
        }
    )
    receipt = tester.get_transaction_receipt(tx)
    if receipt["status"] != 1:
        raise RuntimeError("record transaction failed")
    return receipt["gas_used"]


def main() -> None:
    if not AGG_BIN.exists() or not NAIVE_BIN.exists():
        raise SystemExit("build both Fe contracts before running the gas benchmark")

    tester = EthereumTester()
    sender = tester.get_accounts()[0]
    aggregate, aggregate_deploy = deploy(tester, sender, AGG_BIN)
    naive, naive_deploy = deploy(tester, sender, NAIVE_BIN)

    # Fixed 100-record mix hits every reliability bin and both outcomes.
    pattern = [
        (50_000, 0),
        (250_000, 0),
        (450_000, 1),
        (650_000, 1),
        (850_000, 1),
        (950_000, 0),
        (100_000, 1),
        (350_000, 1),
        (550_000, 0),
        (750_000, 0),
    ]
    aggregate_gas: list[int] = []
    naive_gas: list[int] = []
    cumulative_aggregate = 0
    cumulative_naive = 0
    break_even = None
    break_even_totals = None
    for i in range(100):
        probability, outcome = pattern[i % len(pattern)]
        a = send_record(tester, sender, aggregate, probability, outcome)
        n = send_record(tester, sender, naive, probability, outcome)
        aggregate_gas.append(a)
        naive_gas.append(n)
        cumulative_aggregate += a
        cumulative_naive += n
        if break_even is None and cumulative_aggregate <= cumulative_naive:
            break_even = i + 1
            break_even_totals = {
                "aggregate": cumulative_aggregate,
                "naive": cumulative_naive,
            }

    lifecycle_break_even = None
    lifecycle_totals = None
    for i in range(100):
        aggregate_lifecycle = aggregate_deploy + sum(aggregate_gas[: i + 1])
        naive_lifecycle = naive_deploy + sum(naive_gas[: i + 1])
        if aggregate_lifecycle <= naive_lifecycle:
            lifecycle_break_even = i + 1
            lifecycle_totals = {
                "aggregate": aggregate_lifecycle,
                "naive": naive_lifecycle,
            }
            break

    result = {
        "engine": "eth-tester + PyEVM, one EVM transaction per forecast",
        "eth_tester_version": importlib.metadata.version("eth-tester"),
        "py_evm_version": importlib.metadata.version("py-evm"),
        "vm": tester.backend.chain.get_vm().__class__.__name__,
        "forecast_lens_bytecode_sha256": hashlib.sha256(bytes.fromhex(AGG_BIN.read_text().strip())).hexdigest(),
        "naive_bytecode_sha256": hashlib.sha256(bytes.fromhex(NAIVE_BIN.read_text().strip())).hexdigest(),
        "records": 100,
        "pattern": pattern,
        "aggregate": {
            "deploy_gas": aggregate_deploy,
            "first_record_gas": aggregate_gas[0],
            "steady_record_gas_median_last_50": sorted(aggregate_gas[-50:])[25],
            "record_gas_total_100": sum(aggregate_gas),
            "record_gas_mean_100": sum(aggregate_gas) / len(aggregate_gas),
        },
        "naive": {
            "deploy_gas": naive_deploy,
            "first_record_gas": naive_gas[0],
            "steady_record_gas_median_last_50": sorted(naive_gas[-50:])[25],
            "record_gas_total_100": sum(naive_gas),
            "record_gas_mean_100": sum(naive_gas) / len(naive_gas),
        },
        "recording_only_break_even_event": break_even,
        "recording_only_break_even_cumulative_gas": break_even_totals,
        "lifecycle_break_even_event": lifecycle_break_even,
        "lifecycle_break_even_cumulative_gas": lifecycle_totals,
        "steady_median_reduction_fraction": 1
        - sorted(aggregate_gas[-50:])[25] / sorted(naive_gas[-50:])[25],
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
