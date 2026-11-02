## rlfix5

PRE is `ea48a6b272` (wave 14); branch `cx-rlfix5`. CPUs 24–31 only,
ports 21500–21599, `LC_ALL=C`. No performance measurements or push.

The PRE gate jobs `rlfix5-monotonic`, `rlfix5-yes-no`, and `rlfix5-no-yes`
fail in both modes (six failing rows). Production-linked schedules fail in
both namespaces: STRLEN 9 then GET old; SET OK then GET old across yes→no;
GET new-value before the younger SET across no→yes. Live T10 also fails.
Raw evidence: `docs/rlfix5/pre-gate/`.

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
cannot use the option. Timing verdicts remain unavailable on shared CPUs.

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

Instruction proof: 264 parser/owner/lane scopes plus 32 eight-shard scatter
scopes, batch 1/32, both modes and both namespaces. All **88 protected
comparisons have no added instructions**. The 40 read-local-off parser/owner
cases are exactly identical. The 16 lane GET/MGET cases are unchanged or lower.
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

Broader correctness receipts, final arm hashes and the maintainer's measurement
instructions follow after remaining validation completes.
