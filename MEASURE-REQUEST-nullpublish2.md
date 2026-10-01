# nullpublish2 — landed-tree campaign re-freeze

Launch HEAD: `1a6e84455e594ce5ba177506f9f5f9d2157fd669` on `cx-nullrefresh`. `git fetch origin cpp` followed by `git merge --no-edit origin/cpp` reported already up to date at `90ba908d3aca61f2b1e79664e839a5b8093145a4`.

This commit records the rebuilt artifacts and instrument snapshot and will anchor the campaign source guards. The final report adds the exact committed anchor and complete campaign fence after this commit exists. No server, generator, campaign, benchmark, gate, or push has run.

Forced rebuild passed: `taskset -c 112-127 make -B -j16 build/tomokv build/tailgen`; log: `build/nullpublish2-rebuild.log`. Both targets were recompiled, not merely accepted as up to date. No warnings or errors. Server/build inputs are unchanged from launch.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `build/tomokv-nullpublish-POST` | 176965512 | `49e69e30d1d3d46f46f8e5f96dad17885511e905c98fba4a3d530814885cf1a7` |
| `build/tailgen-nullpublish-frozen` | 2911008 | `613a6a7e115ba522753a37015a2dbb799325e915030a9f8c3ae95c3a8f4a2d05` |
| `build/memtier-nullpublish-frozen` | 616272 | `9b6ee614dae154c64b17a067a10236b3e6532f7ca52c43b547b87101556dd7d4` |
| `build/nullpublish-POST.instrument.json` | 4575 | `409e9ebbb74775454708663b712339789f0ea55d84ab3da2dabe4343b3084b9d` |

Prior instrument SHA-256: `183bcb6585b545a2e0e168451c143e6098978024b3367353af9f02ac7cbfdf1c`.
Current instrument SHA-256: `ef5bb5a313f566a67f70b583708bc087da217c9ec5162a3974bb3483b61617dc`.

Only `tests/gate_receipt.py` and the new `tests/gate_ledger_fixture.py` change the instrument entries. ROOTS, scope and Python identity are unchanged. The old freeze, instrument, checksums, script and check summary are retained as `build/nullpublish2-prior-*`.

Fixture choice: retain the reviewed explicit fixture. A serverless source-declaration check compares the full multiset with `EXPECT_FULL`, reports missing/extra occurrences, and refuses once before receipt Controls setup. It reads `tests/gate.sh` declarations in Python and executes no shell or run ledger. All 463 labels agree; 10 focused controls passed with no skips. EXPECT_QUICK=446 and EXPECT_FULL=463 are untouched. The final serverless set and preflight will be recorded after completion.
