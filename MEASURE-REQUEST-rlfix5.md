## rlfix5

PRE is `ea48a6b272` (wave 14); branch `cx-rlfix5`. CPUs 24–31 only,
ports 21500–21599, `LC_ALL=C`. No performance measurements or push.

The PRE gate jobs `rlfix5-monotonic`, `rlfix5-yes-no`, and `rlfix5-no-yes`
fail in both modes (six failing rows). Production-linked schedules fail in
both namespaces: STRLEN 9 then GET old; SET OK then GET old across yes→no;
GET new-value before the younger SET across no→yes. Live T10 also fails.
Raw evidence: `docs/rlfix5/pre-gate.tar.gz`.

Evidence corrections are retained, not counted as passes: one early gate attempt
used a candidate while it was being linked and was discarded; the first MGET
fixture incorrectly reused input storage while an operation still borrowed it.
The fixture now appends input until the ROB retires. The corrected PRE MGET
still returns the younger value and fails in both modes/namespaces
(`docs/rlfix5/jobs/corrected-pre-mget.tar.gz`). Only the fixed fixture and frozen
POST feed the final results. Intermediate instruction variants with added hit
instructions were rejected; their traces remain in the labelled archives.

RL5.7 adds six rows at the `collect_job rlfix5-*` lines, before the quick
exit: **DQ +6 / DF +6**. The EXPECT literals would become **1052 / 1069** from PRE's 1046 / 1063
by this lane's delta alone. However, PRE's source inventory already contains
1,107 full-tier rows (44 more than EXPECT_FULL); POST has 1,113. The source
inventory requires **1096 / 1113** after the inherited 44-row gap is accounted
for. `docs/rlfix5/gate-counts.json` records the exact additive difference.
Neither EXPECT constant is edited.

The gate's explicit `--shared-correctness-cpus` option permits this eight-CPU
allocation only with selected jobs and `GATE_PROOF_NO_RATES=1`. The server
retains eight threads, 16 shards and ratio 6:2. Full/performance execution
cannot use the option. Timing verdicts remain unavailable on shared CPUs. The feature-matrix driver now
forwards the same gate engine selector and verifies INFO `net_io`; previously it
ignored that selector and an epoll-labelled rerun still booted io_uring. This
changes no row count or server behaviour.

The final ordering jobs pass 7/7 including the release row: six RL5 rows,
all controlled schedules in both namespaces, live uring/epoll in both modes,
and the Redis 7.4.10 oracle. `docs/rlfix5/jobs/final-ordering.json` binds the
frozen candidate SHA. Every boot inherits `LC_ALL=C`.

| Item | PRE witness | POST result | Mechanism | Residual |
|---|---|---|---|---|
| RL5.2 | STRLEN 9 followed by GET old; live T10 fails | Both modes/engines pass STRLEN, EXISTS, GETRANGE, TYPE, TTL, OBJECT | Always extend owner slots for non-GET owner reads; existing point/broad overlap rules | Broad routes remain conservative as specified |
| RL5.1 yes→no | SET OK followed by GET old | Controlled schedules and pipelined toggles pass | Boot-latched bookkeeping continues while tracking is on; only lane eligibility is vetoed | Tracking-on bookkeeping cost is quantified separately |
| RL5.1 no→yes | Older GET/MGET returns younger SET's new-value | Both older reads return old, before SET OK | Same write staging, demotion and MGET fence stay active | None in these schedules |
| RL5.7 | Six new gate rows fail PRE | Six rows pass POST | Shared production-linked schedules plus live CONFIG pipelines and oracle | Broader matrix in progress; inherited EXPECT gap remains |

Instruction proof: 352 parser/owner/lane scopes plus 32 eight-shard scatter
scopes, batch 1/32, both modes and both namespaces. All **128 protected
comparisons have no added instructions**. The 80 read-local-off parser/owner
cases, with tracking both on and off, are exactly identical. The 16 lane GET/MGET cases are unchanged or lower.
The other 32 protected cases cover eight-shard MGET/MSET with atomic 0/1.
`docs/rlfix5/count-deltas.csv`, `scatter-deltas.json`, and `costs.md` contain
absolute counts/deltas and the non-GET/latency-on costs. The single-key
parser fixtures include real production parse, lane/owner execution and
completion; the extra scatter fixture uses eight distinct shards. Counters
exclude fixture bodies and shared libraries. These are finite instruction
counts, not throughput measurements. Latency-on cases include initial
connection bookkeeping; they are not a steady-state throughput estimate.

The zero-cost implementation reuses the shared classifier's already-decided
GET/MGET predicate at enqueue, retaining the boot-enabled guard, and expresses
the existing MGET/batch branches once. No queue, ring, ownership, grace,
capacity or retry algorithm changes. Locked layouts are unchanged.

The final linked census changes 31 hot symbol groups (including emitted clones),
listed individually in `docs/rlfix5/changed-hot-bodies.md`; the complete strict
normalization inventory is `changed-bodies.json`. The changed families are the
ordinary and R7 parsers in both namespaces, three `flush_ready` specializations,
two `run_loop` specializations, and emitted `refine_current_write_hash` and
`kvobj_external_bytes` clone groups. Identity is a proxy; no throughput merit is
claimed from these identities or instruction counts.

For the six non-GET reads with tracking off, batch-1 overhead is 5–12
instructions; batch-32 overhead is 281.125–997.156 instructions per command in
the same-key fixture. Marking every owner read makes later reads inspect their
older owner slots. With read-local and tracking both on, the full per-command
cost table is `docs/rlfix5/costs.md`; this previously skipped ordering work is
now performed. Those costs are not hidden in the protected hit-path comparison.

Frozen arms (all under `build/rlfix5/`):

| Arm | SHA-256 | .text bytes |
|---|---|---:|

| PRE | `e5be4275748bb9efbec96362bb8f7fcf7286313a7439d958593063916a74068d` | 9,021,623 |
| POST | `ee33679bab712d69b735539b1c13211e78ccc9a09dcecd18d668a098a5042a24` | 9,020,279 |
| PAD-A | `272ec9d4a68fb2f66ba5ec0b57385dcb0e158319247a513d4d9eb76653a889ce` | 9,020,279 |

PAD-A is **(A) behaviour twin**: PRE behaviour with POST's total text size.
POST is 1,344 bytes smaller than PRE. PAD-A recompiles only PRE's two cold
`t_server` units with compact alignment, then adds 13,616 unreferenced NOP
bytes. It matches total `.text` size, **not individual function placement**;
that limitation matters when interpreting the control. Source, link recipe,
and digest are in `docs/rlfix5/pad-a.json`. It contains neither S1 fix.
Cold-unit alignment changes 17 groups in the expanded hot-name inventory
(`pad-a-changed-bodies.json`), so PAD-A is not a body-identity control. Its 160
GET/SET/INCR/MGET/MSET scopes, across both modes/namespaces, both batch sizes
and all four lane/tracking states, nevertheless have exactly PRE's instruction
counts (`pad-a-count-deltas.json`). Its negative ordering witnesses are queued.

Maintainer measurement request: use these three frozen arms with the gate's
own instrument on a quiet box. Run the 14 generic cells, `d32g_l1`, `x9_32_l1`,
the eight-instance read-local GET cell, and 2s GET/SET at p1/p32.
`docs/rlfix5/measure-cells.txt` freezes the 18 distinct cells; `d32g_l1` is
explicitly pinned to eight load-generator instances and already belongs to
generic14, as does `x9_32_l1`. The 2s cells are h53/h54/h21/h22. Run pairwise
PRE↔POST and PRE↔PAD-A with matched offered loads and the established ABBA
ordering and identical-arm controls; retain rate, cycles/op,
instructions/op and IPC for every arm/cell. Rate at matched load (and each depth-one cell's declared latency score) decides
merit; cycles and IPC explain it. A control-compatible gain requires POST to move while
PAD-A stays flat relative to PRE. All performance cells, the full iteration,
`flip_saturated` (memtier), and the tailgen client-LB outstanding-bound row
(open-loop generator) are **NOT RUN** here: they remain maintainer-owned.

Broader correctness receipts and freshness results follow when the queued
selected jobs finish. No gate total or throughput verdict is claimed yet.
