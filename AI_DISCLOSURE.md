# AI assistance disclosure

This project was built with AI assistance from ChatGPT worker chats and reviewed with Claude. AI was used to explore Fe 26.5 syntax, propose and implement code, generate tests and scripts, analyze public Kalshi data, and review documentation.

The automated work was checked by compiling and testing with Fe 26.5.0 and by independent Python arithmetic where noted in the repository. No AI-generated claim is intended to substitute for those reproducible checks.

## Review before submission

No human programmer reviewed this code. The entrant, Peeter Tsanev, is not a programmer. He chose to enter and approved publishing. AI agents did the design, the implementation and every review:

- ChatGPT worker chats wrote the implementation, tests, scripts and documentation.
- Claude wrote the project brief and read every file in `src/` on November 9, 2026.
- OpenAI Codex, in a separate session, built the earlier and the current revision on November 9, 2026, and wrote 4 regression checks. Each check fails on the earlier revision and passes on the current one.

## Pre-existing work

An earlier internal Forecast Lens attempt began November 3, 2026, within the contest build window; its `w710-sequence-guard` revision was made November 4. This smaller project rewrote the contract around `ScoringRule`, a generic `Ledger`, mergeable summaries, packed five-bin storage, and a typed message interface. Its Brier error calculation, Newton integer square root, and Wilson interval arithmetic reuse code from that earlier attempt. The contest starter's CI and Apache-2.0 license were also reused. Fe's standard library is a dependency, not original code.
