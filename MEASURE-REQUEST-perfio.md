## perfio

Lane `cx-perfio`, worktree `/home/user/Projects/cx-perfio`; no push. **Proof in progress.**
PRE is merged `origin/cpp` **991d48f651d3c6e1324c061bd9ea801ac085afe8**,
built with `make -j16 BUILD_ROOT=build/perfio/pre all`. The requested pfconfirm
branch was merged and perfex commit `d867a1073` cherry-picked; this lane has not
edited `docs/pfconfirm`. Production changes are confined to the migration commit
in `src/core/io_loop.h`, stream metadata/delivery in `src/cmd/t_stream_groups.cc`,
and two existing compiler inlining budgets in `Makefile`.

All lane commands and children use CPUs 112–127; target 112–119, oracle 120,
load 121–127, ports 25125–25149. The task-specific PROOF authorizes these focused
live tests. No full gate or mainline merit run is being performed by this lane.

| Finding | PRE | POST | Gate row |
|---|---|---|---|
| IO4.19 FLIP | Stale interests grow; extra events; eventual rollback-reservation refusal | 12 moving FLIPs, 201 connections: zero stale/duplicate interests; events/command 1.000 | `perfio stale epoll registration (epoll-flip)` |
| IO4.19 client-lb | Witnessed natural skew-driven move leaves a stale, duplicate interest | Natural move witnessed; 97 connections, zero stale/duplicate interests; events/command 1.000 | `perfio stale epoll registration (epoll-lb)` |
| PFDATATY.1 | Both modes fail the fixed 3 ms GET-after-XREADGROUP bound at 100k entries; metadata also differs from Redis | All 120 oracle metadata snapshots match. Final quiet latency proof pending | `perfio XREADGROUP bounded delivery + Redis metadata (1s)` and `(2s)` |
| NT4.2 | Report only | No production parser change; counter-build patch and incidence driver under `docs/perfio` | None |

The same parameterized `tests/perfio.py` supplies PRE negatives and POST rows.
It derives from audit T16/T16b and shape T5/T13, owns its child PID and port, and
requires actual migration before inspecting `/proc/<pid>/fdinfo`. Socket inode
matching catches fd reuse; exact registration totals prevent vacuous audits.
FLIP collection retains every failed assertion while collecting event amplification,
then fails the row. Client-lb must move within 35 seconds; no missing window is skipped.
Raw receipts: `docs/perfio/{pre,post}-epoll-{flip,lb}-final.log` and corresponding
server directories. `pre-stream-{1s,2s}-final.log` contains the stream negatives.

The epoll fix explicitly DELs the reserved source interest before closing its dup.
Rollback already DELs the destination interest before closing the original fd and
adopts the still-registered source backup as the live fd. Removing that adopted
registration would break rollback. The wave-1 lifetime/pinning scheme is unchanged.

Stream delivery now advances the existing entries-read counter for delivered entries
only when the cursor and max-deleted ID make it usable. Otherwise it infers a value
only at known first/tail boundaries or returns unknown, using cached first ID,
entries-added and live length. XINFO GROUPS and XINFO STREAM FULL use the same guarded
lag semantics. No collection of every record remains in delivery or lag inference.
The stream seek still costs O(log macro-nodes), with bounded node decoding and work
proportional to delivered payload; the removed cost was O(total stream records).
There is no new state, layout or persistence format. Persisted existing counters are
validated by the same metadata guards after native DEBUG RELOAD.

`tests/fixtures/perfio-stream.json` was recorded from the pinned vanilla Redis
7.4.10 (`f103d127`) oracle. Controls cover ordinary delivery, XDEL ahead/at the cursor,
XTRIM including empty, XSETID, XCLAIM LASTID, XAUTOCLAIM deleted PEL entries,
explicit ENTRIESREAD, arbitrary/tail group cursors and native reload. Both XINFO
forms must agree with the fixture at all 120 checkpoints. DUMP of streams with groups
is unsupported by PRE; reload proof therefore uses each server's native snapshot (DEBUG RELOAD).

Gate accounting: DQ **+4**, DF **+4**. Two rows are emitted by `job_flip`,
two by `job_perfio_stream`; both collection sites precede the quick-tier exit.
Starting values **625 / 642** require **629 / 646**. The arithmetic comment
is above the unchanged EXPECT assignments. All **646** fixture labels match the
source inventory. The unmodified `python3 tests/gate_ledger_fixture.py` refuses
solely because EXPECT_FULL remains 642, as the owner-only count rule requires.
The stream timing job waits for ordinary jobs, before the existing atomic timing
job, to preserve its fixed 3 ms bound without a dependency cycle.

Initial reserved-core timing runs were contaminated by other compilers and lane
servers: even XLEN controls had millisecond scheduling stalls. The failed receipts
are retained; the 3 ms bound has not changed. A quiet window was requested.

**NT4.2 static inventory** (16,384-byte initial receive buffer):

| Cell file | Cells | Largest scored frame: arguments / bytes | Largest pipeline bytes |
|---|---:|---:|---:|
| `tests/headline_cells.txt` | 181 | 17 / 759 (8-key MSET) | 97,152 |
| `/tmp/claude-1000/generic_merit_cells.txt` | 14 | 9 / 190 (8-key MGET) | 4,480 |
| `tests/netio_cells.txt` | 32 | 3 / 106 (SET) | 3,392 |
| `tests/ttl_cells.txt` | 2 | 4 / 117 (wire SETEX) | 3,744 |
| `tests/mkprobe_cells.txt` | 19 | 17 / 759 (8-key MSET) | 97,152 |
| `docs/pfconfirm/cells.txt` | 12 | 17 / 735 (8-key MSET) | 3,392 |

Sizes use the maximum generated key length and describe requests. `GET:1024`
and TLS `GET:4096`/`GET:16384` remain two-argument GET requests. The
`tracking-mset1024` cell has 1024 resident keys, not 1024 arguments.
REORDER's 256 KiB values and TLS 4/16 KiB population SETs exceed the initial
receive buffer during setup, outside scored traffic. A pipeline consists of
separate frames. Remaining buffer space can be smaller than capacity and TCP/TLS
can fragment any frame. No supplied scored cell resembles the audit's 2M-argument
frame. File hashes and every cell: `docs/perfio/nt4-frame-inventory.json`.
The temporary generic cell file is copied to `docs/perfio/generic_merit_cells.txt`.

`docs/perfio/nt4-counters.patch` is applied only in `build/perfio/nt4-source`;
no production parser change. It counts multibulk Incomplete results and completed
arguments discarded in those attempts, which successful drained commands must
parse again. This conservative argument count excludes unfinished bulk-header
work. Counters occupy separate cache lines per IO owner; INFO snapshots bracket
load, after population. `docs/perfio/nt4_probe.py` drives SET:1024 p32, eight-key
MSET p8, and TLS GET 4/16 KiB p32 with 1/512 connections, both modes, at least one
million completed commands per cell. A forced-split MSET must fire the observer.
Incidence table and fix/no-fix recommendation are pending the quiet run.

**Reproduction and mainline handoff:**

```sh
# Repeat these identical rows for PRE build/perfio/pre/tomokv and POST build/tomokv.
taskset -c 112-127 python3 tests/perfio.py epoll-flip --binary build/tomokv \
  --port 25125 --cores 112-119 --output docs/perfio/recheck-flip
taskset -c 112-127 python3 tests/perfio.py epoll-lb --binary build/tomokv \
  --port 25125 --cores 112-119 --output docs/perfio/recheck-lb
# Repeat for both --mode 1s and 2s.
taskset -c 112-127 python3 tests/perfio.py stream --mode 2s --net-io uring \
  --binary build/tomokv --port 25125 --cores 112-119 --output docs/perfio/recheck-stream

taskset -c 112-127 docs/pfconfirm/run.sh --smoke --only PFDATATY.1 \
  --binary build/perfio/pre/tomokv --sha256 <PRE-sha256> --port 25145 \
  --output docs/perfio/pfconfirm-smoke-pre
taskset -c 112-127 docs/pfconfirm/run.sh --smoke --only PFDATATY.1 \
  --binary build/tomokv --sha256 <POST-sha256> --port 25145 \
  --output docs/perfio/pfconfirm-smoke-post
# Maintainer's full quiet-box merit run, outside lane authorization:
docs/pfconfirm/run.sh --only PFDATATY.1 --binary build/tomokv \
  --sha256 <POST-sha256> --output <new-directory>
# Required full verdict: NOT CONFIRMED on POST; mainline also runs a performance null.
```

Final build, smoke, SHA-256 and identity tables will be filled from completed
receipts. The initial audit found three unrelated hot-body drifts from GCC
inlining. Compile-only probes restored all three with +12 to two existing budgets
(the epoll DEL adds 8 IPA instructions): `docs/perfio/inline-probe.json`.
The default rebuild is pending. All eight layout locks and every named field
offset already match in both namespaces; initial receipts are retained under
`docs/perfio/identity-initial/`.
