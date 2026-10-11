# respresume — NT4.2 resumable RESP multibulk parser

## respresume

Worktree/branch: `/home/user/Projects/cx-respresume`, `cx-respresume`, based on
`origin/cpp` `991d48f65`. Nothing was pushed. The lane was taken over from a codex
agent stopped by its provider's content filter; its two commits were reviewed and
kept (`873b71047` parser, `7320724a2` witnesses/rows/tools), then corrected and
completed by the commits listed under *Change list*. Every build, server, oracle and
load generator ran under `taskset` inside CPUs **64–79** (server 64–71, Redis oracle
72, drivers/loaders 73–79 unless stated); ports 25400–25449. No performance claim is
made from these shared cores: every number below is a correctness bound, an event
count, or a static/traced instruction count. (Only the agent's own interactive shell —
git, grep, report scripts — ran on its inherited CPUs.)

### Result (PRE = `991d48f65`, POST = this branch)

| Requirement (spec) | PRE | POST | Bound | Verdict |
|---|---|---|---|---|
| Completed arguments re-parsed per command, NT4 probe, 4 cells (audit metric) | 0.13 – 42.07 | **0** in all 4 | 0 | met |
| Length lines decoded more than once per command (independent decode balance) | 0.15 – 84.15 | **0** in all 4 | — | met |
| T12 trickled CPU per frame vs Redis at 50k / 100k / 200k args (ns resolution, median of 5) | 11.9x / 19.4x / 25.7x | **2.51x / 2.37x / 2.40x** | within 3x | met |
| T12b neighbour PING median during a 2M-argument trickle | 6.22 ms (n=23) | **0.02 ms** (n=408) | < 1 ms | met |
| Fragmentation differential vs unsplit and vs Redis 7.4 (4 plain boots; POST also TLS, ASAN, all differ suites fragmented) | byte-identical (correct, but quadratic) | byte-identical | identical | met |
| Complete-frame parse instructions, every dispatcher clone (window + parser body) | GET 197–206, SET 253–265 | GET 195–202, SET 250–260 | not slower | met (GET −1..−6, SET −2..−7) |
| Stores executed on that path (parser GET / SET, plus the window's `rbuf_off` store) | 20–22 / 24–27, +1 | 19–21 / 23–26, +1 | no new stores | met (one fewer: the canary) |
| Stack canaries in `resp_parse_t` (NT4.3) | 10 canary loads, 26 `__stack_chk_fail` refs | **0 / 0** | report | removed |
| New gate rows | 12 FAIL | 12 ok | FAIL PRE, PASS POST | met |
| Existing batteries (differential ×4 geometries/engines, respcompat, netio, netcap, TLS, units, `gates_test`) | — | all pass except 8 epoll `infofix` legs per epoll geometry, which PRE fails identically | no regression | met (finding F1) |

### Change list

Source (4 files, +217/−22 against `origin/cpp`; the parser is the inherited `873b71047`
plus the takeover fix `a49849e25`):

- `src/net/resp.h`
  - `RespFrontier` (32 B): heap array of `{offset, length}` argv pairs plus `expected`,
    `completed`, `next`, `bulk` (`UINT64_MAX` = next names a `$` header, else the decoded
    length of the payload at `next`). Every position is relative to the unconsumed frame's
    first byte; no pointer into the receive buffer is ever stored.
  - `resp_parse_t<kLimited, kResume>`: the production instantiations are now
    `kResume = true` only. Each former `pos = start; return Incomplete` becomes a cold
    `resp_suspend(...)` that records the argv already built plus the resume point. Each
    former restart into `resp_parse_slow` on an exceptional header (`$0` empty bulks,
    counts above 1 Mi, malformed or negative lengths) becomes `resp_parse_start` /
    `resp_parse_tail`, which continue at the current argument; PRE re-walked the
    already-parsed prefix of any frame reaching such a header, even a complete one. The
    stateless inline arm (dead in production: both callers dispatch non-`*` frames to
    `resp_parse_inline` with Client's cursor) is compiled out of the resumable
    instantiations, which removes the address-taken `scanned` local and with it the
    stack canary (NT4.3).
  - `resp_resume` (cold): continues at `next`, appends offsets only, and materialises
    argv into the Op once, when the frame is complete and the buffer is pinned.
    `resp_parse_start` handles a count line that was itself incomplete (exact slow
    decoder; counts above 1 Mi).
  - The stateless `resp_parse` / `resp_parse_limited` wrappers (tests, tools) are
    unchanged.
- `src/net/conn.h`: `Client::multibulk_` occupies the IO-only alignment hole at offsets
  96–127 (`sizeof(Client)` stays 1984; every layout assertion unchanged). The pending
  flag is bit 31 of the existing inline cursor word at offset 76 (inline requests are
  bounded at 64 KiB, so the bit is free), so `advance_parse`'s existing
  `inline_scanned_ = 0` store invalidates it on every consumption: no new store on the
  complete-frame path. `resume_multibulk` (cold, noinline) clears the flag and releases
  burst storage on Ok/Empty/Error; `mark_closing`/`mark_dead` do the same.
- `src/core/io_loop.h` (`parse_and_dispatch`) and `src/core/reorder.cc` (R7 copy
  `r7_parse_and_dispatch`): one `__builtin_expect(false)` test of the pending bit
  before the existing inline/auth/limit selection; the existing parser calls pass
  `&conn.multibulk_frontier()`; an Incomplete multibulk sets the bit.

Takeover corrections (this session, all small commits):

| Commit | What and why |
|---|---|
| `a49849e25` | Removed the inherited `if (!rest) inline_scanned_ = 0;` from `reset_rbuf_at_quiescence`: a pending frame always keeps its `*` byte, so the store was dead, but it added a conditional store to the per-pass retire path. |
| `19c11de76` | The twelve inherited gate rows had never executed. Fixed on first run: DEBUG was disabled in their boots (neighbour rows could never pass), the corpus used `SCAN 0` (tomo returns a shard cursor on an empty keyspace, not byte-comparable; replaced by a one-member `SSCAN`), and the CPU/neighbour bounds were re-derived from measurements (below). |
| `2c52e929c` | PRE/POST reproductions; observer rewritten to carry an independent decode-balance counter next to the audit counter. |
| note | Only the lane's own never-executed rows and witnesses were changed; no pre-existing test or assertion was edited (`tests/differ_gate.sh` only gained the opt-in `GATE_DIFFER_DRIVER` for focused proofs). |
| `02a9718ef` | Fast-path tools and tables; PRE/POST artifacts regenerated for this session's binaries (the inherited ones described binaries that no longer exist). |
| `f64b619a4` | Correctness witnesses and receipts: differential proofs, limits, live FLIP, TLS, ASAN server; `GATE_DIFFER_DRIVER`; TLS EOF handling in the fragment driver. |
| `bade93676` | Removed the never-executed `runtime-plan.{json,sh}` handoff (CPUs 112–127); PAD-A regenerated for the final POST. |
| `8ecf2ed29`, `9f25fcbd5` | Lifecycle site line numbers; fragmented-differential, final gate-row and `gates_test` receipts. |

### Reproductions, PRE vs POST

**T12** — audit script unchanged except ports/CPUs/paths (`tools/respresume_repro.py`;
utime+stime, 10 ms ticks, so Redis rounds to 0.00–0.01 s).
[PRE](docs/respresume/repro/t12-pre.out), [POST](docs/respresume/repro/t12-post.out).

| N args | Redis trickled CPU | PRE trickled CPU | POST trickled CPU |
|---|---|---|---|
| 50k | 0.00 s | 0.04 s | 0.01 s |
| 100k | 0.00 s | 0.13 s | 0.02 s |
| 200k | 0.01 s | 0.34 s | 0.03 s |

**T12x** — same frames and send pattern, CPU summed over every server thread from
`/proc/PID/task/*/schedstat` (ns), median of 5 (`tools/respresume_t12x.py`,
[results](docs/respresume/repro/t12x.json)). Tomo is the T12 default boot (2s, 4 io +
4 ex on 64–71); Redis on 72. The idle window (same wall time right after each trickle)
shows that most of POST's figure is the 8-thread server's background, not parsing.

| N args | Redis | PRE | POST | PRE ratio | POST ratio | POST idle-window CPU |
|---|---|---|---|---|---|---|
| 50k | 3.21 ms | 38.12 ms | 8.06 ms | 11.86x | **2.51x** | 5.20 ms |
| 100k | 6.71 ms | 130.48 ms | 15.93 ms | 19.43x | **2.37x** | 10.37 ms |
| 200k | 12.88 ms | 331.28 ms | 30.92 ms | 25.72x | **2.40x** | 20.68 ms |

PRE grows quadratically (x3.4 then x2.5 per doubling); POST grows linearly.

**T12b** — audit script unchanged except ports/CPUs/paths; 2M-argument frame in
64 KiB chunks, neighbour pinging on the same io thread (`--thread-mode 2s --ratio 1:1`).
[PRE](docs/respresume/repro/t12b-pre.out), [POST](docs/respresume/repro/t12b-post.out).

| Server | frame CPU | neighbour PINGs | median | max |
|---|---|---|---|---|
| Redis 7.4.10 | 0.10–0.11 s | 406 | 0.01 ms | 26.8–27.6 ms |
| PRE | 0.51 s | 23 | 6.22 ms | 84.43 ms |
| POST | 0.08 s | 408 | **0.02 ms** | 27.92 ms |

The remaining ~28 ms maximum (Redis and POST alike) is the single dispatch of the
completed 2M-argument command. The first PRE T12b attempt failed to boot with a
transient `io_uring init failed: -12` (ENOMEM, environment); it was re-run unchanged.

**NT4 probe** — the audit's cells with the same boot argv (perfio boot: paper rl=0,
uring, 16 shards, atomic 1, key-lb/client-lb on) and memtier argv, server 64–71,
memtier 73–79 (`tools/respresume_probe.py`), on observer builds
(`tools/respresume_observer.py`). Two witnesses per completed command: the audit's
"completed argv discarded at Incomplete" and an independent decode balance (every
successful length-line decode minus argc+1 per completed multibulk: lines decoded more
than once). [PRE](docs/respresume/repro/probe-pre.json),
[POST](docs/respresume/repro/probe-post.json).

| Cell (1M+ commands each) | audit PRE re-parsed/cmd | PRE re-parsed/cmd | **POST re-parsed/cmd** | PRE replayed lines/cmd | **POST replayed lines/cmd** | Incomplete events/cmd PRE | POST |
|---|---|---|---|---|---|---|---|
| 1s MSET 8 keys p8 c512 | 0.20 | 0.13 | **0** | 0.15 | **0** | 0.02 | 0.02 |
| 1s SET 1 KiB p32 c512 | 6.79 | 8.46 | **0** | 16.99 | **0** | 4.27 | 4.29 |
| 2s MSET 8 keys p8 c512 | 2.46 | 8.31 | **0** | 9.27 | **0** | 0.96 | 0.41 |
| 2s SET 1 KiB p32 c512 | 37.55 | 42.07 | **0** | 84.15 | **0** | 21.04 | 21.43 |

Directed-split observer control (one MSET split 9 bytes before its end, both modes):
PRE 2 Incomplete events, 30 arguments discarded, 34 lines decoded twice; POST 2
Incomplete events, 0 discarded, 0 decoded twice. The Incomplete path still fires
millions of times in POST (non-vacuous); it now resumes in O(new bytes).

### Correctness proof list (receipts)

All POST runs use the final binary (`18d24b9d…`) or, where stated, `build/tomokv-asan`
(`make asan` at HEAD: `-O1 -fsanitize=address,undefined`, JE=0). Receipt paths below are
relative to `docs/respresume/`.

**(1) Fragmentation differential** — replies byte-identical to the unsplit run and to
Redis 7.4.10; protocol-error replies and closes identical to Redis.

| Run | Coverage | Result | Receipt |
|---|---|---|---|
| Gate rows `RESP resumable fragment`, 1s/R7 and 2s × epoll/uring | RESP2+RESP3 (HELLO 3); 66 small payloads: 45 command-family groups from the differential suites (strings incl. binary CR/LF/NUL values, lists, sets, zsets, hashes + HTTL, streams + groups, geo, bitmaps/BITFIELD, HLL, scripting/functions, MULTI/EXEC, WATCH, SORT, SSCAN, keyspace/expire, DUMP/RESTORE, CLIENT/CONFIG/ACL/COMMAND, pub/sub, arity errors, RESET); inline; `*0` pipelines; 1-argument frames; 19 protocol errors (bad header at argument positions 0–3, bad count line) each requiring Redis's reply and close; **every byte split** of all 66 (2,302 cut positions per protocol), which includes every cut of the pipelined groups inside the next frame; argument counts 1, 2, 10, 1023, 1024, 1025, 1Mi−1, 1Mi, 1Mi+1, whole and with 16 random cuts at seeds 7/19/20/23; bulk lengths 0, 1, 16383–16385, 32767–32769 (around the 16 KiB initial receive buffer) | 4692 trials, 0 differences, in all 4 boots | `rows/post/*fragment.log` |
| Same corpus, POST observer build | non-vacuity and exact accounting | 14,302 Incomplete multibulk events; 0 completed arguments re-parsed; length lines decoded − completed = 1,780 = exactly the lines decoded before the error in the 19 protocol-error payloads (Σ(a+1)·len·2), i.e. every line decoded once | `proof/frag-observer-post.out` |
| Same corpus over **TLS** (POST, `--tls-port`, both engines and modes) | as above; on io_uring without the 606 close-expecting trials (see findings) | epoll 4692/4692, uring 4086/4086 | `proof/tlsfrag-*.out` |
| Same corpus on **ASAN/UBSAN server**, 2s uring and 1s R7 epoll, with the CPU and neighbour witnesses | as above | 4692/4692 each; 0 sanitizer reports; clean shutdown | `proof/asan-server.out` |
| Serverless unit (PRE-compilable), also under ASAN/UBSAN with leak checks | every split of small frames incl. malformed headers at every argument; counts to 1Mi+1 with seeds 7/19/20/23; bulk boundaries; whole vs split result, argv and error text | PASS (PRE fails only the no-replay witness) | `post/unit.log`, `post/unit-asan.log`, `pre/unit.log` |
| **All 47 differential suites with every target write fragmented** (`tests/respresume_differ_frag.py` through `GATE_DIFFER_DRIVER`; ~1 cut per 32 bytes, up to 64 per write, 0.2 ms gaps; oracle unfragmented) | seeds 7/19/20/23, atomic 0/1; io_uring split and epoll armed-fused | 1.18 M target writes cut into 6.0 M pieces; uring split **376/376**; epoll armed-fused 362/370, the 8 failures being the same epoll infofix assertion as unfragmented and on PRE | `proof/fragdiffer-*.log.gz`, `proof/fragdiffer-summary.txt` |

**(2) Limits close exactly as before** — `tests/respresume_limits.py` sends the same
byte scripts to PRE, POST and Redis in all four boots (1s/2s × uring/epoll): 1 MiB
query-buffer limit crossed by many completed small arguments, by a decoded header's
payload, and by a partial header exactly at the limit; a frame exactly at the limit;
pre-AUTH count 11 and bulk 16385 split across reads; a valid pre-AUTH 4-pair MSET of
16384-byte bulks split mid-payload; a split AUTH; a 1 MiB pre-AUTH inline request.
**PRE and POST are byte-identical with identical close behavior in all 36 case×boot
pairs** (`proof/limits-*.jsonl.gz`). The gate's `NET1 inline + query cap` rows (pre-AUTH
1 MiB inline window, live query cap with a pending 2 MiB bulk, queued MULTI argv) pass
on both, with identical output (`proof/existing-rows/*-gate-netcap-*.txt`).

**(3) Partial frame pending across migration**
- `build/respresume-migration` (production code, no listener): a frame suspended with
  one completed argument, that argument's header then poisoned, moved through the real
  client-LB request/drain/install path and through FLIP prepare/commit, then completed
  by the destination's parser: 2s ordinary, 1s ordinary, 1s R7 × client-LB, FLIP —
  6/6 PASS with the exact reply (a replay would hit the poison) (`post/migration.log`).
- `tests/respresume_flip.py` (live, 2s, `--client-lb 0 --flip-auto 0`): 48 clients parked
  in every partial shape (count line, header, decoded header, mid-payload) plus 3 frames
  above 1 Mi arguments, then `FLIP 7 1` and back to `6 2`. POST uring: grow 34
  transfers with 26 parked frames changing owner (1 of them above 1 Mi), shrink 38 / 30
  (3); POST epoll: grow 33 / 25 (0), shrink 30 / 22 (2); every reply and stored value
  exact; also on the ASAN server (21–26 moved, 0 reports) and on PRE
  (`proof/flip-*.out`).
- Migration **preserves** the frontier instead of resetting it (the spec text lists
  migration among reset paths). No migration path consumes, discards or replaces the
  receive buffer: FLIP, client-LB and R7 adoption move the same `Client` (buffer and
  offset frontier together) across the release/acquire `ifid_thread_` edge; rollback
  only swaps the fd; TLS clients are refused transfer (`client_transfer_ready`).
  Resetting would be safe but would re-parse the completed prefix once per move,
  against the lane goal; the poisoned-header witnesses fail if anything re-parses.
  `docs/respresume/lifecycle.md` lists every consume/discard/owner site
  (`lifecycle-sites.txt`, 82 sites).

**(4) Suites**

| Battery | PRE | POST | Receipt |
|---|---|---|---|
| `tests/differ_gate.sh` focused proof, 47 suites × seeds 7/19/20/23 × atomic 0/1, split, io_uring | not run | **376/376** | `proof/differ-post-uring-split.log.gz` |
| same, armed-fused (`--read-local 1`; lane fired: 983 hits), io_uring | not run | **370/370** (sort skipped by design) | `proof/differ-post-uring-armed-fused.log.gz` |
| same, split, epoll | infofix 0/8 | 368/376: the 8 failures are infofix | `proof/differ-post-epoll-split.log.gz`, `proof/differ-pre-infofix-epoll-split.log.gz` |
| same, armed-fused, epoll | infofix 0/8 | 362/370: the 8 failures are infofix | `proof/differ-post-epoll-armed-fused.log.gz` |
| `tests/respcompat.py` (gate row: 1s/2s × atomic 0/1 vs Redis) | ok | ok | `proof/existing-rows/` |
| `tests/netio.py` (gate rows `epoll directed correctness (1s/2s)`, uring and epoll) | ok | ok | `proof/existing-rows/` |
| TLS battery (17 gate rows: auth matrix, kTLS, KeyUpdate, torn records, pipeline, shutdown) | 17 ok | 17 ok | `proof/existing-rows/{pre,post}-ledger.tsv` |
| netcap (4 rows) | 4 ok | 4 ok | same |

The infofix legs fail identically on PRE and POST under `--net-io epoll` only, at the
same assertion (`instantaneous_input_kbps > 0`, `tests/differ.py:6533`):
`epoll_recv` never adds to `net_input_bytes` (the io_uring paths do), so the meter
stays 0.00. Pre-existing, not a framing difference.

**(5) Builds and harness**
- `make all` (release, both namespaces) — 0 warnings; `make -q all` = 0 at HEAD.
- Every `job_production_units` target (31 units + `mdbqsbr-live-arms`, incl.
  `build/respresume-unit`, `build/respresume-migration`): `make -k` exit 0
  (`post/production-unit-build.log.gz`).
- `make asan`: exit 0.
- `python3 tests/gates_test.py` (pinned to 64–79): 66 tests OK in 86.5 s (`post/gates-test.log`).

### Complete-frame fast path (objdump of build/tomokv)

Full per-clone tables: [docs/respresume/fastpath.md](docs/respresume/fastpath.md)
(every `resp_parse_t`, `parse_and_dispatch` and `r7_parse_and_dispatch` instantiation and
IPA clone, PRE and POST addresses and sizes); every dispatcher window's instruction list:
[fastpath.json](docs/respresume/fastpath.json); inventories and GDB traces:
`docs/respresume/{pre,post}/`. Method:

1. **Parser bodies** — `tools/respresume_trace.py` copies each clone's bytes out of the
   production ELF into a fixture and single-steps a complete `GET k` / `SET k v` frame
   under GDB (no server; leaving the body except by `ret` fails the trace).
2. **Callers** — `tools/respresume_fastpath.py` takes, in every dispatcher body, the
   call-free control-flow path from the `op->rbuf_off` store (Op offset 24) to the call of
   the default-limit parser, constrained through the `'*'` compare (a multibulk frame
   with bytes available). Any other outcome (resume, inline, pre-AUTH or configured
   limits) reaches a different call, so this path is exactly the complete authenticated
   route. Post-call result tests are identical PRE/POST in all 26 bodies (jump offsets
   only).

| Family (PRE -> POST) | Clones | Bytes | Executed GET | Executed SET | Stores on path |
|---|---|---|---|---|---|
| `resp_parse_t<false>` -> `<false, true>`, tomo (.isra) | 4 bodies + 4 cold | 998 -> 1086 each | **182 -> 174** | **238 -> 229** | 20 -> 19 / 24 -> 23 |
| same, tomo_db0 | 4 + 4 | 1058 -> 1097 | **189 -> 179** | **248 -> 237** | 22 -> 21 / 27 -> 26 |
| `resp_parse_t<true>` -> `<true, true>` (pre-AUTH / configured limit), tomo | 1 | 1073 -> 1216 | 194 -> 185 | 252 -> 242 | 22 -> 21 / 26 -> 25 |
| same, tomo_db0 | 1 | 1150 -> 1232 | 203 -> 198 | 267 -> 262 | 23 -> 22 / 28 -> 27 |
| dispatcher selection window (26 bodies: ordinary 2s/1s/batch/split-local and R7, both namespaces) | 26 bodies + 10 cold | −25..+342 per body | 15–17 -> 21–23 | same | 1 -> 1 (`rbuf_off` store) |
| **window + parser, per dispatcher clone** | 26 | | **197–206 -> 195–202 (−1..−6)** | **253–265 -> 250–260 (−2..−7)** | parser −1 |

What the caller window adds (identical in all 26): `mov 0x4c(%rClient),%e; test; js`
(the single predicted-false pending test on the existing cursor word) and
`lea 0x60(%rClient),%r9` (frontier address argument, no memory access), plus 0–3
register moves in the batch/R7 clones. What the parser loses: the redundant
`buf[pos] != '*'` inline test and the stack-protector prologue/epilogue. No complete-frame
path in any clone grows; no store is added.

**NT4.3 (stack canary):** removing the stateless inline arm from the resumable
instantiations removes the address-taken `uint32_t scanned` local, and with it the
canary: `resp_parse_t` canary loads **10 -> 0** and `__stack_chk_fail` references
**26 -> 0** (all 18 clone parts). Dispatcher canary loads are unchanged (38 across the
`parse_and_dispatch` inventory, 12 across `r7_parse_and_dispatch`), as no address-taken
local was added. Removing the reset-to-start logic alone would not have
removed it; the inline arm is the address-taken local, and the resumable instantiations
must not contain a stateless (replaying) inline fallback anyway.

### Gate rows

**DQ = +12, DF = +12** (EXPECT_QUICK 625 -> 637, EXPECT_FULL 642 -> 654; `EXPECT_*`
deliberately not edited). Twelve rows `RESP resumable {fragment,cpu,neighbour}
({1s,2s}, {epoll,uring})`, collected immediately after `RESP protocol error
compatibility` and before `generated Redis 7.4 ACL categories`, above the quick-tier
exit, so they count in both tiers. `tests/gate.sh`: job dispatch line 906, plan entries
1046–1048, `job_respresume` 1846–1899, dependency (`release production_units`) 3519,
collection 3640–3645 (quick exit at 3770). Boots: 1s = `--thread-mode fused
--read-local 1 --reorder 1` (the **R7** parser), 2s = `--ratio 6:2 --thread-mode 2s`
(ordinary parser); 16 shards, `--client-lb 0 --key-lb 0 --enable-debug-command yes`.

| Row | Checks | POST (median) | PRE (median) | Bound | Runtime |
|---|---|---|---|---|---|
| fragment | serverless no-replay/corpus unit, production migration unit, wire differential vs unsplit and Redis (RESP2+RESP3, every byte split of 66 payloads, 1..1Mi+1-argument frames at seeds 7/19/20/23, bulk 0..32769 boundaries, protocol errors with close), plus the CPU work witness on the candidate | 4692 trials byte-identical; work 0.02–0.05 s | 4692 identical (PRE is correct but quadratic); work **0.69–0.72 s** | 0.2 s | 14.6–16.8 s |
| cpu | 3 trickles of a 400k-argument frame (2 KiB, 0.5 ms), server utime+stime | 0.03–0.05 s | **0.69–0.72 s** | 0.2 s | 2.6 s |
| neighbour | 2M-argument frame in 64 KiB chunks; PING median on a proven same-owner connection | 0.021–0.022 ms | **5.7–8.7 ms** | 1 ms | 0.8–0.9 s |

Bounds sit about 3x (CPU) and 5x/45x (neighbour) from PRE and POST respectively, so a
quiet gate box cannot false-fail while PRE fails decisively. Receipts (final run on the
committed test code; an earlier identical-verdict run is in history at `19c11de76`):
[PRE ledger, 12 FAIL](docs/respresume/rows/pre/ledger.tsv) and per-row logs in
`docs/respresume/rows/pre/`; [POST ledger, 12 ok](docs/respresume/rows/post/ledger.tsv)
and `docs/respresume/rows/post/`. Run: `GATE_ONLY_JOBS='respresume-…(12)'
REDIS74_ROOT=/home/user/Projects/redis74 taskset -c 64-79 tests/gate.sh quick
--server-cores 64-71 --load-cores 72-79 --ports 25400-25449 --candidate-binary <bin>`.

### Findings outside this lane (pre-existing; PRE and POST identical; not fixed here)

| # | Finding | Evidence |
|---|---|---|
| F1 | `--net-io epoll` never accounts received bytes (`epoll_recv` commits reads without adding to `net_input_bytes`; the io_uring completions do), so `total_net_input_bytes` / `instantaneous_input_kbps` stay 0 and the differential `infofix` suite fails 8/8 legs in both epoll geometries. | `proof/differ-pre-infofix-epoll-*.log.gz` vs `proof/differ-post-epoll-*.log.gz`; `src/core/io_loop.h:2411,2592` vs `epoll_recv` |
| F2 | TLS on io_uring does not close a connection that must close after its reply (protocol error, QUIT) while the peer stays silent: the reply arrives, the socket stays open (>10 s). TLS on epoll and plain TCP on both engines close at once. | `proof/tls-close-after-reply.out` (+ `.py`) |
| F3 | Pre-AUTH limit errors say `invalid multibulk length` / `invalid bulk length`; Redis 7.4.10 says `Protocol error: unauthenticated multibulk length` / `unauthenticated bulk length`. Same close behavior. | `proof/limits-*.jsonl.gz` (count 11, bulk 16385 cases) |
| F4 | The 1 MiB query-buffer limit counts the whole pending frame (`rlen - rpos`), so a frame whose already-complete arguments pass 1 MiB is closed; Redis counts only unparsed bytes and keeps such a connection. (With the frontier the parsed prefix is now known; changing the accounting is a separate decision.) | `proof/limits-*.jsonl.gz` ("many completed args", "partial header crosses limit") |
| F5 | `SCAN 0` on an empty keyspace returns a nonzero shard cursor (valid SCAN semantics, not byte-comparable with Redis); the inherited corpus used it and could never pass. | gate row fix in `19c11de76` |
| F6 | In 2s the parse pass re-enters an incomplete tail after every retire pass even without new bytes: 21 Incomplete events per command on SET 1 KiB p32 c512 (PRE and POST alike). POST makes each re-entry O(1) (no argument is re-parsed), but the ROB slot reset and call remain; skipping the re-entry when `rlen` is unchanged since the last Incomplete is a possible follow-up. | `repro/probe-*.json` |

### Measurement request (mainline, quiet box)

No performance claim is made here. Please run the performance merit on a quiet box:
the generic headline/smoke cells plus the eight lane cells in
[tests/respresume_cells.txt](tests/respresume_cells.txt) (accepted by `abbagate.read_cells`):
8-key MSET p8 c512 and SET 1 KiB p32 c512, 1s and 2s, rl=0 and rl=1, atomic 1.

| Arm | Path | SHA-256 |
|---|---|---|
| POST (this branch HEAD, `make all`) | `/home/user/Projects/cx-respresume/build/tomokv` | `18d24b9db8ec7267c51a8de3b6bef663100d6e7ba152b2ed73d41b1012417c9e` |
| same bytes, named copy | `/home/user/Projects/cx-respresume/build/tomokv-respresume-post` | same |
| PRE reference (`991d48f65`, built from `git archive` in `build/rr-pre-tree`) | `/home/user/Projects/cx-respresume/build/tomokv-respresume-pre` | `3fd923f6ca350bdac28090c89713fa73bc270e84b7c0a50b8061cae55c46a004` |
| optional layout control PAD-A (POST bytes; both `resp_suspend` entries patched to return Incomplete without saving, so every partial frame is re-parsed from its array header as in PRE) | `/home/user/Projects/cx-respresume/build/tomokv-respresume-pad-a` | `860b1f69fce48d724d370ef1b8990e99d995ef17fd8ebd65d05cb0dd603293d3` |

`make -q all` returns 0 for `build/tomokv` at HEAD. PAD-A receipt:
[docs/respresume/pad-a.json](docs/respresume/pad-a.json) (`tools/respresume_pad.py`).
Expected direction only (not measured here): SET 1 KiB p32 (both modes) and 2s MSET p8,
where PRE re-parsed 8–42 completed arguments per command, should gain; complete-frame
cells should be flat or marginally better (fewer instructions per parse, no new store).
POST vs PAD-A isolates the retained frontier from code-placement effects.

### Where everything is

| Path | Contents |
|---|---|
| `docs/respresume/audit/` | the round-4 NT4.2 scripts, outputs and counter patch, as supplied |
| `docs/respresume/repro/` | T12, T12b (audit scripts), T12x (ns), NT4 probe — PRE and POST |
| `docs/respresume/rows/{pre,post}/` | the twelve new gate rows: ledgers and per-row witness logs |
| `docs/respresume/proof/` | differential (plain and fragmented), limits, FLIP, TLS, ASAN, existing gate rows, PAD-A sanity |
| `docs/respresume/{pre,post}/` | binary hashes, build logs, symbol lists, objdump inventories, GDB traces, unit / ASAN-unit / migration / production-unit receipts |
| `docs/respresume/fastpath.{md,json}` | per-clone fast-path tables and every dispatcher window's instructions |
| `docs/respresume/lifecycle.md`, `lifecycle-sites.txt` | frontier lifetime audit: every consume / discard / owner-change site |
| `tests/respresume*.py`, `tests/respresume_{unit,migration}.cc` | witnesses (gate drivers, FLIP, limits, fragmented differ driver, units) |
| `tools/respresume_*` | reproduction, observer, probe, inventory, trace, fast-path and PAD-A tools |

The ad-hoc runners behind the standalone runs (`rr-pair.sh`: tomo on 64–71 + Redis on
72 + command on 73–79; `rr-limits.sh`; `rr-differ-batch.sh`; `rr-asan-witness.sh`) are
copied verbatim to `docs/respresume/proof/runners/`; they ran from `build/`.
