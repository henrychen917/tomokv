## blockfix

PRE is `05a5e01a9d8f1236e11cdbe4f2f7d490eb40edba`; branch `cx-blockfix`.
Builds and child commands use CPUs 80–95; TomoKV/Redis listeners use 37800–37899.
Final stock harness socket probes also use that range through `GATE_TEST_PORT`.
Earlier harness-only runs used that script's default ephemeral probe ports.
No push, full iteration gate, throughput benchmark, or measurement load generator.

Item commits: AT4.8 `5b1b5874f`, CC4.18 `88b1ffce5`, CC4.19 `419fd26f1`.
Gate wiring was folded into its item without changing the tested tree or working
file timestamps; `docs/blockfix/commit-provenance.json` records the identical tree.

### Changes and reproductions

* **AT4.8 reproduced and fixed.** The registry now hashes namespace/hash/key bytes,
  retains a FIFO deque per key, and indexes waiter membership separately. Publishing
  erases only the selected empty queue. Deadline sweeps still visit every waiter;
  registration retries and duplicate key arguments preserve the earliest position.
  The registry remains shard-owned and uses its existing migration/lifetime pointer.
  Shards without waiters retain the existing early return; untouched shards allocate
  no registry. No locked production layout changes.
* **CC4.18 reproduced and fixed.** MKSTREAM creates an empty macro-node stream.
  Embedded XADD storage promotes when either node limit requires rollover, preserving
  its existing node when CONFIG changes. Legacy external Compact streams promote on
  append while retaining their group/PEL pointer. Both node axes and zero settings
  have directed coverage. PRE's Compact path and the old streamgroups expectation
  counted an ID skipped by XCLAIM LASTID as a delivery. Redis rejects that expectation.
  The common macro-node path and corrected battery report entries-read=7/lag=1,
  with an independent oracle comparison in the new battery. The revised existing
  streamgroups row fails PRE and passes POST in both modes and atomic settings.
* **CC4.19 reproduced and fixed.** Regular and FULL XINFO use the actual macro-node
  index size and the compressed radix topology of its big-endian base IDs, including
  the empty root. TomoKV allocates a sorted vector index, not Redis's rax objects:
  `radix-tree-nodes` describes that index's Redis-style logical topology, **not an
  allocation census**. No extra counters or work are added to the XADD path for XINFO.
  Other XINFO values were inspected: length, IDs, entries-added, group counts/cursors,
  entries-read/lag, PEL and consumer counts, timestamps, idle/inactive and entry arrays
  all derive from state; no additional hard-coded placeholder was found.
  XINFO's radix-node calculation walks the index with at most 16 key-byte levels;
  it is allocation-free but linear in indexed nodes, not Redis's cached O(1) count.

Directed rows use the gate's existing `compat3_case` helper: **24 legs per item**
(databases 1/16, atomic 0/1, epoll/uring, split read-local 0 and fused read-local 0/1).
Every boot has eight threads and 16 shards; split is 6 io + 2 ex. Source inventory and
fixture agree on 788 labels. Collection lines 5222–5224 precede quick exit line 5375:
**DQ=+3, DF=+3; maintainer counts should become 771/788 from 768/785.** EXPECT constants
remain untouched. The stock fixture checker therefore refuses only the count mismatch;
there are no missing or extra fixture labels.

### Instruction witness (no throughput claim)

`tests/blockfix_cost.cc` includes the production owner implementation and invokes real
LPUSH/XADD handlers plus their publication hooks. It opens no listener and starts no
worker. One 16-shard 6:2 server object holds 1/100/10,000 distinct blocked keys on shard 0;
each written key hashes to that same shard and has no waiter. `perf_event_open` counts
retired user instructions only around 64 calls, excluding key generation, request
parsing, socket IO, background sweeps and setup. Registration is the owner registry's
BLPOP insertion, not an end-to-end network command; its 64 inserts follow the stated
initial population. Counts are not latency, cycles/op, or matched-load rates.

| Initial blocked keys | PRE LPUSH | POST LPUSH | PRE XADD | POST XADD | PRE registration | POST registration |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2106.70 | 2129.69 | 3529.45 | 3565.55 | 2912.11 | 1339.00 |
| 100 | 2466.52 | 1994.45 | 3994.34 | 3591.55 | 4200.06 | 1185.36 |
| 10,000 | 52097.17 | 2145.98 | 53601.30 | 3678.02 | 111157.67 | 1282.47 |

These are final combined-binary POST counts; the earlier registry-only counts also
remain in the receipts. The gate rejects a >4x increase
over the one-key control and also executes all 24 FIFO/oracle legs even when that
cost assertion fails. PRE fails the cost arm; POST passes it. Same-key FIFO, duplicate
binary keys, a middle timeout, disconnected/recreated queues and stream cursor
skipping have deterministic reply and actual-parked-client witnesses.
The gate's production_units helper builds the witness and its server SHA-256 binding
through `tools/blockfix_cost.mk` and checks both outputs with `make -q`. External
PRE/PAD candidates carry their own frozen witness and binding. A missing or stale
pair fails the row, while all protocol legs still execute.

### Structural compatibility boundaries

The directed exact oracle comparisons use identical node limits and inputs with
entry-limited nodes, forced byte rollover, unlimited nodes and the default limits.
IDs exercise both components and common-prefix branching; regular/FULL replies,
RESP2/RESP3, group creation and trimming to empty are compared in full.

Additional observations in `docs/blockfix/native-structure-boundaries.json` expose
existing representation differences instead of substituting invented Redis counts:
with 250 `XADD s i-0 f v` entries and a byte-only limit of 64, Redis has 63 macro nodes
and TomoKV has 250, because Compact and listpack use different byte budgets. At 128,
the counts are 25 versus 28. XDEL of all three one-entry nodes leaves three tombstoned
nodes in TomoKV, whereas Redis removes them. XINFO now reports the retained structure.
Matching Redis's packing estimates or changing tombstone reclamation is separate
from making MKSTREAM use the ordinary XADD structure and reporting its real index.

### Maintainer merit request

Use PRE `build/blockfix/PRE/tomokv`, POST `build/tomokv`, and
PAD-A `build/blockfix/PAD-A/tomokv`. SHA-256s, text sizes and exact link commands are in
`docs/blockfix/binary-manifest.json`. PAD kind **A: behaviour twin**: PRE behavior,
with unreachable trailing padding matching POST's total `.text` size. This controls
total text size, not every function address or internal alignment. Locked production
types are unchanged; the registry heap sidecar changes representation as part of
AT4.8. This PAD does not equalize its allocator state. No inverse PAD-B arm.
PAD-A also ran all three directed gate jobs: all 72 oracle legs were present, FIFO
replies passed, and the three defect witnesses failed exactly as on PRE.
Its linked audit matches PRE in all 340 audited bodies and their start addresses.
Because padding is trailing,
internal candidate alignment effects remain possible even if POST moves and PAD-A
stays flat; this arm alone does not establish purely behavioral attribution.
The final padding object preserves the compiler's CET property note, `.text` start
address and both PLT sections. The first control lacked that note and was replaced;
its evidence is retained under `initial-*` and the earlier PAD gate log.

Run the gate's own quiet-box ABBA instrument on exactly these generic 14 cells:
`h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0 v1g_l0 d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`.
Compare PRE/POST and PRE/PAD-A with matched geometry and offered load. Record rate,
cycles/op, instructions/op, IPC and the depth-1 latency scores. Rate/latency against
the instrument's null-control criteria decide merit; instructions and IPC explain
it. A PAD movement limits behavioral attribution. **No throughput claim is made.**

### Verification status

All directed executions use `tests/gate.sh`'s own selected-job interface. The three
new rows each have all 24 declared legs on PRE, POST and PAD-A. POST passes all 72
oracle legs and all three rows. PRE/PAD-A pass the 24 registry FIFO legs but fail
the instruction-growth witness; all 24 MKSTREAM and all 24 structure legs fail
their defect witnesses. The final reserved PRE directed run has 7 passing rows
(release plus all six existing compat3 rows) and exactly the three intended failures.

The four feature jobs cover blocking, blockmulti, stream, streamgroups, s6/list,
zsetops and every other battery in their declared inventory in split/fused modes
and atomic 0/1. POST passes all 138 feature rows. PRE fails only the four corrected
streamgroups assertions after replaying one auxiliary-server bind failure.
`datafix1_lists` passes on both binaries with all declared engines/modes. POST's
`netcmd_units` (16 rows) and `exbatch_units` (3 rows) pass. Both arms pass all six
compat3 rows, each with all 24 legs; a POST history bind failure was replayed through
the entire compat3 job. See the final/wired/reserved receipts, not the earlier
mixed-test-revision runs.

`make all` and every production_units target were built with `-j16`; all **46**
freshness checks return 0, including the supplemental cost witness and its binding.
`production-build-final.log` and `production-freshness-final.json` contain the exact
targets and commands. PRE retains only its binary and needed object subset; there
is no duplicate full PRE build tree. Large reproducible disassembly caches were removed.

The stock differential matrices ran through the gate on both engines, with split
6:2 and fused/read-local=1, 16 shards/databases and atomic 0/1. Each completed 938
declared legs, including the stock atomic-1 MULTI repeats; armed sort is excluded
by the stock driver because it requires split geometry. Seeds were 7/19, retained
20/23 and per-run rotations: POST uring 21, POST epoll 22, PRE uring 24, PRE epoll 25.
Of **3,752** legs, **3,727 passed**; the other **25** failed solely at Climon's
reader-control `bind()` with EADDRINUSE before comparison. The original ledgers
remain red. A complete reserved-port POST epoll split replay also passes its four
gate rows. `standard-differential-summary.json` records every original failure.

Matched Climon replays use the stock `tests/differ_gate.sh` focused-proof interface,
not a substitute differential driver: seeds 7,19,20,21,22,23,24,25 × atomic 0/1 ×
both modes × both engines × PRE/POST = 128 cases. These are explicitly focused
replays, not replacement full-matrix receipts. **All 128 passed**, with coverage
sidecars for every case and zero returns from all eight driver invocations.
DIFF-TRK-1 was not observed in these matched replays. Both PRE and POST also pass
the complete `perfio_stream` job (release plus the 1s and 2s stream rows) when run
after the concurrent proof jobs finished. Quiet `python3 tests/gates_test.py` runs
passed **72/72 on POST and 72/72 on PRE**, with 14 nested persistfix self-tests also
passing in each run. The PRE harness is an unchanged archive of `05a5e01a9`.
Earlier deadline failures under concurrent correctness work are retained in the
`gates-test*` logs, without changing any timeout or assertion.

Identity is a proxy, not the merit verdict. The strict linked audit (including
literal-pool consumption and normalizer negative controls) compared the actual
baseline inventory of 340 bodies: **339 identical, one different**. All 16 GET/SET
bodies match. The 32 multi-key bodies have one 1,190-byte xshard lambda with a
short-to-near backward branch, a four-byte epilogue shift, and four fewer padding
bytes; both arms have 281 instructions and the same operations. No hot source body
was edited. Scheduler 72/72, envelope 120/120, dispatch 92/92 and retirement 8/8 match.
The object audit reports 72/74: its additional db0 mismatch is resolved by the
linked audit's address and consumed-literal normalization (a four-byte float's
unused neighbour changed). All locked sizes and every field offset match PRE,
POST and PAD-A in both namespaces. See `docs/blockfix/linked-identity.json`,
`identity-diffs.tar.gz`, `command-hot-identity.json` and `layouts.json`.

The allocated lane ports overlap the host's ephemeral range (32768–60999; no
reserved-port sysctl entries). Initial receipts retain observed bind failures.
`tools/blockfix_ports.py` replays the exact gate jobs while holding non-listening
SO_REUSEADDR sockets for their three ports; the real server can bind/listen, while
automatic client-port allocation cannot take a port between boots. It changes no
server arguments, reply assertions, deadline, or host setting.

`docs/blockfix/gate-receipts.json` indexes every selected-job run and its archived
ledger, per-leg logs and coverage. `climon-receipts.json` and its companion archive
record the 128 focused cases. Final PAD-A evidence is in
`final-pad-a-replay-gate-receipts.tar.gz`; the earlier `pad-a-gate` receipt belongs
to the replaced initial control. Binary hashes and cost bindings were rechecked,
and all 46 freshness checks still pass after the final proof runs.
`verification-summary.json` selects the final receipts and checks their leg counts;
no listener remains on the lane's 37800–37899 port range.

**NOT RUN:** the full `tests/gate.sh iteration`, throughput/load-generator
measurements and the 14-cell merit comparison are reserved for the maintainer by
the task. The instruction-only witness above was run as explicitly requested.
