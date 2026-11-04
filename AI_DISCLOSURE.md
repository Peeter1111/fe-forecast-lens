# AI assistance disclosure

This project was built with AI assistance from ChatGPT worker chats and reviewed with Claude. AI was used to explore Fe 26.5 syntax, propose and implement code, generate tests and scripts, analyze public Kalshi data, and review documentation.

The automated work was checked by compiling and testing with Fe 26.5.0 and by independent Python arithmetic where noted in the repository. No AI-generated claim is intended to substitute for those reproducible checks.

## Human review before submission

The project lead should fill this section in before submission with the specific code, mathematics, data-selection rule, benchmark commands, and documentation personally checked by a human.

## Pre-existing work

An earlier internal Forecast Lens attempt began November 3, 2026, within the contest build window; its `w710-sequence-guard` revision was made November 4. This smaller project rewrote the contract around `ScoringRule`, a generic `Ledger`, mergeable summaries, packed five-bin storage, and a typed message interface. Its Brier error calculation, Newton integer square root, and Wilson interval arithmetic reuse code from that earlier attempt. The contest starter's CI and Apache-2.0 license were also reused. Fe's standard library is a dependency, not original code.
