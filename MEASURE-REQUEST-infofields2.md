# infofields2: path 2; nested Lua feed requirement remains unfinished

**Do not treat this as a completed landable delivery.** The retained change takes
path **2** for refused-command visibility and preserves the ordinary-body proof.
It fixes INFO placement and MONITOR's six explicit script entry feeds. The 05:15
addendum also requires nested `lua` feeds; that implementation was tried, failed
the body audit, and was removed. The strict script witness demonstrates this
remaining gap. No new gate row is deliberately red, but that alone does not
complete the requested task.

The branch remains `cx-infofields`. The initial merge and permanent-seed repair
were committed together in `ee09a032d`; subsequent work is committed in small
steps. `origin/cpp` was fetched and merged again before the final proof; it was
already current at `65a9d0a2283010ea78a7c5af8d1f253905f82b9e`. That is the rebuilt
PRE merge-base. No push or full 517-row landing gate was run.

## Retained behavior and rejected attempts

The gated `monitor` generator compares a complete, independently expected stream
of 15 lines from 19 driven commands on each peer. It checks admin exclusions,
AUTH redaction, binary quoting, framing, checked source endpoint, and all six
EVAL/EVALSHA/FCALL entry commands. The driver omits the three refused ordinary
commands; it does not remove unexpected lines from a captured stream, accept a
tolerance, xfail, or skip. Its denied CONFIG command still tests admin exclusion.
Redis's six `skip_monitor` entries have explicit script-entry feeds, so excluding
those entries wholesale was incorrect.

The separate, non-gated strict witness retains all refusal assertions and prints
exact extra/missing lines before failing. The `--scripts` witness additionally
requires all six nested `lua` lines. Neither witness is in the gate's suite list.
[Deviation and exact rerun commands](docs/infofields/deviation-monitor-refused.md).

The first armed-only duplicate-verdict implementation introduced 53 unexplained
climon body changes (28 multi-DB, 25 db0). Its two changed *selected ordinary*
bodies were INFO-related db0 HELLO compiler changes, later fixed; those two are
not attributed to MONITOR. The next attempt isolated the predicate in the ACL TU
and tried a MONITOR-only script handler/IO bridge. It still changed unrelated
ACL, scripting and dispatch bodies. These trials were built and audited, not
retained as runtime code. See the [complete first trial](docs/infofields2/top-level-proof/summary.json),
[later audit](docs/infofields2/rejected-armed-body-audit.txt),
[script audit](docs/infofields2/rejected-script-body-audit.txt), and
[rejected implementation](docs/infofields2/rejected-armed-script.patch).
The predecessor's global reorder remains rejected: **55 / 1,584** selected hot
instances changed, including main/genthread/rl2s/reorder parse and dispatch.

INFO now places `number_of_cached_scripts`, `number_of_functions`, and
`number_of_libraries` in Memory, in that order and before maxmemory, matching the
oracle's relative order. They are absent from Stats. `tests/scriptsurf.py` requests
both Memory and Stats for its combined counter inventory. The differential checks
placement and the counters' relative order on both servers.

The db0 renderer stays in the cold INFO body; the multi-DB renderer uses the
existing cold `info_stats_memory_fields` helper. This compile-time distinction
preserves each namespace's ordinary inlining. There is no runtime knob, dispatch
reorder, struct growth, or ordinary operation store.

Redis 7.4.10 source inspection used
[server.c](https://raw.githubusercontent.com/redis/redis/7.4.10/src/server.c),
[script.c](https://raw.githubusercontent.com/redis/redis/7.4.10/src/script.c),
[eval.c](https://raw.githubusercontent.com/redis/redis/7.4.10/src/eval.c), and
[functions.c](https://raw.githubusercontent.com/redis/redis/7.4.10/src/functions.c).
Downloaded files are in `build/infofields2/redis-7.4.10`; their
[digests](docs/infofields2/redis-source-sha256.json) are retained.

## Rebuilt artifacts and unchanged proof tool

Both builds use GCC 13.3.0, the default optimized/debug flags, jemalloc, and both
namespaces. PRE was rebuilt from an archive of the merge-base:

```sh
taskset -c 112-127 make -C build/infofields2/PRE-source -j16 \
  BUILD_ROOT=/home/user/Projects/cx-infofields/build/infofields2/PRE
```

POST used `taskset -c 112-127 make -j16`; after the TU-local budget adjustment,
`make -j4 build/src/cmd/t_server.o build/db0/src/cmd/t_server.o
build/src/cmd/info_stats.o build/db0/src/cmd/info_stats.o` rebuilt the four edited
objects, then `taskset -c 112-127 make -o Makefile -j8` linked the final image.
`-o Makefile` avoids rebuilding unchanged TUs just for the changed budget lines;
the affected objects had already been rebuilt explicitly. Logs:
`build/infofields2/build-PRE.log`, `build-renderers.log`, and `build-POST-final.log`.
Artifacts were copied to the required `build/infofields/{PRE,POST}` paths.
The predecessor's images were preserved as `build/infofields/predecessor-{PRE,POST}`.

| Arm | Path | SHA-256 |
| --- | --- | --- |
| PRE | build/infofields/PRE/tomokv | 8d0706e5b166e281aa24532ba08ed3b567de62a472d3d5e99ad29cafcf69f1db |
| POST | build/infofields/POST/tomokv | a1797b206ec31d67aa898f314f4ed10e1b235f56aaff6d578b8e82119e336725 |
| POST copy | build/tomokv | a1797b206ec31d67aa898f314f4ed10e1b235f56aaff6d578b8e82119e336725 |

[All digests, including the oracle and proof tool](docs/infofields2/SHA256SUMS).
The proof tool is unchanged, SHA-256
`13b3714b384eb26fa3023b3296baecd99e245dd7d91e6bc8d350729c42c3e29b`.

```sh
taskset -c 112-127 python3 tools/infofields_artifacts.py \
  build/infofields/PRE build/infofields/POST docs/infofields2/final-proof
```

| Body audit metric | PRE | POST / result |
| --- | ---: | ---: |
| Objects | 94 | 94 |
| Function instances | 17,057 | 17,057 |
| Changed bodies, all explained | — | 80 |
| Ordinary bodies equal | 4,828 | 4,828 |
| Literal raw-byte equal ordinary object bodies | — | 4,764 |
| Ordinary static instructions | 1,133,435 | 1,133,435 |
| Linked ordinary bodies proven | 3,013 | 3,013 |
| Literal raw-byte equal linked bodies | — | 449 |
| Locked layouts and member offsets | 16 namespace/type combinations | all equal |
| Unexplained changed bodies | — | 0 |
| .text bytes | 7,811,893 | 7,817,349 (+5,456) |

The unchanged tool canonicalizes actual address relocations, retaining opcode,
operand, named target and referenced-constant equality. This is not a claim that
linked address displacement bytes are identical. [Summary](docs/infofields2/final-proof/summary.json),
[every changed body and reason](docs/infofields2/changed-bodies.md),
[full JSON receipt](docs/infofields2/final-proof/changed-bodies.json), and
[locked layouts](docs/infofields2/final-proof/layouts.json).
No PAD arm: no locked layout changed. No throughput or IPC gain is claimed.

Only edited production TUs have lane-specific budget overrides: climon
25735/25670; t_server 31290/31632 (db0 retains mainline's max-inline-insns-auto=16);
snapshot 14584/14457. Other mainline budgets are unchanged.

## Baseline live evidence supplied by mainline

These are the requested `differ2-*` logs, not the older refused `differ-*` attempts.
They used server 0-7, load 8-15, all four suites, both atomics, and seeds
7/19/20/23/91. [Per-suite/atomic inventory](docs/infofields2/baseline-summary.json).

| Arm / geometry | Pass | Fail | Log |
| --- | ---: | ---: | --- |
| POST split | 19 | 21 | build/infofields/differ2-POST-split/differ.log |
| POST armed fused | 22 | 20 | build/infofields/differ2-POST-armed-fused/differ.log |
| PRE split | 10 | 30 | build/infofields/differ2-PRE-split/differ.log |
| PRE armed fused | 12 | 30 | build/infofields/differ2-PRE-armed-fused/differ.log |

All ten POST infofix legs failed field placement and all ten POST monitor legs
failed the incorrect expected stream/refusal visibility in each geometry. POST
split also had the reported psfix atomic=0/seed=91 SAVE race. PRE lacked the new
INFO/save-status fields and MONITOR filtering. These results are baseline evidence,
not passes for the retained change.

## Live commands and results

Every new live server runs on **112-119**, every driver on **120-127**. Geometry is
split `--ratio 6:2` or fused `--thread-mode fused --read-local 1`, always
`--shards 16 --databases 16`, atomic=0 and 1. Oracle:
`/home/user/Projects/redis74/src/redis-server` (vanilla 7.4.10).
This lane ran no compilation or concurrent load during these proofs.

The serial runner records every exact server/driver command, result, and orderly
stop in its JSON receipts and parent logs:

```sh
taskset -c 120-127 python3 tools/infofields2_live.py smoke build/infofields2/live-smoke
taskset -c 120-127 python3 tools/infofields2_live.py controller build/infofields2/live-controller
taskset -c 120-127 python3 tools/infofields2_live.py matrix build/infofields2/live-matrix
```

The matrix expands to this exact harness command for each arm and geometry:

```sh
REDIS74_ROOT=/home/user/Projects/redis74 \
GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis74/src/redis-server \
GATE_DIFFER_PROOF_SUITES=docs/infofields/suites.txt \
GATE_DIFFER_PROOF_SEEDS=docs/infofields/seeds.txt \
GATE_LOAD_CORES=120-127 GATE_DIFFER_GEOMETRY="$geometry" \
GATE_DIFFER_OUT="$directory" GATE_RUN_ID="infofields2-$arm-$geometry" \
bash tests/differ_gate.sh "build/infofields/$arm/tomokv" 18899 18900 112-119 6:2
```

The literal values for all four expansions are in the retained command receipts.
Suite and seed files have one entry per line. No permanent seed was removed.

DIFFERENTIAL_MATRIX_PENDING

### Rate, peak and controller witnesses

All four smoke boots and all eight controller-off boots passed the paired-server
rate and peak properties. Offered load was 2,000 PING/s; the measured rate below
includes the pacing boundary. Both INFO Stats polls on each server were within
15% of the measured offered rate. Every boot passed the 8 MiB peak witness after
allocation and deletion, while polling only Stats during the allocation window.

| Run ID (under build/infofields2/) | Measured offered/s | Target polls/s | Oracle polls/s | 8 MiB peak |
| --- | ---: | --- | --- | --- |
| live-smoke/split-a0-config0 | 2006.0 | 1999, 1998 | 1992, 1992 | PASS |
| live-smoke/split-a1-config0 | 2006.0 | 1998, 1997 | 1992, 1992 | PASS |
| live-smoke/armed-fused-a0-config0 | 2005.9 | 1998, 1998 | 2004, 2005 | PASS |
| live-smoke/armed-fused-a1-config0 | 2005.9 | 1999, 2000 | 1992, 1992 | PASS |
| live-controller/split-a0-config0 | 2005.9 | 1999, 2000 | 2004, 2005 | PASS |
| live-controller/split-a0-config1 | 2006.0 | 1998, 2010 | 2004, 2005 | PASS |
| live-controller/split-a1-config0 | 2006.0 | 1997, 1998 | 1992, 1992 | PASS |
| live-controller/split-a1-config1 | 2006.0 | 1997, 1998 | 1992, 1992 | PASS |
| live-controller/armed-fused-a0-config0 | 2005.9 | 1999, 1998 | 1992, 1992 | PASS |
| live-controller/armed-fused-a0-config1 | 2005.9 | 1998, 2000 | 2004, 2005 | PASS |
| live-controller/armed-fused-a1-config0 | 2005.9 | 1998, 2000 | 1992, 1992 | PASS |
| live-controller/armed-fused-a1-config1 | 2005.9 | 1998, 2000 | 1992, 1992 | PASS |

The eight `live-controller` boots all used `--key-lb 0 --client-lb 0 --flip-auto 0`.
Each also passed `tests/infofix.py` (**41 checks**). `config0` returned an empty
`config_file`; `config1` returned exactly
`/home/user/Projects/cx-infofields/build/infofields2/live-controller/<geometry>-a<atomic>-config1/loaded.conf`.
Both peers exited with status 0 after SIGTERM in all twelve paired boots; no forced
termination was used. [Smoke commands/results](docs/infofields2/live/smoke-commands.json),
[controller commands/results](docs/infofields2/live/controller-commands.json),
[smoke measured values and shutdown receipts](docs/infofields2/live/smoke-summary.json),
[controller measured values and shutdown receipts](docs/infofields2/live/controller-summary.json).

The quiet preflight refused once before `live-controller/split-a1-config1`:
`quietcheck: assigned cores busy: cpu113=30% cpu118=30%`.
The runner retried after 200 seconds; the next screening passed. The cause was not
established, so this is not attributed to a sibling compiler. The remaining smoke
and controller screenings passed on their first attempt.

### Non-gated strict witnesses

All four smoke geometries/atomics passed the gated monitor check: 19 driven
commands and 15 visible lines per peer. The refused-command witness exited 1 in
each boot and printed exactly these three target-only payloads:

```text
"SET" "ifmon:denied" "v"
"GET" "outside:denied"
"GET" "ifmon:noauth"
```

The `--scripts` witness also exited 1 in each boot. In addition to those three
extra lines, the target missed six `lua "get" "ifmon:key"` lines, one after each
script entry variant. In all eight strict witness runs, the oracle had **no extra
or missing lines**. These are observed failures documenting the two deviations,
not passing tests. [Example refusal receipt](docs/infofields2/live/smoke-split-a0-config0-strict-refused.log)
and [example nested-script receipt](docs/infofields2/live/smoke-split-a0-config0-strict-scripts.log);
all four geometry/atomic receipts are retained beside them.


## Gate rows, checks and remaining work

Rows: **+0 quick / +0 full**. `EXPECT_QUICK=500` and `EXPECT_FULL=517` are unchanged.
The existing differential folds are at tests/gate.sh:3393 and :3405, both after
the quick-tier exit at :3365. The standalone strict witness adds no suite or row.
No full 517-row gate was run; the maintainer still owns landing verification.

Serverless checks: 7 infofields controls and 24 differential harness tests pass;
Python syntax, shell syntax and `git diff --check` pass. The tests/ text audit
used grep, including literal, hexadecimal and escaped-byte spellings:
[before](docs/infofields2/test-text-before.txt), [after](docs/infofields2/test-text-after.txt).

Remaining mandatory work: implement actual nested Lua feeds without altering
ordinary bodies, make `--scripts` strict witness pass for admitted script commands,
and promote those nested assertions into the gated leg. Refusal assertions remain
separately documented under the explicitly allowed path 2. The live witnesses must
not be represented as proof that the nested implementation exists.
