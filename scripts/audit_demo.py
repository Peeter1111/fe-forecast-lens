#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["eth-tester==0.13.0b1", "py-evm==0.12.1b1", "eth-hash[pycryptodome]==0.7.1", "eth-utils==5.3.0"]
# ///
"""Replay the public trades into Fe and independently verify the audit hash."""

from __future__ import annotations

import json
from pathlib import Path

from eth_tester import EthereumTester
from eth_utils import keccak

from gas_bench import AGG_BIN, calldata, deploy

ROOT = Path(__file__).resolve().parents[1]
SCALE = 1_000_000
STRIDE = 2 * (SCALE + 1)


def words(*values: int) -> bytes:
    return b"".join(value.to_bytes(32, "big") for value in values)


def call_view(tester: EthereumTester, sender: str, contract: str, signature: str, *args: int) -> list[int]:
    data = keccak(text=signature)[:4] + words(*args)
    answer = tester.call(
        {"from": sender, "to": contract, "gas": 1_000_000, "data": "0x" + data.hex()}
    )
    encoded = bytes.fromhex(answer.removeprefix("0x"))
    return [int.from_bytes(encoded[index : index + 32], "big") for index in range(0, len(encoded), 32)]


def main() -> None:
    fixture = json.loads((ROOT / "data" / "kalshi_btc15m.json").read_text())
    calibration = json.loads((ROOT / "data" / "calibration.json").read_text())
    tester = EthereumTester()
    owner, stranger = tester.get_accounts()[:2]
    address, _ = deploy(tester, owner, AGG_BIN)

    unauthorized = tester.send_transaction(
        {"from": stranger, "to": address, "gas": 3_000_000, "data": calldata(1, 500_000, 1)}
    )
    assert tester.get_transaction_receipt(unauthorized)["status"] == 0
    assert call_view(tester, owner, address, "audit()") == [0, 0]

    chain = 0
    changed_chain = 0
    for index, code in enumerate(fixture["events"]):
        event_id, encoded = divmod(code, STRIDE)
        probability, outcome = divmod(encoded, 2)
        transaction = tester.send_transaction(
            {
                "from": owner,
                "to": address,
                "gas": 3_000_000,
                "data": calldata(event_id, probability, outcome),
            }
        )
        if tester.get_transaction_receipt(transaction)["status"] != 1:
            raise AssertionError(f"valid event {index} rejected")
        chain = int.from_bytes(keccak(words(chain, event_id, probability, outcome)), "big")
        wrong_outcome = (1 - outcome) if index == 0 else outcome
        changed_chain = int.from_bytes(
            keccak(words(changed_chain, event_id, probability, wrong_outcome)), "big"
        )

    expected_count = fixture["count"]
    assert call_view(tester, owner, address, "audit()") == [expected_count, chain]
    assert changed_chain != chain, "corrupt raw event list should fail hash verification"
    assert call_view(tester, owner, address, "scores()") == [
        expected_count,
        calibration["brier_micro"],
    ]
    for index, row in enumerate(calibration["bins"]):
        expected = [
            row["count"],
            row["mean_quote_micro"],
            row["yes_rate_micro"],
            row["wilson_lower_micro"],
            row["wilson_upper_micro"],
        ]
        assert call_view(tester, owner, address, "bin(uint256)", index) == expected
    print(
        f"PASS: {expected_count} real trades, 5 bins, Brier {calibration['brier_micro']/SCALE:.6f}; "
        f"reporter denied, altered-list hash rejected; audit hash 0x{chain:064x}"
    )


if __name__ == "__main__":
    main()
