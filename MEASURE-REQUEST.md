# cx-lbstall: bounded load-balancer drains

**Maintainer execution request; no server, load generator, benchmark, or gate was run by this lane.**
Worktree: `/home/user/Projects/cx-lbstall`; branch: `cx-lbstall`.
PRE: `118487882` (v3 `5d567adf5` plus gate-only commits).
Implementation: `ad1542013`, followed by the verification/diagnostic commit containing this request.

Busy client migration now refuses at its first failed readiness check. A ready client
waiting for destination preparation, or a shard drain waiting for IO/executor ACKs,
is refused by the third IO control tail. The five-second deadline remains the final guard.
Root cause and the stack3 comparison: [LBSTALL.md](LBSTALL.md).

## Binaries

All filenames below are under `/home/user/Projects/cx-lbstall/build/`.
GCC `13.3.0-6ubuntu2~24.04.1`, release `-std=c++20 -O2 -g -Wall -Wextra -march=native
-pthread`, jemalloc, and the Makefile's documented per-TU inlining locks. All builds
used `taskset -c 112-127`, `make -j8`.

| Arm | File | .text bytes | SHA256 |
| --- | --- | ---: | --- |
| PRE | `tomokv-lbstall-pre` | 3793379 | `4d138a7bd1e22bc0ae98f49cfddb21d83a691cab966bb4659893d8bd50fa9778` |
| POST | `tomokv-lbstall` | 3798131 | `a9642cdd5be1fc53fb2d13ba7cb98c24ee737efd0954000730dead7ef963a5ee` |
| PAD-A | `tomokv-lbstall-pad` | 3798131 | `6a95b8faff02a775f58c82f6e8f470325c7aa9ce387f864b23fe348a0549528c` |
| DEBUG-POST | `tomokv-lbstall-debug` | 3799613 | `9f39c9944aa2e35af68b0e793f1e79bbdaccabd321ba526420b9861cbf9387af` |
| DEBUG-PRE | `tomokv-lbstall-debug-pre` | 3799085 | `fd29b87a488704eff027ce66a3f99422c0b3e885bd28ddd143e7343c40ff4042` |

Release POST grows .text by **4,752 bytes**. PAD is **kind (A), behaviour twin**:
PRE's unbounded busy-drain policy with POST's exact text size, addresses, and state layout.
It is made by replacing only the out-of-line `lb_refuse_stalled` entry with
`xor eax,eax; ret` in a COPY of POST, preserving its CET landing instruction. The only
three differing file bytes are at offsets 3822692–3822694; every section header and all
other bytes match. `build/lbstall-proof/pad.json` records the patch.

Control scope: PAD restores the old wait-until-timeout behavior for ordinary tail-cell
clients. It retains POST's cold safety mutexes, polling cadence, cooldown scaffolding,
and INFO schema; it is not a reconstruction of every PRE instruction. Its job is to
show POST moving while the same-layout unbounded policy still stalls. The identical patch
on the unit executable FAILS the bounded-arrivals assertion, as does the frozen original
PRE. No PAD or diagnostic server was started. No kind (B) arm is requested.

DEBUG-POST defines `TOMO_LB_STALL_DEBUG`. DEBUG-PRE additionally defines
`TOMO_LB_STALL_OBSERVE_ONLY`, disabling new refusals while recording their reasons and
pending duration. These two binaries are diagnostic controls only; use release arms for
rate/IPC judgments. Keep their raw INFO snapshots with the generator logs.

## 1. Primary open-loop reproduction

Use mainline's existing tail-cell boot, population, pinning, and frozen tailgen binary.
Record its digest and each exact command in MEASURE-RESULT. Server: 8 cores as in the
original tail run, `--shards 256 --thread-mode 1s --atomic 1 --overlap 1 --read-local 0`.
Populate 2,000,000 `memtier-N` keys with 64-byte values and 2,048 `blocker:memtier-N`
keys with 256 KiB values using the gate's population method.

The tool's published t01 invocation, for the maintainer to run against each selected arm:

```sh
taskset -c 84-111 /home/user/Projects/cx-tailgen/build/tailgen \
  --host 127.0.0.1 --port 6379 \
  --rate 717000 --threads 16 --conns 32 --cores 84-111 \
  --mix 'GET:8,BITCOUNT:2' --spacing poisson --seed 1 \
  --short-keys 'memtier-{1..2000000}' \
  --long-keys 'blocker:memtier-{1..2048}' \
  --warmup 3 --duration 20 --max-outstanding 64
```

`--conns` is per worker: 16 × 32 = 512 connections. The outstanding threshold is an
observer, not a sending cap. Save both stdout JSON and stderr for every run.
Use the original endpoint/CPU mapping if it differs from this published example;
all arms must use the same recorded geometry.

| Cells | Arms and order | Required variants |
| --- | --- | --- |
| Main P0 cell at 717,000/s | PRE, POST, POST, PRE; 3 ABBA blocks | reorder=0 and reorder=1; both LBs on |
| Layout/behavior control | PRE, PAD-A, PAD-A, PRE; then PAD-A, POST, POST, PAD-A | Same two reorder settings, both LBs on |
| LB splits at 717,000/s | PRE/POST ABBA | client-lb=0 only; key-lb=0 only; both=0, reorder=0/1 |
| Higher-load check at 900,000/s | PRE/POST ABBA | both LBs on and both off; reorder=0/1; retain overload witnesses |
| Split mode | PRE/POST ABBA | t03/t04 geometry, its calibrated offered load, client/key LB on |
| Armed read-local | PRE/POST ABBA | t05/t06 geometry, its calibrated offered load, both LBs on |
| Diagnostic attribution | DEBUG-PRE/DEBUG-POST paired windows | 717,000/s, client/key LB on, reorder=0/1 |

Use matched seeds within each block, fresh arms/populations as the existing instrument
requires, and retain warmup/measurement boundaries. Diagnostic polling is outside the
release measurements; take INFO before/after each diagnostic window. Run more windows
if PRE/PAD does not expose the known episode: an unarmed control cannot prove its removal.

**Deciding numbers:** POST at 717,000/s must eliminate the recurring ~5 s plateau and
any-connection-over-64 episodes under both reorder settings, return short GET p99.9
near the matched client-lb-off control, and preserve long BITCOUNT p99.9 (no starvation).
PRE and PAD must still expose the defect for a causal control. A failed/missing episode
in a finite PRE control is inconclusive; it is not a POST pass. Preserve p50, p99, p99.9,
p99.99, maximum, per-connection maximum outstanding, over-64 interval fraction, all
short/long counts, unsent bytes, pacing lag, final backlog, and drain duration. At the
higher rung distinguish global overload from one client's LB hold using those witnesses.

Diagnostic expectations: DEBUG-PRE `tomokv_lbstall_pipeline` and `parked_passes` advance
while a move stays pending, with `pending_ns_max` near the guard; DEBUG-POST records
immediate pipeline (or another real predicate) refusals. `pending_ns_max` is publication
to refusal/observation; `parked_ns_max` is first-to-latest observed park, not end-to-end
latency. Normal builds count successful refusals; DEBUG-PRE counts blocked observations.
Keep existing key/client move and refusal counters: a busy candidate may be declined,
and ready candidates must still be able to move.

## 2. Gate and throughput protection

Mainline runs `tests/gate.sh iteration` against POST with its own **--shards 16**,
`GATE_RATIO`, and `GATE_CORES` geometry, including both 1s/2s boot and armed-read-local
legs. Open-loop tail reproduction above uses 256 shards deliberately; do not substitute
one geometry for the other. The lane did not run any gate or boot test.

Use the gate's own ABBA instrument and existing calibrated load floors for PRE vs POST:
`h01-h64`, `m01-m96`, `x01-x06`, `c01-c04`, `a01-a04`, `t01-t06` from
`tests/headline_cells.txt` (180 cells). This covers GET/SET p1/p32; MGET/MSET p1/p8/p32;
both modes and reorder/read-local/overlap combinations; mixed, connection-count, atomic,
and tail controls. Keep all required arm instrumentation and engagement witnesses.
For changed cells, add POST/PAD ABBA before attributing a gain to the refusal mechanism.

Verdict: no main-command regression at matched offered load under the existing gate's
acceptance rule. Record rate, cycles/op, instructions/op, and IPC per arm/cell; rate and
tail at the matched offered load decide, and both instruction count and IPC explain.
A larger-than-2% identical-arm spread requires resolving contention or a bug, not widening
thresholds. No throughput or live-latency improvement is claimed from local units.

## 3. Completed offline verification

| Check | PRE | POST |
| --- | --- | --- |
| Continuous-arrival, empty-ROB pending-IFID witness | Fails four-pass bound | Refuses first busy tail; same frames replied exactly once |
| Ready source, destination never ACKs | Old deadline guard | Exact third-tail refusal |
| Shard publication/executor drain | Old deadline guard | Shared three-tail budget; ownership/RYOW checked in 1s and 2s |
| Native selections | Both extra probes below fail | 62/64 pass; identical two pre-existing failures |
| Full core TSAN + waits + store-flags | Not claimed | 10/10 pass |
| Debug park/INFO unit | Not applicable | PASS with actual parked-byte and predicate assertions |
| Negative control patched from POST unit | Not applicable | FAILS bounded-arrivals assertion as required |
| Live p99.9 / maximum / cycles/op | Maintainer's prior evidence in LBSTALL-BRIEF.md | Pending mainline measurement |

All units ran on 112–127; the four owner-arena selections ran on **112–119**, as their
fixture requires exactly eight allowed CPUs. The native core unit uses ASAN/UBSAN.
The separate core TSAN build instruments the test TU and its production dependencies,
without jemalloc, using `-O1 -fsanitize=thread -fno-omit-frame-pointer -no-pie` and
`TSAN_OPTIONS=halt_on_error=1:exitcode=66`, `setarch x86_64 -R`.
Raw records: `build/lbstall-proof/final-native-units.json`, `final-tsan-units.json`,
`debug-unit.log`, `pre-negative.log`, and `unit-pad-negative.log`.

**Reported correctness defects, independently reproduced on frozen PRE:**
`atomic-survivors-unit post_apply_probe` leaves `BW` after two successful APPENDs that
both report 2; `netcmd-unit collection-oom` reports OPEN F05, a failed multi-field HSET
retaining a changed prefix and old TTL. Both are existing probes outside the green gate.
See `pre-post-apply-probe.log` and `pre-collection-oom.log`; no expectation was weakened.

All eight size locks are equal in PRE/POST:
`Op 336`, `Client 1984`, `ThreadCtx 1408`, `Shard 1440`, `FlatStore 944`,
`Rob<64> 192`, `AtomicEntry 144`, `Config 624`.
Also unchanged: `ExLoop 5856`, `IoLoop 8384`, `Server 105088`.
The optional LB policy grows **80 → 8448 bytes per server** for per-owner cold watch
lines and counters. Both LB knobs at zero allocate none of it, covered by the unit.

**Strict byte-proof limit:** the comparison of 363 selected operation bodies finds
359 raw matches, **361/363** matches after address-relocation normalization. Callee
and constant identities are compared, not discarded. Parser, executor, reply, and
GET/SET/MGET/MSET bodies match, including the runtime reorder 0/1 branches. Two names
alias one TLS read-local conflict helper: two `cmp` operand encodings commute without
changing size, accesses, instruction count, or equality branches. These are real byte
differences; the checker returns failure. The changed IO control tail also has a
different prologue and is outside the operation-body comparison. See LBSTALL.md and
`build/lbstall-proof/hot-bodies.{json,txt}`, `encoding-exceptions.json`,
`lb-control-bodies.txt`. This is not a claim of full stable-path byte identity.

Reproduce the comparison without executing a server:

```sh
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare \
  build/lbstall-proof/pre-objects build/src build/lbstall-proof/hot-bodies.json
```

No gate row was added or retired. The existing route row at `tests/gate.sh:1233` gains
the LB cases and remains above the quick exit at line 2747 (collected at line 2640).
Counts stay **419 quick / 436 full**; EXPECT_QUICK and EXPECT_FULL were not edited.

Append measurements and the decision to `MEASURE-RESULT` in this worktree.
