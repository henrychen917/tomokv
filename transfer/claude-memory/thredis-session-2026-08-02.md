---
name: thredis-session-2026-08-02
description: 55-commit session — 3 P0-class fixes, stress_validation soak built, bigstress made honest, ABCD A1-A3 done and B answered as a negative result; plan in docs/NEXT_CONTEXT_PLAN.md
metadata:
  type: project
---

Tip `2c54f89a8` on `origin/2s-numa-stable-dev`. FULL bigstress
`PASS=28 FAIL=0 INCONCLUSIVE=1 SKIP=0 NA=12`, all four reference cells above baseline.
**Full plan: `docs/NEXT_CONTEXT_PLAN.md` in the repo.**

## Fixed (real defects)

* **J4 P0** — `flat_resize_active` parks every worker and only IO slot 0 could clear it; its 200 ms
  deadline was evaluated by that same blocked thread. CAS-guarded any-thread watchdog (`4754a73a5`).
  Later caught firing in the wild during a reload.
* **J3** — `DEBUG RELOAD` killed a sharded server 8/8 (`Duplicated key found in RDB file`).
  `RDBFLAGS_ALLOW_DUP`, scoped to the DEBUG path only. A stop-the-world attempt was **reverted** —
  it cured the crash and wedged the server.
* **K1** — `OBJECT ENCODING/REFCOUNT/FREQ` and `MEMORY USAGE` returned **nil for keys that exist**:
  key at argv[2], never dispatched, ran inline against the empty decoy db. Same class as the SCAN
  decoy bug.
* **A1** — no boot-time capacity check: `--tomokv-nodes 8 --tomokv-thread-io 8` wrote past
  `tm_io_sig[]`. Also `tomokv-cores-per-node` couldn't express its own max pool (64 vs 96).

## Confirmed already-fixed (by measurement, not by reading filings)

Set-op posmap leak (the handoff's "highest-priority open item"), active expiry on shard dbs (#42).

## Retracted — my own bad evidence

**J6** "DEBUG RELOAD orphans client sockets" was **wrong twice**: `connected_clients` is
PER-IO-THREAD, and my follow-up probe encoded `k%06d` behind a `$8` header so the server correctly
closed every connection. Correct probe: 16 conns, all live, `HUNG conns: []`.

## Built

* **`tools/preflight/stress_validation.{sh,py}`** — ~2 h single-server soak, numa1 then numa2.
  **Has never completed a full run** (3 attempts, all stopped by my own harness bugs — all fixed,
  none re-run). Must go green once before being trusted as the ABCD gate.
* **bigstress made honest** — `NA` verdict class (structurally-impossible ≠ untested), `--dir`
  hardening, flip tolerance raised above the noise floor, **median** baseline ratchet.

## ABCD

A1/A2/A3 done and gated. **B answered as a negative result** — see
[[thredis-worker-overhead-bound]] and [[thredis-prefetch-truth]]. C expected negative too. **D is
the interesting half** (`docs/ABCD_D_DESIGN.md`): IO owns classification/admission/SEDA window, EX
owns readiness + aging; controller built on the `lb_grp_ops` idiom. Queued after: threadcap (#66),
per-node semi-main driver (#67).

## Process traps hit FOUR times this session

`pgrep -x` matches the command name (`bash`), `pgrep -f` self-matches your own shell,
`timeout cmd &` captures **timeout's** pid (leaving the real server alive to fake later results),
`grep -c … || echo 0` emits `0\n0`. **Trust the listening port and the withbox parent pid.**
See [[thredis-ab-harness-traps]].
