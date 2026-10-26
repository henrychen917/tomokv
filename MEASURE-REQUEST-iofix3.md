# WB4.1 completion-derived IO parking

## iofix3

Worktree `/home/user/Projects/cx-iofix3`, branch `cx-iofix3`, baseline
`3700b51d7fb3074f32330dd81f138efbf1ddd980`. No push. Merit is pending; this
lane makes no throughput claim.

The candidate reapplies `762c3d5bc`'s grace window. Split IO learns the largest
completion interval in a busy tenure from the existing pass clock cut. Intervals
spanning a park are excluded. Pending FIFO entries keep the loop awake only
while the completion-derived grace remains active or a bounded deferral counter
advances. The existing FIFO pins, wake arm/recheck, latency policy, completion /
byte / half clauses and load detector are unchanged. Both ordinary and generated
R7 envelopes carry the same change. The window is stack-local; all eight locked
object layouts retain their baseline sizes.

`TOMO_WB_IDLE_MULTIPLIER` is a build-time measurement override, initially 2.
POST arms use 2, 4 and 8. The maintainer keeps the smallest multiplier whose two
2s multi-key cells are within the measured PRE noise band, hardcodes it, and
deletes the other arms and this override. A few pending-FIFO parks under load
are an event-count observation, not an automatic rejection.

### Requested merit

Use [the exact 20-cell list](docs/iofix3/merit-cells.txt): `mk2g_a1_p8` and
`mk2s_a1_p8` copied from `/home/user/Projects/bins/mk-merit-cells.txt`; 2s
GET/SET at p1 and p32 (`h53`, `h54`, `h21`, `h22`); and all 14 generic cells
from `tests/wbland_merit_cells.txt`. Use the gate's own ABBA instrument on the
maintainer's quiet-box geometry, with matched offered load and identical-arm
noise controls. Compare PRE with each POST arm and with PAD-A. Rate decides;
record cycles/op, instructions/op and IPC to explain it, plus the ordinary
depth-1 latency scores. The correctness geometry below is not a merit receipt.

**PAD-A is kind A, a behaviour twin:** PRE's positive-work result for every
deferred FIFO visit, at POST2's exact text/ELF layout. The guarded existing
patcher changes only 104 work-result sites (312 bytes); all sections, symbols,
addresses and sizes remain equal. POST grace bookkeeping remains in the twin,
but positive work prevents it from causing a pending-FIFO park. It must fail
the restored idle row for the same reason as PRE.

### Validation record

Correctness uses only CPUs 64–79: server/oracle 64–71, clients 72–79; builds
use `taskset -c 64-79 make -j16`. Ports are 48800–48899. Gate jobs use the
standard 16-shard 6:2 split geometry and eight-worker fused geometry. Every
selected gate run is PARTIAL: no full iteration, ABBA, NIC or source receipt.

The restored row is collected at `tests/gate.sh:5359`, before the quick-tier
exit at line 5626: **DQ=+1, DF=+1**.
`EXPECT_QUICK=798` and `EXPECT_FULL=815` remain untouched. The maintainer must
set **799 / 816**. The fixture and declared source inventory both contain 816
rows; [the inventory](docs/iofix3/row-inventory.json) records the collector and
quick-exit source lines.

### Frozen release arms

All paths are relative to this worktree; binaries remain in `build/` for the
maintainer. SHA-256 covers the entire ELF, including debug information.

| Arm | Binary | .text bytes | SHA-256 |
|---|---|---:|---|
| pre | `build/tomokv-iofix3-pre` | 8,279,287 | `661117595196c46fc72d9c613b10d60b96336b6fe1cc65c56b7d32477cb42193` |
| post2 | `build/tomokv-iofix3-post2` | 8,286,743 | `dd1699ed4dc953cac8f24e9d47c8c5e43ef4b280e158f278c496c5193ab871d4` |
| post4 | `build/tomokv-iofix3-post4` | 8,286,743 | `09a015c68f19291db9ba70eb4023232676373fee5e085ae752336a7e6583b890` |
| post8 | `build/tomokv-iofix3-post8` | 8,286,743 | `8227cb0cfaf1da6291fb773511fb461d5f2e0e99be5bda4d40b37c0ff9681702` |
| pad-a | `build/tomokv-iofix3-pad-a` | 8,286,743 | `3895bc786a8029bae7eaebc7cbad437cc00108f6e3d894477578964c4dd40ab4` |

PRE was built from a `git archive 3700b51d7` copy of `src`, `third_party` and
`Makefile` under `build/iofix3`. POST2 uses ordinary `make -j16 all`; POST4 and
POST8 use separate `BUILD_ROOT=build/iofix3/postN` trees and the ordinary flags
`-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, adding only
`-DTOMO_WB_IDLE_MULTIPLIER=N`. All builds run under `taskset -c 64-79`.
`tools/iofix3_artifacts.py pad` constructs the guarded PAD-A from frozen POST2.
The [artifact manifest](docs/iofix3/artifacts.json) and
[PAD receipt](docs/iofix3/pad-a-final.json) retain the details.

Each POST adds 7,456 text bytes to PRE. All three POSTs and PAD-A have identical
allocated-section layouts and symbol addresses/sizes; POST4 and POST8 each
change 280 text bytes relative to POST2. PAD-A changes only its 312 documented
bytes. Thus the one PAD-A also matches the other POST arms' allocated layout.
See [the layout comparison](docs/iofix3/arm-layouts.json).

### Main-command identity

The unchanged `tests/reorder_noop.py Binary(literal_pools=True)` normalizer
compares opcode encodings, operands and referenced literal pools; the existing
`tools/iofix_identity.py` hot selector covers GET, SET, MGET and MSET.
All **142 selected linked groups are identical to PRE in each arm**:
[POST2](docs/iofix3/identity-post2-final/summary.json),
[POST4](docs/iofix3/identity-post4/summary.json),
[POST8](docs/iofix3/identity-post8/summary.json). All-group inventories and
normalized changed-body diffs are retained alongside those summaries.

This is not whole-server identity. Of 9,427 groups, 131 change: 104 writeback
flush bodies, 17 run loops, one fused sweep, and nine compiler/link propagation
groups outside the selected hot commands. The
[classified diffs](docs/iofix3/identity-post2/changed-bodies-explained.json.gz)
retain these exceptions. The gate's separate R7 FIFO-control audit also passes
312/312 bodies and its missing-body/opcode negative controls. The eight layout
locks remain 336/1984/1408/1440/944/192/144/624 bytes.

### Idle-battery CPU

WB4.1 passes all four mode/engine legs on every POST. Each leg exercises policy
0, policy 1 at S16/D3, S0/D3 and S16/D0; every leg witnesses a real remote LPOS
and compares exact replies against Redis 7.4.10. PRE fails the restored row in
all four legs because policy 1 busy-spins. Missing LPOS/deferral windows fail;
no tolerance or skip was added.

The table is **IO-thread CPU milliseconds**, default policy 1/S16/D3, over 16
LPOS waits. Wall intervals are 426.4–430.5 ms. This is idle CPU evidence, not
throughput. All 64 policy/mode/engine observations, including owner identities,
wall time and the independent second-busy-thread check, are in
[idle-cpu.json](docs/iofix3/idle-cpu.json).

| Mode / engine | PRE | POST2 | POST4 | POST8 |
|---|---:|---:|---:|---:|
| 1s / epoll | 426.717 | 0.514 | 0.589 | 0.495 |
| 1s / uring | 426.457 | 0.686 | 0.527 | 0.527 |
| 2s / epoll | 426.617 | 0.433 | 0.477 | 0.467 |
| 2s / uring | 426.511 | 0.766 | 0.459 | 0.473 |

PAD-A also fails the restored row in all four legs for the same busy-spin
reason as PRE, with LPOS CPU, deferral and exact oracle-reply witnesses present.
[The negative-control proof](docs/iofix3/pad-a-idle-proof.json) is from the
completed gate run, not an earlier port-preflight failure.

### Fixed-count park probe

The unchanged wave5b workload uses 64 connections, depth 8 and 64-byte values.
Each of three repeats sends **131,072 requests per arm/cell**. The separate
instrumented copies count events between READY/GO and DONE/STOP barriers; they
are not the release merit binaries. PRE and POST arm order alternates by repeat.
All 36 runs completed, checked replies and observed visits/deferrals/sends/
completions. Only CPUs 64–79 and port 48820 were used.

| Arm | Cell | Pending-FIFO parks, repeats 1/2/3 | Pooled parks/request |
|---|---|---|---:|
| PRE | MGET a1 | 0/0/0 | 0.000000000 |
| PRE | MGET a0 | 0/0/0 | 0.000000000 |
| PRE | MSET a1 | 0/0/0 | 0.000000000 |
| POST2 | MGET a1 | 2/3/3 | 0.000020345 |
| POST2 | MGET a0 | 5/4/5 | 0.000035604 |
| POST2 | MSET a1 | 15/96/28 | 0.000353495 |
| POST4 | MGET a1 | 1/3/7 | 0.000027974 |
| POST4 | MGET a0 | 0/3/5 | 0.000020345 |
| POST4 | MSET a1 | 32/53/36 | 0.000307719 |
| POST8 | MGET a1 | 3/1/3 | 0.000017802 |
| POST8 | MGET a0 | 3/1/3 | 0.000017802 |
| POST8 | MSET a1 | 0/15/32 | 0.000119527 |

Each repeat's parks/request is its count divided by 131,072. The pooled column
uses all 393,216 requests. The [machine-readable summary](docs/iofix3/fixed-count-summary.json)
also records each individual fraction and the instrumented/client SHA-256s.
[Raw results](docs/iofix3/probe/fixed-count/) retain before/after per-owner
counters, exact launch arguments and server logs; instrumentation diffs are in
[the probe directory](docs/iofix3/probe/). No ordering or throughput conclusion
is drawn from these event counts.

### Remaining correctness

The remaining engine/mode correctness matrix is still running. Its completed
results, exact job ledger and any NOT RUN items will replace this paragraph
before delivery. The first gate attempt's failures and resolving reruns are
preserved, not counted as passes.
