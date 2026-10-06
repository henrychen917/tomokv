# psfix2 — mutable AOF-load policy in the netcmd knob matrix

Worktree `/home/user/Projects/cx-psfix`, branch `cx-psfix`. Entry HEAD was
`7cb77166b`; merged `origin/cpp` (`9d957b9fb`) as `e20592e1a` before editing.
Test fix: `80125786c`. No push. This lane requests no performance measurement.

## Stale expectation and replacement

The landing log `build/gate-run.iw7ywm/jobs/netcmd_units/gate-netcmd-config.txt`
failed with `FAIL: knob matrix SET validation`. Its boot-latched matrix still
required live `CONFIG SET aof-load-truncated no` to fail after psfix made the knob
mutable. The local Redis 7.4.10 source confirms the mutable boolean and exact
duplicate-parameter grammar.

Only `tests/netcmd_config_unit.cc` changes executable test code. The test keeps
the existing startup `no` and rewrite directive, checks GET `no`, accepts SET
`yes` and GET `yes`, then accepts SET `no` and GET `no`. In **both** live states:

- SET `1`, `0`, `true`, empty string, and `no ` must fail with the complete reply
  `-ERR CONFIG SET failed (possibly related to argument 'aof-load-truncated') - argument must be 'yes' or 'no'\r\n`.
- A duplicate parameter must fail with
  `-ERR CONFIG SET failed (possibly related to argument 'aof-load-truncated') - duplicate parameter\r\n`.
  The uppercase second spelling is checked too, preserving that spelling in the error.
- The shared validator must reject each command; `execute()` checks the complete
  handler reply. GET must retain the previous value after each path. Duplicate
  commands request the opposite value twice, so partial application is observable.

## Search audit

Searched all text under `tests/` and external `/home/user/Projects/calib` with
case-insensitive recursive `grep` for `aof[-_]load[-_]truncated`,
`aof_rewrite_completions`, and `aof_rewrite_consecutive_failures`.
Commands, matches and dispositions: [search-audit.txt](docs/psfix2/search-audit.txt).

No other stale current-worktree expectation was found. The earlier psfix updates
to `knobs.py`, `redisgap.py`, `aof_rewrite_triggers.py`, and `edgetime_persist.sh`
remain correct. Old INFO names in `psfix.py` identify the PRE negative control;
`differ.py` explicitly forbids those aliases on the candidate.

This worktree has no `calib/` directory. The external search found 628 text
matches, all in 14 `harness-*` historical worktrees and the `harness60` source
copy; none in other calibration consumers. Those historical copies still have
old knob expectations and INFO consumers. They were not edited because this
lane may edit only its own worktree. Full output: `build/psfix2/calib-grep.txt`.

## Correctness proof

The `netcmd_units` selection passed **13/13 rows, 0 FAIL**, including all ten
netcmd regression cases and the formerly failing `netcmd config regression`.
Evidence: [ledger](docs/psfix2/gate-netcmd-ledger.tsv),
[gate output](docs/psfix2/gate-netcmd.log),
[config unit output](docs/psfix2/netcmd-config.txt). Artifacts:
`build/gate-run.YNzjqM`. This is a partial gate, not a full receipt.

The config/AOF selection passed **59/59 rows, 0 FAIL**: one release row, two
`config_unit` rows, 28 `aof-epoll` rows and 28 `aof-uring` rows. All four
`configuration reduction + actual geometry` rows passed (epoll/uring × atomic
0/1), as did the 1s/2s in-window recovery rows. Evidence:
[ledger](docs/psfix2/gate-config-ledger.tsv), [gate output](docs/psfix2/gate-config.log).
Artifacts: `build/gate-run.rA4vCU`. This is also a partial gate; the release row
appears in both selections, and neither run claims a full receipt.

All requested processes were pinned to CPUs 112–127, with eight server CPUs,
16 shards, and ratio 6:2 for split.
The related parser and live knob rows are in `config_unit`, `aof-epoll`, and
`aof-uring`; the latter two contain both atomic variants of `tests/knobs.py`.

Commands (run serially; each selects its normal build prerequisites):

```bash
GATE_ONLY_JOBS=netcmd_units taskset -c 112-127 tests/gate.sh iteration \
  --server-cores 112-119 --load-cores 120-127 --server-smt '' --load-smt '' \
  --ports 18340-18342
GATE_ONLY_JOBS='config_unit aof-epoll aof-uring' \
  taskset -c 112-127 tests/gate.sh iteration \
  --server-cores 112-119 --load-cores 120-127 --server-smt '' --load-smt '' \
  --ports 18340-18342
```

Reran psfix's existing harness once, which invokes `tests/differ.py ... psfix 7`
against fresh harness-owned target and Redis processes in RESP2 and RESP3:

```bash
taskset -c 112-127 python3 tests/psfix.py --binary build/tomokv \
  --root build/psfix2/oracle-2s --cores 112-119 --load-cores 120-127 \
  --port 18340 --mode 2s --databases 1
```

**PASS: 27 exact/property checks per protocol, zero diffs (54 total).** The
failed-SAVE counter preservation, successful retry, and AOF rewrite exclusion
checks also passed. [Oracle log](docs/psfix2/oracle-2s.log). Oracle: Redis 7.4.10,
`/tmp/claude-1000/redis74/src/redis-server`, verified SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.
Both gate cleanup paths succeeded; the oracle harness reaped its own children.

**Rows: +0 quick / +0 full.** No EXPECT constant or fixture is edited by this
lane. At the merged baseline, `config_unit` is collected at gate line 3177,
`netcmd_units` at 3218, and both AOF jobs at 3294, all before the quick-tier exit
at 3352. Existing totals remain 499 quick / 516 full.

## Production identity and historical-hash mismatch

The requested historical SHA-256 was already different from `build/tomokv`
before this lane changed anything:

```text
58f8cf4db216d07da391d907a1758b1e98dfd90e5b2ce9c2fc29951042836cd6  build/tomokv (entry)
65ebd0960fca2f1b00753b59cd2529a1454d523e1bf02f4c41c00c6894c1661c  build/psfix/POST/tomokv (frozen original)
```

**The exact historical-hash requirement is not satisfied by the current tree.**
The entry HEAD had already merged production changes through `570712d8d`;
the newly required merge adds newer mainline production changes. No production
source or Makefile changes are authored by psfix2. The exact historical hash
cannot be asserted for a build of this merged source. There are no lane production
edits to undo; the historical frozen binary is preserved.

`taskset -c 112-127 make -j8` passed. Its merged-source production build is:

```text
9155ab743b5421091321e0a3ffb87ac27bfeb44dde9433e5605533dbb37ea0f4  build/tomokv
```

Preserved that binary as `build/psfix2/merged-baseline-tomokv` before the gate.
After all proof jobs, the final `make -j8` reported nothing to do and `cmp`
confirmed `build/tomokv` is byte-identical to that preserved merged baseline.
Both hashes remain `9155ab743b5421091321e0a3ffb87ac27bfeb44dde9433e5605533dbb37ea0f4`.
The frozen original remains exactly the requested `65ebd096...` hash.
[Full hashes](docs/psfix2/production.sha256), [final make](docs/psfix2/final-make.log).

`git diff e20592e1a -- src Makefile tests/gate.sh` is empty; `git diff --check`
passes. No production, EXPECT, or fixture edit was introduced by the test fix.
No performance measurements, PAD arms, or push were performed.
