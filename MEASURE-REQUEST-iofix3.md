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

The restored row is collected before the quick-tier exit: DQ=+1, DF=+1.
`EXPECT_QUICK=798` and `EXPECT_FULL=815` remain untouched. The maintainer must
set **799 / 816**. The fixture and declared source inventory both contain 816
rows; [the inventory](docs/iofix3/row-inventory.json) records the collector and
quick-exit source lines.

Final arm hashes, fixed-count park counts, idle CPU, correctness outcomes and
any NOT RUN items are recorded below when validation completes.
