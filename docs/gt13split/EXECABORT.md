# EXECABORT/WATCH extraction

Baseline `b38916d8884e3d620a9cda85e0a2fec4363173bf` (fetched and merged
`origin/cpp` before editing). The production-source diff is exactly GT13's three
lines in `src/cmd/multi.inc`: a release store of `true` to the parent abort word
before aborting child units. No loading code or startup change is included.

A queue-time error suppresses command preparation, but EXEC still validates WATCH
and installs a blocking reservation pointing at the parent epoch/abort words.
PRE replies EXECABORT without deciding those words. The reservation survives
retirement and makes an ordinary later SET retry forever. POST decides the parent
before finalizing the owners' reservations, so the SET can execute normally.

`tests/execabort_watch_unit.cc` drives the real public production interfaces:
WATCH, MULTI, a queued SET, SAVE rejected at queue time, EXECABORT, then another SET
on the watched key. It starts no worker, ring, listener, or server. Its SAME
witness object is linked to frozen PRE and POST objects. Both variants use 16
shards and eight configured workers; split is 6 IO + 2 EX. Namespaced tests use
2 databases, DB0 tests use 1. All unit invocations use CPUs 112–119.

`python3 -B docs/gt13split/prove_execabort.py` records 64 bounded runs:

| Case | PRE | POST |
|---|---|---|
| Armed, 2 variants × 2 modes × 2 atomic settings | 8/8 fail: SET denied 1,024 times, waits 1 → 1,025, 1 deferred parent | 8/8 pass: SET immediately OK, waits 0 → 0, 0 deferred parents |
| No WATCH / no queue error | 16/16 pass | 16/16 pass |
| Deliberately absent WATCH window | 8/8 fail with the required arming diagnostic | 8/8 fail with the required arming diagnostic |

The queued SET is also required to leave the key absent. PRE's finite retry bound
is a deterministic dispatch-stall witness, not a timed live-server experiment.
The retained undecided parent explains why another retry cannot make progress.

A literal port perturbed GCC 13's namespaced xshard inlining budget and changed
ordinary `xshard_plain_prepare`. The Makefile pins that translation unit to
`inline-unit-growth=0, large-unit-insns=127577`; the DB0 budget is unchanged.
This retains the exact requested source fix and confines final code changes to:

| Body | PRE bytes | POST bytes |
|---|---:|---:|
| `tomo_db0::multi_execute_task` | 11737 | 11737 |
| `tomo::multi_execute_task` | 11880 | 11880 |
| `tomo::(anonymous namespace)::normalize_multi_blocking_pop` | 3356 | 3329 |

The stock `tools/lbstall_artifacts.py compare build/gt13split-pre build OUTPUT`
passes **1,482/1,482**, both raw bytes and resolved relocation targets. This
includes six GET, four SET, and 240 parse/dispatch bodies. The broader
`docs/gt13split/audit_bodies.py` checks all 854 + 859 functions in the two changed
objects, with unchanged symbol inventories. All other objects are byte-identical.
That broader audit adds the four-byte width for ELF TLS relocation 23 while
preserving the stock canonicalizer's symbol/addend/target comparison; the stock
hot-body tool itself is unchanged. GNU size text is 8,796,237 → 8,796,217 (−20),
data/BSS unchanged. No structure layout changes or PAD arm.

Both release builds and their layout assertions pass. Existing serverless
`watch_parent`, `watch_cycle`, `watch_oom`, `mset_arity`, and `rename_overlay` pass.
The new row's three verdict tests reject missing builds, failed witnesses,
unarmed success, and unrelated failures. Gateplan passes 23 planning + 11
measurement-metadata tests; seven existing row/boot-wiring tests pass. Shell
syntax passes. Live Python batteries and the complete gate remain maintainer work.

One row: `tests/gate.sh:1587`, collected at line 3144, before the quick exit at
line 3272. Delta **+1 quick / +1 full**: maintainer-owned counts should become
**497 / 514**. EXPECT constants and the ledger-label fixture are unchanged.
The label to add to that fixture is `EXECABORT releases WATCH reservation`.

Frozen binary hashes are in `binaries.sha256`; raw witness and audit receipts
are adjacent. No performance measurement, live server, or gate was run.
