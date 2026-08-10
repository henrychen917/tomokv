# feature_sweep.sh — THredis full-feature correctness + stress sweep

Target tree: `/shared/Projects/.claude/jobs/fd085c8e/tmp/stable-w2` (2s-numa-shared-kv fork, @ 52c760720).
Oracle: stock Redis at `/shared/Projects/redis/src/redis-server` (dev build, v=255.255.255).

## Usage

```
SMOKE=1 /shared/Projects/.claude/jobs/fd085c8e/tmp/feature_sweep.sh    # ~12-16 min
        /shared/Projects/.claude/jobs/fd085c8e/tmp/feature_sweep.sh    # full, ~50-80 min
```

Env overrides: `TREE`, `ORACLESRV`, `CLI`, `FORK_PORT` (7791), `ORACLE_PORT` (7792),
`SRV_CORES` / `LG_CORES` (optional tasksets for server / load-gen, e.g. `0-7` / `8-15`;
default = no pinning at all — the fork is booted with `--tomokv-pin-mode float` so it never
sched_setaffinity's onto cores a concurrent bench owns), `SEED` (stream seed).

Exit code 0 iff no FAIL rows (KNOWN/SUSPECT do not fail the run).

## Outputs

- `/shared/Projects/.claude/jobs/fd085c8e/tmp/feature_sweep.tsv` — `section  test  config  result  detail`
  with result in {PASS, FAIL, KNOWN, SUSPECT}.
  - **KNOWN** = documented-broken/by-design behavior asserted to still behave exactly as
    documented (a change in either direction becomes FAIL).
  - **SUSPECT** = the number/observation failed its plausibility gate or the check was
    vacuous (comparator self-test failed, load did not run, timing missed the window).
    Per the sanity-gate rule these are never silently upgraded to PASS.
- `/shared/Projects/.claude/jobs/fd085c8e/tmp/feature_sweep_logs/` — `sc_<section>.log` per section plus one
  **preserved, uniquely-named** server log per boot (`srv_<seq>_<kind>_p<port>.log`;
  never truncated by a later boot).
- `/shared/Projects/.claude/jobs/fd085c8e/tmp/feature_sweep_work/` — helper (`oracle_helper.py`), per-cell
  comparator outputs (`*.out` + `*.err`), RDB dirs, memtier logs, key caches.

## Box discipline encoded in the script

- Single instance via `flock /tmp/feature_sweep.lock`; cleanup runs on EXIT **and**
  on INT/TERM/HUP aborts.
- **No pkill/pgrep, ever.** Server lifecycle is by recorded PID only, and any signal is
  additionally gated on `/proc/<pid>/comm == redis-server` (exact comm, PID-reuse safe).
- A port that is already serving aborts the cell — a foreign server is never touched.
- Before measurements, `assert_server` re-verifies OUR pid serves OUR port
  (`INFO server: process_id`), so a hijacked/crashed-and-replaced port cannot fake a PASS.
- Boot-time identity control: the fork must expose `tomokv_*` INFO fields; the oracle
  must NOT (guards against testing the wrong binary).
- No bare `wait`; every wait is `wait $PID` or a bounded poll loop; every client call is
  under `timeout`, including every python helper invocation (socket timeouts inside,
  `timeout(1)` outside).
- Every `DEBUG DIGEST` reply is validated as a 40-hex nonzero digest before it can PASS
  (error text / "Could not connect" / zero digests cannot pass); crash-log scans refuse
  to certify a missing or empty server log as "clean".
- memtier `Totals` **last column is KB/sec** — the script reads column 2 (Ops/sec) and
  plausibility-gates it (>5000, else SUSPECT).
- Multi-field INFO comparisons parse ONE INFO call.

## The comparator (`oracle_helper.py`)

Speaks RESP directly over sockets (fully binary-safe keys/values — no redis-cli argv
limits; binary data never traverses redis-cli), and mirrors the fork's `xxh64`
**byte-exactly** (verified against reference XXH64 seed-0 vectors AND cross-checked
against the compiled `server.c` routine on >=32-byte inputs; the helper re-asserts
those vectors at every invocation and exits 3 / SUSPECT if the mirror ever drifts)
so it can craft:
- `hot:*` keys that all land on worker 1 of 2 (`worker = (xxh64(k)&16383)*W/16384`,
  the exact `ex_bucket_table` init) — used for the **>64-keys-per-shard** MGET/MSET
  wave shapes and the reshard hot-load;
- `sbk:*` keys that collide on ONE bucket (same dict/lock granule).

Deterministic stream (fixed seed; identical byte-for-byte across runs and cells):
seed phase (strings at the embed boundaries 1/44/45/170/192/255/4k/64k, binary keys with
`\x00`/`\xff`, hashes/sets/zsets/lists, set-op/z-op operand pools), weighted mutation
phase (SET/GET/APPEND/SETRANGE/GETRANGE/INCR/DECR/INCRBY/SETNX/SETEX/GETSET/GETDEL,
EXPIRE/TTL/PTTL/PERSIST/TYPE/EXISTS/DEL/UNLINK, SADD/SREM/SMEMBERS/SINTER/SUNION/SDIFF/
SINTERCARD, ZADD/ZRANGE/ZINTER/ZINTERCARD, HSET/HDEL/HGETALL, LPUSH/LRANGE, SORT(list),
WRONGTYPE pokes, and ported xshard extras RENAME/RENAMENX/COPY/SMOVE/LMOVE/SINTERSTORE/
ZUNIONSTORE), multi-key phase (MGET/MSET 2..64 and 150 keys; MGET 100 hot keys and an
80-pair hot MSET = >64 keys in a single per-shard sub; MSETNX 1-then-0), TTL tail.

Comparison, lockstep-pipelined (batches of 400) against fork and oracle:
1. **per-op replies** — normalized: set-valued replies sorted, HGETALL pair-sorted,
   error replies compared by CLASS only (version-tolerant), TTL/PTTL banded (3s/3000ms);
2. **DBSIZE**;
3. **full enumeration** — SCAN cursor-loop (or `KEYS *` where SCAN is decoy-inline, see
   below), deduplicated (the SCAN contract permits returning a key twice) + sorted
   byte-compare;
4. **per-key readback** — TYPE-driven (GET / LRANGE / SMEMBERS-sorted / ZRANGE
   WITHSCORES / HGETALL-sorted) + per-key PTTL band (±5s);
5. plausibility gate: implausibly-few final keys => rc 3 => SUSPECT (a vacuous pass is
   not a pass).

**Self-test (positive control, run every time):** one run with a deliberately injected
per-op divergence (a GET is swapped for INCR on the oracle side) and one with an
injected state divergence (extra key on the fork) — the comparator must exit 2 for
both, else the section-A rows are demoted to SUSPECT.

Deliberately excluded from the stream (nondeterministic or version-drift-prone):
RANDOMKEY/SRANDMEMBER/SPOP/HRANDFIELD (RNG), PFADD/PFCOUNT/PFMERGE/BITOP,
hash-field-TTL (HEXPIRE...), streams — see coverage gaps.

## Sections

### A — oracle equivalence (centerpiece)
Default config (`--tomokv-thread-io 2 --tomokv-thread-ex 2`, everything else stock
defaults => FLATSTORE ON, shared node dbs) vs stock oracle; 50k ops (12k SMOKE).
Plus the KNOWN-reject list asserted with the expected message
(`is not supported with tomokv sharding` for MULTI/WATCH; `not yet supported with
tomokv sharding` for keyed EVAL, LCS, ZRANGESTORE, BLPOP/BRPOP, XREAD, GEORADIUS,
GEOSEARCHSTORE, SORT-BY, MIGRATE) — a silent behavior change flips the row to FAIL.
Plus a short-TTL lazy-expiry functional check (kept OUT of the oracle stream because the
fork has no active expiry cron on the shards; long TTLs only inside the stream).

### B — feature-toggle semantics
For each toggle: fresh fork boot with the toggle + FLUSHALL'd persistent oracle + the
reduced stream; results must be IDENTICAL (opdiffs=0, dbsize/enum/readback/ttl equal).
SMOKE cells: `flat0` (tomokv-flat-store no; enumeration via KEYS because top-level SCAN
under flat=0 falls inline onto the empty decoy — asserted as KNOWN), `mcmd-lock`,
`thread-mode-auto`, `xshard-guard0` (+ positive control that LCS
stops being guard-rejected, proving the knob is live), `xshard-pipeline0`,
`express-slim 0` and forced (1), `pipeline-depth 0`, `fake-ring-depth 0`, `num-cdb 0`,
`operand-pool on` (KNOWN default-off knob).
Full adds: num-cdb 1/4, pipeline-depth 8, fake-ring 8, fake-buf 0, all pf-w-* at 0 and
at 256, worker-pop-batch 0/8, drain-tail-skip 0, io-drain-userpoll 0/64, worker-spin
512, mget-coalesce 0/2, setop-coalesce 0, mset-move on, localfast 0, strict-order 1,
zerocopy-off (min-value 2e9), and topology cells ex=1 (non-shared per-worker dbs; KEYS
enumeration) and ex=3 (odd worker count).

### C — feature-effect checks
- `flat-resize-grow`: 200k-key seed must produce `FLATSTORE resize: ... rebuilt X -> Y`
  with Y>X (negative control: no resize line before seeding).
- `flat-resize-shrink`: DEL 145k of 200k must produce a rebuilt line with Y<X
  (+ exact DBSIZE=55000 sanity).
- `qsbr-pending-drains`: overwrite 50k LIVE keys (retire path), then after 3s idle
  `tomokv_flat_batches_pending <= 2`; activity-gated on `tomokv_flat_batches_closed`
  actually moving (else SUSPECT — vacuous).
- `flat-io-pinned-during-digest`: `tomokv_flat_io_pinned` polled during a background
  `DEBUG DIGEST` over ~300k keys must exceed the idle baseline (SUSPECT if the digest
  outran the polls). Plus digest nonzero.
- `fake-ring-decay`: dedicated small server; a held-open connection bursts 3x4000
  pipelined GETs, then idles 10s; `used_memory` must drop >=32KB (open-conn ring decay;
  SUSPECT below the threshold — indistinguishable from noise).
- `exqfull` positive control: `--tomokv-ex-queue-depth 64` + single-hot-key memtier P32
  must drive `tomokv_ex_queue_full > 0` while the server stays correct (sentinel + PING)
  — proves the counter CAN move (its staying 0 under normal load is asserted per-config
  in F) and regression-covers the dropped-dispatch/queue-full path.
- `flips-under-phases`: thread-mode-auto boot; p1 phase then p32 phase; counts
  `flip: GROW-FRONT/BACK complete` log lines (>0 PASS; controller-alive-but-0-flips =>
  SUSPECT; no flip-ctl lines at all => FAIL).
- `reshard-done`: `--tomokv-reshard-min-ops 2000`; 4 crafted worker-1 hot keys hammered
  via `--pipe` loops; `reshard DONE` in log => PASS; ARMED-but-never-DONE => FAIL
  (stuck migration); never armed => SUSPECT.
- `express-lane-engagement`: KNOWN/skip — **no observable exists** in this tree
  (`express_hit_ewma` is not exported and the slim path keeps no counter); semantics
  covered by the two B express cells.

### D — persistence
Reduced-stream seed (mixed types + TTLs) -> full state snapshot (pickle: sorted key
list + typed readback + PTTL + wallclock) -> BGSAVE (status polled) -> SHUTDOWN NOSAVE
-> restart on the same dir -> enumeration equality + per-key readback + TTL re-check
(elapsed-adjusted, ±8s). Then `DEBUG RELOAD` on its own boot: survival with identical
DEBUG DIGEST upgrades to PASS (with note to update the ledger); the documented crash
records KNOWN; survival with wrong digest is FAIL.

### E — script fence (phase 1)
Keyed EVAL rejected; 10 sequential evals (no gate leak); one busy EVAL (~5s Lua loop)
with 20 concurrent SETs (the original SIGSEGV repro) — all must succeed with the server
alive; concurrent EVAL must see `-BUSY TomoKV`; foreign SCRIPT KILL returns +OK and the
owner's reply shows the kill (NOTBUSY timing => SUSPECT, not FAIL); next EVAL clean.
Full mode repeats 20 short busy+SET rounds. Boot sets `--busy-reply-threshold 1000`.

### F — stress spot-checks
Per config class {default io2ex2, numa2 (2 nodes x (1 io + 2 ex)), thread-mode-auto,
mcmd-lock}: 32 sentinels -> memtier 60s/300s (t2 c25 P4, 1:1, R:R over 500k keys, 64B)
-> assert our pid still serves; 32/32 sentinel readback; DEBUG DIGEST completes nonzero;
`tomokv_ex_queue_full == 0`; VmRSS < 3GB; crash-marker scan of the preserved server log
(`REDIS BUG REPORT|ASSERTION FAILED|Segmentation fault|SIGSEGV|SIGABRT|SIGBUS|
AddressSanitizer|Guru Meditation`); memtier ops/sec plausibility gate.

### G — known-issues ledger
Asserted on a live default boot: MULTI/WATCH exact reject message; decoy-blind inner
EVAL (`redis.call('get',...)` inside a keyless script) returns nil while the direct GET
returns the value — if the inner read ever starts seeing shard data the row FAILs with
"update the ledger"; xshard-guard message intact (LCS); DEBUG RELOAD outcome re-emitted
from D. Changes in either direction get flagged.

## Known coverage gaps (also reported in the run's structured output)

See the `coverage_gaps` list in the task output; headline items: the os-opts
knob family (build/root-dependent), pin-mode/pin-cores (deliberately floated for box
politeness), reshard tuning knob family beyond min-ops, flat-load-pct / l3-kb values,
modeshift-test manual actuator, express-lane engagement observable, PF/BITOP/streams/
hash-field-TTL/pubsub/AOF/replication/keyspace-notifications, RNG commands.

## Cautions for interpreting results

- SUSPECT rows on flips/reshard/exqfull are timing/load-sensitive on a busy box: rerun
  those cells in isolation before treating them as regressions.
- The oracle is a NEWER upstream than the fork's 8.6.2 base; per-op error TEXT is
  therefore compared by class only. A FAIL on data bytes is always real.
- `zerocopy` is exercised implicitly in A (64KB values > the 1024 default threshold);
  the `zerocopy-off` B cell is the toggle control.
