## maxmemrace

**Verdict: the defect is real, and it is fixed in POST.** On the headline (PRE `e32b04a44`),
`CONFIG SET maxmemory` (also `maxmemory-policy` and `maxmemory-samples`) can reply `+OK` while a
shard owner still admits, refuses and evicts under the old value. A command the client sends after
reading that `+OK` can be refused with OOM after a lift to 0, admitted after a tightening under
`noeviction`, or evict keys after a lift. A directed row reproduces it in every one of 48 tested
geometries (428 of 432 lift/tighten trials), and a toggle stress reproduces it at scale. In POST, every shard owner switches
inside its own CONFIG fragment, so the barrier's `+OK` follows every owner's switch.

No throughput or latency claim is made. This lane ran no performance benchmark, load generator,
ABBA/NIC measurement, full iteration, push or merge.

Base `e32b04a44`, branch `cx-maxmemrace`. Every server, oracle, driver and build ran on CPUs
32–47: servers on 32–39, clients on 40–47, builds with `taskset -c 32-47 make -j16`. Listeners used
ports 20300–20399, and every boot pinned `LC_ALL=C`. The oracle is Redis 7.4.10
`/home/user/Projects/redis/src/redis-server`, SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.
Receipts are under [docs/maxmemrace](docs/maxmemrace).

### Results at a glance

| Evidence | PRE `e32b04a44` | POST | Redis 7.4 |
|---|---|---|---|
| Directed row, 48 geometries × 12 trials | **fails 48/48 legs**, window open on every counted trial (1 re-arm) | **passes 48/48**, window open on every trial, no re-arm | passes |
| Toggle stress, 32 legs × 100,000 toggles | 57,755 OOMs after a lift `+OK`; 49,003 admissions after a tight `+OK`; 41,168 evictions after a lift `+OK` (19 of 32 legs) | **0 / 0 / 0** (0 of 32 legs) | 0 / 0 / 0 (4 legs) |
| Fused legs with the publisher loaded, 8 × 100,000 | 42,151 / 7,305 / 29,822 (3 of 8 legs) | **0 / 0 / 0** | — |
| Fused shadow scheduler (`--reorder 1`), 8 × 100,000 | 59,890 / 19,128 / 19,756 (4 of 8 legs) | **0 / 0 / 0** | — |
| Command-scope instructions (GET/SET/INCR/MGET/MSET, 48 scopes + 4 read-local GET) | reference | **+0 in all 52**, identical per-function counts | — |

The stress counts are violations: SET refused with OOM after a lift `+OK` / SET admitted after a
tight `+OK` (`noeviction` only) / `evicted_keys` growth after a lift `+OK` (`allkeys-lru`).

### Code-level guarantee after `+OK`

PRE publishes the maxmemory family like this:

1. `CONFIG SET` is an all-shard scatter. Every shard's owner runs `cmd_config(shard, op)` as one
   fragment, and the IO thread replies `+OK` once every fragment has completed.
2. Only shard 0's fragment publishes (PRE `src/cmd/t_server.cc:1796-1814`). `set_maxmemory_config`
   stages every per-thread mailbox and then stores an even version (`src/core/server.h:3539-3557`).
3. An owner adopts the mailbox only in `refresh_live_config()`, at the top of an owner pass
   (`src/core/ex_loop.h:401` fused, `:625` split). LB/flip-frozen passes skip it, and
   `sweep()`/`fused_sweep_impl()` drain tasks without it. The refresh writes each owned store's
   enable flag, limit, policy and samples, which `budget_admit` (`src/store/flatstore.h:1663`), the
   insert/overwrite `make_room_for` admissions (`:1258`, `:1725`, `:2990`) and `evict_over_limit`
   (`src/cmd/eviction.cc:6`) read. It also sets the owner's enable flag, touch policy and LRU clock;
   `owner_control_tail` runs `eviction_cycle()` only while that flag is set (`ex_loop.h:1534`).
4. Nothing makes the `+OK` wait for any owner to reach a pass boundary after the commit. The
   publishing owner's own pass always began before its commit. `ThreadCtx::drain_tasks`
   (`src/core/thread.h:631`) keeps receiving from a producer channel while it is non-empty, and
   `ExLoopT::drain_tasks` executes each full 32-task batch inside that loop. A task enqueued after
   the client read `+OK` therefore executes in the same stale pass.

So for these three knobs PRE guarantees only **next owner pass**, and an owner pass lasts as long as
its backlog. An idle server rarely shows the defect for a separate reason. A parked CONFIG IO
thread is woken by the publisher's completion message only when the publisher submits at the end of
its pass, so the `+OK` itself leaves after the stale pass. That explains why pubtrackfix's 128-cycle
idle probe found nothing. Any other traffic on the CONFIG connection's IO thread lets the `+OK`
leave mid-pass; the directed row keeps that thread busy with PINGs.

POST changes the publication and adds a per-owner switch:

- **Single publication.** The first fragment of a CONFIG SET to take `g_config_mu`, on whichever
  owner, claims the family's single publication (`config_claim_memory_publication`,
  `t_server.cc:1700`). It writes the table entries and the live values together, in claim order
  (`config_publish_memory`, `:1718`). Shard 0 no longer writes these three table entries.
- **Per-owner switch.** Every fragment then calls its owner's `ExLoopT::apply_memory_config()`
  (`ex_loop.h:1711`) through a thread-local hook. The executor binds the hook for its whole tenure:
  split `run()` (`ex_loop.h:591`), fused `run_fused()` (`src/core/genthread.cc:65`) and its
  generated `--reorder 1` mirror `run_fused_reordered()` (`src/core/reorder.cc:3031`). The call
  applies the latest committed values to every store the owner holds, to the owner's
  enable/touch/LRU-clock state and, on a fused thread, to the read-local precise-write promise.

The `+OK` waits for all fragments, so every shard owner has switched before it. A late fragment of
an older CONFIG SET applies the latest committed copy, never its own arguments. Owners therefore
converge on the last publication and agree with `CONFIG GET`; the row's CONCURRENT-CONVERGENCE
case checks exactly this.

| Live knob | Read on | PRE guarantee after `+OK` | POST |
|---|---|---|---|
| `maxmemory`, `maxmemory-policy`, `maxmemory-samples`, owner side | owner admission (`budget_admit`, insert/overwrite `make_room_for`), background eviction, touch/LRU state | next owner pass only; **violated after `+OK`** | every shard owner switches before `+OK` |
| same family, read-local precise-write promise, IO side | IO parse marks point writes non-evicting (`io_loop.h:4997`) | next IO pass | fused threads that own a shard switch inside their fragment; split read-local IO threads and shard-less fused threads keep next IO pass (Residuals 1) |
| `maxmemory-clients` | — | not a TomoKV parameter; `CONFIG SET` replies unknown option | unchanged |
| `notify-keyspace-events` | shard notify mask; IO handler-variant choice (`io_loop.h:3490`) | mask: each fragment sets its own shard before `+OK`; variant: next IO pass | unchanged |
| `proto-max-bulk-len` | IO parser limit (`io_loop.h:3250`); string size limit (`g_proto_max_bulk_len`) | parser: next IO pass; atomic: stored by shard 0's fragment before `+OK` | unchanged |
| `client-query-buffer-limit` | IO input limit (`io_loop.h:861`) | next IO pass | unchanged |
| `slowlog-log-slower-than`, `latency-monitor-threshold`, `latency-tracking` | owner and IO timing selectors | next pass; observability only | unchanged (Residuals 2) |
| `save` | owner change counting (`NOTIFY_SAVE`), IO save cron | next pass | unchanged |
| `client-output-buffer-limit`, `timeout` | IO reads the committed copy at each check (`io_loop.h:4838`); live atomic at the cron | committed before `+OK`, read at use | unchanged |
| `maxclients`, `atomic`, `requirepass`, `protected-mode` | accept and dispatch read live atomics (`io_loop.h:1331`, `:4285`, security flags) | stored before `+OK`, read at use | unchanged |
| encoding limits, `stream-node-max-*`, `zc-min` | per-shard fields that each fragment sets (`t_server.cc:2011`) | set on every shard before `+OK` | unchanged (Residuals 3) |
| `locale-collate`, `hz`, `dynamic-hz`, `tcp-keepalive`, `appendfsync`, `aof-*`, `auto-aof-rewrite-*`, `acl-pubsub-default`, `acllog-max-len`, `slowlog-max-len`, `shutdown-on-*`, `latency-tracking-info-percentiles` | globals and atomics at use (cron, accept, AOF, INFO, SORT) | stored by shard 0's fragment before `+OK` | unchanged |

On io_uring, "next IO pass" is effectively fresh for any command sent after `+OK`. The rings use
`IORING_SETUP_DEFER_TASKRUN`, and the IO loop reaps receive completions once per pass, after its
pass-top refresh (`io_loop.h:569`, `:634`). Completions become visible only at the kernel entry that
ends the previous pass, so a command that arrived after the commit is always parsed after a
refresh. On epoll, a pass can `recv()` directly after its refresh. A command arriving during an IO
pass that straddles the commit is then parsed with the old value, for that one pass.

### Directed row

`tests/maxmemrace.py` (gate job `maxmemrace`) proves the geometry on each boot (`DEBUG SHARDS`,
`DEBUG IO-THREAD`). Then:

1. `b1` pipelines 20 `LPOS` scans of a 20,000-element list on shard 0, which occupies the shard-0
   owner X;
2. `a`, on an IO thread other than X, sends `CONFIG SET maxmemory <new>`;
3. `b2`, on `a`'s IO thread, pipelines 60 more scans behind the fragments, so X executes its
   fragments mid-drain;
4. `a` reads `+OK` and immediately sends `SET` of a key on another of X's shards.

A third connection on `a`'s IO thread sends PINGs throughout, so that thread polls instead of
parking. The cases are:

- **LIFT-NOEVICTION** and **LIFT-ALLKEYS-LRU**: maxmemory goes 1 → 0, and the SET must be admitted.
- **TIGHTEN-NOEVICTION**: maxmemory goes 0 → 1, and the SET must be refused with OOM.
- **CONCURRENT-CONVERGENCE**: two clients race conflicting `CONFIG SET maxmemory` pipelines from
  different IO threads. Afterwards a SET on every shard must admit or refuse exactly as the final
  `CONFIG GET` says.

Each case runs 3 trials per leg. A candidate trial counts only if its window opened: X still owed
scan replies after the SET was written, and all 80 scans found the list. A trial whose window did
not open is re-armed on fresh state, at most 3 attempts; the assertion is never relaxed.

The legs are 1s/2s × uring/epoll × atomic 0/1 × read-local 0/1 × databases 1/16 (32 legs), plus
`--reorder 1` for all 16 fused products, for 48 candidate legs. Every candidate leg uses
`--key-lb 0 --client-lb 0`. The Redis oracle runs the same wire sequence and must pass. The window is
not asserted there; its allkeys-lru limit may evict the list, which explains the oracle's 9
re-arms.

| Arm (through `tests/gate.sh`) | Candidate legs passed | Window open | Re-arms | Oracle |
|---|---:|---:|---:|---|
| POST `a3cb3cc9…` | **48/48** | 48/48 legs, every trial | 0 | pass |
| PRE `692a0eae…` | **0/48**: every lift/tighten trial fails except 4 timing-dependent passes (7–9 of 9 per leg); convergence passes | 48/48 | 1 | pass |
| PAD-A `7eb78717…` | **0/48** (8–9 of 9 per leg) | 48/48 | 0 | pass |

The row does not separate the superseded first candidate from POST on the `--reorder 1` legs: that
binary also passes them, probably because its single publication already runs in the earliest
fragment, so the occupied owner's next pass starts after the commit in this recipe. The source sync
check is what caught that candidate's missing binding, and PRE fails those legs.

Receipts: [row-summary-post.json](docs/maxmemrace/proof/row-summary-post.json),
[row-summary-pre.json](docs/maxmemrace/proof/row-summary-pre.json) and
[row-summary-pad-a.json](docs/maxmemrace/proof/row-summary-pad-a.json).

### Toggle stress

`tests/maxmemrace_stress.cc` (driver) and `tests/maxmemrace_run.py` (runner) boot one fresh server
per leg. The geometry is 16 shards, ratio 6:2 for split, default databases 16, read-local 0 and
LB on. Each leg fills 4,096 keys. Every toggle sets maxmemory to 1 or half the dataset
(alternating), sends a SET wave on 8 other connections the moment it reads the `+OK`, lifts to 0,
and sends another wave the moment it reads that `+OK`. Waves are single (4 rounds) or pipelined
(4 per connection). Three background threads pipeline single-shard `EXISTS` of 256 missing keys,
whose cost does not depend on stored data, so owner passes stay long.

The tight check counts only under `noeviction`. Under `allkeys-lru`, Redis itself admits a write
while an eviction is still running (`EVICT_RUNNING`). The eviction check samples `INFO evicted_keys`
right after the lift `+OK` and again after the wave. The Redis legs use a light background, since a
single-threaded server has no publication window.

PRE main matrix. Each cell is OOM-after-lift / admitted-after-tight under `noeviction`, and
OOM-after-lift / evicted-after-lift under `allkeys-lru`:

| Geometry | noeviction single | noeviction pipe | allkeys-lru single | allkeys-lru pipe |
|---|---:|---:|---:|---:|
| 2s uring atomic 0 | 5 / 3 | 3,756 / 2,559 | 18 / 1,120 | 705 / 2,642 |
| 2s uring atomic 1 | 281 / 207 | 831 / 914 | 1 / 1,223 | 109 / 2,218 |
| 2s epoll atomic 0 | 419 / 494 | 5,773 / 4,498 | 456 / 192 | 2,270 / 1,371 |
| 2s epoll atomic 1 | 2,215 / 2,204 | 39,457 / 38,124 | 138 / 117 | 1,321 / 32,258 |
| 1s uring atomic 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 1s uring atomic 1 | 0 / 0 | 0 / 0 | 0 / 9 | 0 / 8 |
| 1s epoll atomic 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 10 |
| 1s epoll atomic 1 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Every split leg shows the defect. A fused owner's share of the uniform background drains between
round trips, so fused legs rarely straddle the commit. With the background on the publisher's shard
only (`--bg-shard 0`, pipelined), PRE shows 42,151 OOMs, 7,305 tight admissions and 29,822
evictions in 3 of 8 fused legs. With `--reorder 1` (the fused shadow scheduler, same publisher-loaded
background) PRE shows 59,890 / 19,128 / 19,756 in 4 of 8 legs. POST shows zero in all 48 of its legs
across those three families, on the final binary. The Redis oracle shows zero in all 4 legs. An
earlier POST candidate (`982fb693…`, without the reorder-entry binding) also showed zero in all 40
of its legs; its receipts are kept under explicit "superseded" labels. Totals and per-leg data:
[stress-summary.json](docs/maxmemrace/stress-summary.json).

### Fix

The production diff touches `src/cmd/t_server.cc`, `src/core/ex_loop.h`, `src/core/genthread.cc`,
`src/core/reorder.cc` and `src/cmd/command.h`: +144 / −23 lines, in commits `dc7c30569`,
`9a57b4706` and `f174fb0ac`.

- No locked structure changes size or layout (`Op`, `Client`, `ThreadCtx`, `Shard`, `FlatStore`,
  `Config`, `LiveConfigSnapshot`).
- The only new state is one 16-byte `inline constinit thread_local` hook (`command.h`) and a small
  claim list in `t_server.cc`, guarded by `g_config_mu`.
- The per-pass refresh, the mailbox protocol and LB adoption are unchanged.
- `set_maxmemory_config` now runs under `g_config_mu`. No live-config writer takes that lock inside
  its odd-version window, so there is no lock-order cycle.
- `run_fused_reordered()` is generated from `run_fused()` (`tests/r7shadow_sync.py`). The gate's
  `reorder_sync` and `wbland_units` source checks caught the missing binding there on the first
  candidate, and the envelope was regenerated.

### Proof through `tests/gate.sh`

All runs selected jobs with `GATE_ONLY_JOBS`, which gives partial ledgers with no EXPECT tally,
ABBA, NIC or receipt. The CPUs were 32–39 for servers and 40–47 for load, on ports 20310–20399.

The job selection comes from source. [select_jobs.py](docs/maxmemrace/select_jobs.py) takes every
full-tier job whose shell body, or a tests/tools script that body names, matches the maxmemory,
eviction, CONFIG, DENYOOM or pub/sub keyword families. That is 155 of 279 jobs: 144 quick-tier jobs
(the row among them), the full-only `asan_batteries`, `replyoff` and `globcase`, the five
differential parts, and three build-only prerequisites
([selected-jobs.json](docs/maxmemrace/selected-jobs.json)).

| Stage (final POST `a3cb3cc9…`) | Result |
|---|---|
| Affected quick-tier jobs (147 including prerequisites), including the row | 721 ok, 25 FAIL, classified below |
| Same, `moverfix` and `txnorder2` re-run with `--candidate-binary build/tomokv` (byte-identical) | 25 ok, 0 FAIL |
| Full-only `asan_batteries`, `replyoff`, `globcase` | 10 ok, 0 FAIL |
| `tests/differ_gate.sh` standard seeds 7/19/20/21/23, io_uring (split 0/1, armed 0/1, equivalence) | 6 ok, 0 FAIL; 964 passed comparison lines over the four parts |
| Same, epoll | 6 ok, 0 FAIL; 964 passed comparison lines |
| Row on PRE and on PAD-A | FAIL, as required |
| `python3 tests/gates_test.py` (standalone, listener on 20309) | 76 tests OK, plus the nested 14-test persistence check |
| `make all`, the 51 make targets of `job_production_units`, both mdbqsbr arms, blockfix-cost (2) and blockfix2 (2) | 58/58 `make -q` queries fresh; POST equals the make-all output ([freshness.json](docs/maxmemrace/freshness.json)) |

The 25 affected-stage FAIL rows are none of this lane's regressions:

- **1, maintainer-owned accounting.** `ABBA comparison + saturation negative controls`: its
  `gate_receipt` self-test refuses the ledger-label fixture because the source now declares 995
  rows against `EXPECT_FULL=994`. The only missing label is this row's. In memory, adding that one
  label with `EXPECT_FULL=995` is accepted; neither file was edited.
- **1, pre-existing intermittent.** `aoffix2 error (2s, epoll)`: a write that `appendfsync always`
  cannot persist must not be acknowledged. The same assertion fails on PRE 1/240 and POST 2/240 in
  standalone repeats, and the row passed in the earlier run
  ([aoffix2-error-repetition.json](docs/maxmemrace/aoffix2-error-repetition.json)).
- **23, harness path.** 8 `moverfix conservation` and 15 `txnorder2` rows run unit helpers from
  `dirname($CANDIDATE_BINARY)`, and the frozen copy's directory has none. Re-run against
  `build/tomokv`, all 25 pass.

An earlier affected run on the first candidate was stopped after 97 jobs once the R7 omission
surfaced (546 ok, 5 FAIL: the accounting row, the superseded row version, the two R7 checks, and one
row interrupted by the stop). Details: [proof-summary.json](docs/maxmemrace/proof-summary.json) and
the ledgers in [docs/maxmemrace/proof](docs/maxmemrace/proof).

### Command instruction proof

All **52 comparisons add zero instructions**, with identical per-function counts on the final
POST objects. The scopes are GET, SET, INCR, MGET and MSET (atomic 0 and 1) in both namespaces,
1s/2s and batches 1/32, plus fused read-local GET at batches 1/32. The counter is the same ptrace
single-stepper as pubtrackfix (`docs/wave9/step_pc.c`, `tests/wave9_scope.cc`, step-pc
`c3a1bcf8…`). It counts command-scope instructions only; it measures no rate.

| Command (batch 1, atomic 1) | normal 1s PRE → POST | normal 2s | DB0 1s | DB0 2s |
|---|---:|---:|---:|---:|
| GET | 936 → 936 | 1556 → 1556 | 818 → 818 | 1051 → 1051 |
| SET | 1060 → 1060 | 1680 → 1680 | 926 → 926 | 1159 → 1159 |
| INCR | 1511 → 1511 | 2131 → 2131 | 1308 → 1308 | 1541 → 1541 |
| MGET | 10177 → 10177 | 10177 → 10177 | 10325 → 10325 | 10325 → 10325 |
| MSET | 16956 → 16956 | 16624 → 16624 | 16415 → 16415 | 16075 → 16075 |

Full results: [instructions-pc](docs/maxmemrace/instructions-pc) and
[instruction-counter.json](docs/maxmemrace/instruction-counter.json).

### Arms

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/maxmemrace/pre/tomokv` (worktree at `e32b04a44`) | `692a0eae0546d873346034a49987fe4c95e0717f0ce16167b228e6c838f760da` |
| POST | `build/maxmemrace/post/tomokv`, equal to `build/tomokv` (source `ea98be941`, clean) | `a3cb3cc9ca5973af492b577f7647633c4835dd3a6ff3e0b35fd6e6fd78b10faa` |
| PAD-A | `build/maxmemrace/pad-a/tomokv` | `7eb78717853bf5b5c2ef3629fb8b4cddd5f986d2b6a5177bb58ca035a7232bfe` |

PAD-A is a **kind A behaviour twin**. It links the unchanged PRE objects (an exported
`e32b04a44` tree) with an unreachable 3,360-byte `.text` filler and an unused 32-byte `.tbss` block.
This matches POST's `.text` origin and extent and its TLS segment size, which grow by the same
amounts in POST. Individual function, TLS-variable and data-section addresses come from the PRE
link and are not matched one by one ([pad-a.json](docs/maxmemrace/pad-a.json)). The binary
`build/maxmemrace/plants/tomokv-no-reorder-binding` (`982fb693…`) is the superseded first
candidate, kept for reference only; it is not a merit arm.

### Residuals and owner decisions (not changed here)

1. **IO-side caches.** These are refreshed once per IO pass: the read-local precise-write promise on
   split read-local IO threads and shard-less fused threads, the notify handler variant,
   `proto-max-bulk-len` and `client-query-buffer-limit`. They are fresh by construction on io_uring.
   On epoll they can be stale for one IO pass that straddles the commit. For the maxmemory family
   this matters only when enabling an evicting configuration with read-local on, where it gives OOM
   instead of eviction. Closing it needs the `+OK` to wait for every IO thread's pass boundary,
   which means holding the reply in the IO retire path. That is an architecture change, so it is
   left to the owner.
2. **Owner per-pass observability knobs.** Slowlog thresholds, latency tracking and save-change
   counting are applied at the next owner pass, the same window PRE had for maxmemory. The same
   per-owner hook could carry them if Redis-exact SLOWLOG/LATENCY behaviour after `+OK` is wanted.
3. **Per-shard knobs under conflicting concurrent CONFIG SETs.** Each fragment applies its own
   arguments for the notify mask, encoding limits, stream limits and `zc-min`. Conflicting
   concurrent CONFIG SETs can therefore leave shards different. This is pre-existing; the
   maxmemory family now applies only the latest committed copy.
4. **`CLIENT TRACKING` (not CONFIG).** The tracking arm reaches owners' write observation
   (`NOTIFY_TRACKING`) at the next owner pass, while read registration checks the live atomic. A
   write in an owner pass that began before the publication of `CLIENT TRACKING ON` could therefore
   skip an invalidation for a key registered in that same pass. This is a code-level observation
   only; it was not reproduced or changed here.
5. **`aoffix2 error (2s, epoll)`.** Intermittent on PRE and POST alike (above).

### Gate accounting

**DQ = +1, DF = +1.** `collect_job maxmemrace` is at `tests/gate.sh:6305`, before the quick-tier
exit at line 6381. The job (`job_maxmemrace`, line 5540) emits one public row, "maxmemrace CONFIG
SET maxmemory reaches every owner before +OK". The owner should change EXPECT_QUICK **977 → 978**
and EXPECT_FULL **994 → 995**, and add that label to `tests/fixtures/nullrefresh-ledger-labels.json`.
This lane edited neither constant nor the fixture.

### Maintainer merit request (NOT RUN in this lane)

[merit-cells.txt](docs/maxmemrace/merit-cells.txt) holds the **14 generic cells plus the 2s GET/SET
p1/p32 null controls**, parsed by `abbagate.read_cells` into
[merit-cells-parsed.json](docs/maxmemrace/merit-cells-parsed.json). Run PRE/PRE first as the null,
then matched-load PRE/POST and PRE/PAD-A ABBA blocks. Rate at matched offered load decides
regression; cycles/op, instructions/op and IPC explain it.

The change is confined to CONFIG SET and the executor's tenure entry, and the command scopes are
instruction-identical. The expected result is a null within noise. A POST shift that PAD-A also
shows is layout (`.text` +3,360 bytes, `.tbss` +32 bytes), not mechanism.
