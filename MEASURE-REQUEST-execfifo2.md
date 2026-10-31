# FIFO hand-off on the current headline

## execfifo2

Base/PRE: `e32b04a445b056976abb308aa598e356fcbaae74`.
Approved source: `cx-execfifo-arm-c1` / `bd0cb9668` (B+C1 only, D6).
Lane: `cx-execfifo2`; no push. All builds and correctness work use CPUs 0–31,
ports 20100–20199, and `LC_ALL=C` for every server boot. Performance and the
full iteration remain maintainer work; no throughput claim is made.

Port sequence: B with unified EXEC/escalated-script key admission; then C1
owner-local chaining and H3 boundaries, preserving headline X1–X5, woundfix,
D1–D10/amend1/D4′ and FLIP stage obligations. C2/C3 are excluded.

`EXPECT_QUICK` and `EXPECT_FULL` remain unchanged. Release/PAD identities and
maintainer-only measurement commands are recorded below.

### Implemented order and progress argument

For each owner/key, a plain writer W is refused by a live, **waiting EXEC**
whose monotonic age is <= W's saved writer-episode stamp. On first refusal the
existing A' episode marks every key touched on that owner. Repeated dispatch
probes preserve the stamp; only the final execution gate removes its marks.
A younger unit cannot place ahead of that stamp. The retiring EXEC promotes an
eligible writer to the front of the deferred queue, where the writer still
rechecks its complete key set and connection order. This is the D1 amendment.

EXEC and escalated scripts use the same `TxnKeyQueue::head`, comparator
`(age_ns, age_io, age_seq)`, monotonic clock and IO sequence. A script draws that
age at its **first escalated IO dispatch**, preserving it across retries. Its
optimistic-slot FIFO remains per IO and counts only optimistic activations;
escalated attempts use neither a slot nor a read cut (AT4.12 C8). No second
EXEC-versus-script priority queue or script age reset is introduced. F10 checks
both mixed arrival orders and a script younger than an existing writer mark.

D-F1/2/3 remain **no/no/no**: whole-shard waiters do not FIFO-block keyed
writers; kind-2 waiters (including escalated scripts) do not gain a new
plain-writer FIFO predicate; unstarted placed EXEC claims are not FIFO
waiters. Existing held/started/validation predicates still apply. FLUSH checks
all relevant queues. EXEC children, blind atomic groups, script APPLY,
blocking serves, WATCH/UNWATCH and committed dirtying retain their original
non-FIFO predicates (R-F2). Script placement still obeys the shared claim
order and writer marks; D4's execution immunity and cancellation rules stay.

For a fixed stamped writer, later EXECs cannot enlarge its predecessor set:
its finite older waiting/held units drain, and younger units wait on its mark.
The mark survives both readiness probes (R-F1), so a passing writer cannot
accidentally acquire a younger episode. Progress assumes the existing owner
scheduler and predecessor progress, rather than imposing a new reader wait.
F1/F2/F3 assert actual refusal, stamp persistence, and hand-off; F6 puts 1,000
younger units behind the mark. The live row requires all four plain clients to
progress in every one-second window of a continuous EXEC stream, with exact
data/counter checks and the inherited latency bounds.

C1 drains only owner-local runnable nodes, with a recursion guard. Siblings
released by arrival/phase/command/decision events and the next eligible EXEC
can run in the same turn. A refused markless operation leaves an H3 boundary
note; boundary service precedes another fresh EXEC, while already placed
siblings may complete. The note never becomes a placement dependency (B9).
Boundary notes live in existing shard padding and move with the shard. Runnable
nodes remain in the existing retry count, so the unchanged ExDrain quiescence
check includes them. `flip_stage_owed` and all FLIP acknowledgements are intact.

Port-specific adaptations retain compact participant slots, fused wake hints,
`execute_resumed` timing, the tracked/untracked `multi_execute.inc` variants,
repeated-key version reuse and X2 eager reclamation. No C2 event parking or C3
lone-claim shortcut is present.

### Gate accounting

Ten FIFO directed rows (including new mixed-script F10), one sustained FIFO
row, and four C1 rows (local, WATCH boundary, BLPOP boundary, hot hand-off) are
collected before the quick exit. **DQ=+15, DF=+15**. The source inventory is
994 -> 1009 full rows with no removed labels. The unchanged 977/994 constants
should become **992/1009**; only the maintainer changes them. The new jobs are
collected at `tests/gate.sh:6299–6301`, before the quick exit at line 6423.

### Verification status

Verification is in progress. Completed-run identities and any failed attempts
will be retained under `docs/execfifo2/`. This is a selected-job proof, never a
full iteration receipt. The full iteration and all performance cells are
**NOT RUN** by this lane.

### Falsification controls

All **12/12** process-local GDB controls detected the intended break, in both
modes and both compiled namespaces. Returning true from the plain-writer probe
fails F1's older-waiter refusal; disabling the chain drain fails the same-turn
completion assertion; bypassing boundary service fails the held-claim BLPOP
refusal. Each record requires a fired breakpoint, the exact expected assertion
and inferior exit 1. No broken source or executable is published. Commands,
unit hashes and outputs are in `docs/execfifo2/negative/`.

### Frozen artifacts

Paths below are relative to this worktree's `build/execfifo2/`.
The release objects match source commit `6cb177b21`; subsequent evidence-only
commits do not change them. PRE and B sources were separately archived and built.

| Arm | SHA-256 | .text bytes |
| --- | --- | ---: |
| `PRE` | `735cbffb1afa279a4b47ddd42411cbc5d4e25a38653c01150ee15edc5fd6ebca` | 8729431 |
| `POST-B` | `f45b5089e6132897df60e2c824868c8a35e1a37214cca941d6e114d77a1c11da` | 8726343 |
| `POST` | `ee5aee2768e0e8f8899a90f628a45f8a2ec47cebe3e405dbf9cf21210e9d0b0a` | 8739399 |
| `POST-layout` | `02dec207ab3d5fef1aa257e353966f7d8572b477ed4f30817eca9bafb58b0998` | 17468455 |
| `PAD-A` | `07df961f35b194562de4e27e8b3a2be467ef9d250d448330f8e8d5494976b432` | 17468455 |

PAD-A is **type A, behaviour twin**: PRE behaviour in the exact POST-layout
common image. POST-layout and PAD-A have identical ELF sections, symbol tables,
and function addresses; the only difference is the five-byte entry jump.
Their exact twin relationship is with each other, not the smaller release
POST. Keep both comparisons. `docs/execfifo2/pad-a.json` records the link,
object hashes and patch; `pad-smoke.json` records **16/16 PASS** (two images ×
two modes × two engines × db1/db16), with EXEC, WATCH, EVAL and FCALL checks.
The first smoke attempt used MGET inside Lua, which this baseline disallows;
the fixture now uses two allowed GET calls. That driver error is retained.

### Maintainer measurement request — NOT RUN by this lane

Use the gate's instrument on the quiet box, record CPUs/ports and `LC_ALL=C`,
and use the same allocation for every arm. Compare PRE against POST-B and POST;
use PAD-A as reference against POST-layout for the exact image control.
Scripts are in `/home/user/Projects/calib/`; their digests, the benchmark driver's
digest and Redis oracle digest are in `docs/execfifo2/measurement-tools.json`.

1. `exec-merit.py --cells all --blocks 3 --secs 20 --threads 16 --conns 64`:
   all eight cells, 1s/2s × atomic 0/1 × hot/uncontended, pipeline 4. Retain
   the four plain INCR clients' individual progress, rate and share in each
   hot cell as well as EXEC rate, cycles/op, instructions/op and IPC.
2. `exec-depth-sweep.py --mode 1s` and `--mode 2s`, each with `--blocks 3
   --secs 10 --atomic 0 --placements cross,same-owner,same-shard --depths
   16x1,16x4,32x4,64x4,128x4`. Retain every block and all per-EXEC counters.
3. `script-storm-merit.py --blocks 3 --secs 30`: the contended T6 script storm,
   with its standard load and placement. This judges the shared script/EXEC
   admission path rather than assuming the earlier at412 result carries over.
4. Repeat the same EXEC cells/depths against Redis 7.4.10 with
   `--reference /home/user/Projects/redis/src/redis-server --redis-io-threads 4`
   (the harness enables `io-threads-do-reads yes`). The owner verdict is
   **POST hot-key EXEC at least equal to Redis 7.4 on the same workload**.
5. The 14 generic ABBA cells:
   `h05,h06,p8g,p8s,d1g_l0,d1s_l0,d32s_l1,d8s_l1,d32g_l1,x9_32_l1,x9_32_l0,m8g_l0,v1g_l0,d128g_l0`,
   plus `cc_2s_get_p1,cc_2s_set_p1,cc_2s_get_p32,cc_2s_set_p32` as a null.

For `exec-merit.py`, supply `--reference build/execfifo2/PRE --candidate
build/execfifo2/POST` (or POST-B), and
`--benchtxn /home/user/Projects/bins/benchtxn-b6e76d422`. For depth sweeps,
`--binary` chooses each arm separately. Give every run its own `--output`
directory and explicit maintainer-selected `--server-cores`, `--load-cores`
and `--port`. Run POST-layout/PAD-A on the same cells to distinguish behaviour
from common-image layout effects. Rate at matched offered load is the verdict;
instructions and IPC explain it. No throughput result is asserted here.
