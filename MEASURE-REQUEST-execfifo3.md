# Remove FIFO's incidental plain-command parser cost

## execfifo3

PRE: `e32b04a44`. FIFO source: `2461efbbb` (`cx-execfifo2`), with its frozen
POST executable retained unchanged. Lane: `cx-execfifo3`, CPUs 96–111,
ports 20600–20699, `LC_ALL=C` on every correctness/oracle boot. No push.

The production diff changes **three GCC inlining-budget values in Makefile**.
FIFO/C1 increases the initial IPA size of both fused units by 2,031 compiler
size units. Their old ceilings caused ordinary RESP length parsing to be
outlined. The multi-database main unit grows by 1,646 and loses inlining of
`Client::nothing_to_write` in split parsing (+44 instructions and three
explicit memory operands per batch of 32). The corrected ceilings restore
the former absolute allowances; the final linked scopes return exactly to PRE.
Every FIFO source predicate, queue operation, hand-off, boundary and ownership
rule remains unchanged. No field, allocation, runtime branch or knob is added.

The original owner-command scopes missed this cost because they start after
parsing. In the db0 linked parser at batch 32:

| Cell | PRE instructions | FIFO | POST | PRE explicit memory operands | FIFO | POST |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1s SET, read-local 0 | 23,669 | 25,045 | 23,669 | 7,784 | 8,488 | 7,784 |
| 1s SET, read-local 1 | 27,427 | 28,803 | 27,427 | 8,939 | 9,643 | 8,939 |
| 1s INCR, read-local 0 | 21,205 | 22,485 | 21,205 | 7,272 | 7,880 | 7,272 |
| 1s GET, read-local 0 | 21,205 | 22,485 | 21,205 | 7,400 | 8,008 | 7,400 |
| 1s INCR, read-local 1 | 24,963 | 26,243 | 24,963 | 8,427 | 9,035 | 8,427 |
| 2s SET | 20,646 | 20,646 | 20,646 | 6,173 | 6,173 | 6,173 |

These are finite serverless instruction/access counts, **not throughput**.
The [source/access audit](docs/execfifo3/audit.md) explains why the suspected
unconditional FIFO waiter-state access is absent: the existing Shard+8 gate
short-circuits before the registry, in both ordinary and read-local writes.
The added SET accesses are 160 stack reads, 480 stack writes and 64 reads of
the thread-local stack canary (`FS+0x28`) per batch. INCR/GET add 384 stack
writes instead. The [access table](docs/execfifo3/accesses.md) identifies the
lines and their writers, including the separate multi-database split case.
There is no new unconditional FIFO cache-line access to gate away.

Final evidence so far:

* **48/48 owner-command comparisons exactly equal PRE**, GET/SET/INCR/MGET/MSET,
  both modes and namespaces, batches 1/32, both MSET atomic settings.
* **36/36 extended parser/owner comparisons exactly equal PRE** in instructions
  and explicit memory operands, with no added classified object lines; includes
  atomic 1 and fused read-local 0/1. An additional address trace confirms the TLS reads are
  removed. These finite fixtures have no WATCH/EXEC state; the source audit also
  states the active-reservation slow path rather than claiming it is free.
* **378/378 perf counter runs** pass with all events running at 100%, including
  one- and two-owner fixtures on CPUs 96/104. [All block counts and medians](docs/execfifo3/perf/README.md)
  are retained. This is not a zero-regression verdict: for example the full
  read-local SET parser fixture has cycle medians PRE/FIFO/POST of
  154.299/159.296/157.204 million. Some two-owner controls also have large
  coherence-counter differences; these process-level measurements do not
  attribute transfers to a FIFO line or establish server performance.
  **Direct LLC counts: NOT RUN.** This kernel exposes no AMD L3 PMU and rejects
  generic and named LLC-miss events. Its `cache-misses` alias is combined
  instruction/data **L2** misses; the [PMU audit](docs/execfifo3/pmu-audit/README.md)
  records the mapping and availability failures. Available remote-cache-fill
  and exclusive-request events are coherence proxies, not dirty-HITM counts.
* **160/160 F1–F10 legs**, **12/12 deliberate break controls**, and **16/16
  common-image smoke cells** passed. The broader selected-job matrix is running.
* `python3 tests/gates_test.py` passed on a quiet rerun with its deadlines
  unchanged. The initial scheduler-fixture timeout and all artifacts are retained.
* `make all`, the complete `job_production_units` build, and **60/60 make -q
  freshness queries** passed. Debug-only unit compression preserves `.text`;
  the five aggregate stamps affected by changed mtimes were rebuilt and rechecked.

### Gate accounting

**DQ=0, DF=0 relative to execfifo2.** No gate row is added, removed or moved.
The inherited FIFO/C1 rows still precede the quick-tier exit; the inherited
request remains **992 quick / 1009 full**, versus the untouched source
constants 977/994. This is 10 FIFO rows + 1 live FIFO row + 4 C1 rows, collected
at `tests/gate.sh` lines **6299–6301**, before the quick-tier exit at line
**6423**. Only the maintainer changes those constants.

### Artifacts and control semantics

Artifacts live in `build/execfifo3/`: `PRE`, `FIFO`, `POST`, `POST-layout`,
and `PAD-A`. [SHA256SUMS](docs/execfifo3/SHA256SUMS) and the
[artifact manifest](docs/execfifo3/arms.json) bind the exact images.

| Arm | SHA-256 |
| --- | --- |
| PRE | `15faa04036c682eba596d520925bedd55f337d0802029db893fd5cb25d523c3b` |
| FIFO (unchanged) | `ee5aee2768e0e8f8899a90f628a45f8a2ec47cebe3e405dbf9cf21210e9d0b0a` |
| POST | `6f9af8cdb5e6491437565b587451fcdcf5c5ddce1ee5d654bc0c1d9d73dc08b8` |
| POST-layout | `c3512ef049bd02e5fcf9ef4da31a32b1909cd21ae2a8136303f488029903aa25` |
| PAD-A | `47c757dca7ceacff91b512c52b6aafdeecbaa6b217ab7636c7774b8d6507e7c4` |

PRE was rebuilt from e32b04a44; its executable `.text` is identical to
execfifo2's frozen PRE (full-file differences include build/debug provenance).
FIFO is byte-identical to execfifo2's frozen POST. POST's `.text` is 8,759,831
bytes, +20,432 versus FIFO. The intermediate two-budget candidate and its own
PAD-A/common-image pair remain in `build/execfifo3/stage1/` with separate receipts;
the table above always names the final three-budget candidate.

PAD-A is **type A, behaviour twin**: PRE behaviour in the identical combined
POST-layout image. The control pair has identical ELF sections, symbols and
function addresses; only the entry jump changes. Its exact twin is
`POST-layout`, not the smaller release `POST`. The entry chooses different
PRE/POST function bodies within that common image, so this does not hold
their executed instruction addresses fixed. The release comparison remains
necessary; no stronger code-placement control is claimed.

### Maintainer measurement request — NOT RUN here

Use the gate's instrument on the quiet box, identical allocation and offered
load for every arm, three blocks per comparison. Retain individual blocks,
cycles/op, instructions/op and IPC. Current harness, driver and oracle digests
are recorded in [measurement-tools.json](docs/execfifo3/measurement-tools.json).

1. Run the generic cells against PRE for both FIFO and POST:
   `h05,h06,p8g,p8s,d1g_l0,d1s_l0,d32s_l1,d8s_l1,d32g_l1,x9_32_l1,x9_32_l0,m8g_l0,v1g_l0,d128g_l0`,
   plus `cc_2s_get_p1,cc_2s_set_p1,cc_2s_get_p32,cc_2s_set_p32`. Prioritize **d32s_l1** and
   **x9_32_l0**. Run POST-layout versus PAD-A on the same cells. Main commands
   must meet the owner's zero-regression rule against PRE.
2. Retain the 64-connection EXEC merit (`exec-merit.py --cells all --blocks 3
   --secs 20 --threads 16 --conns 64`, pipeline 4), both modes and atomic
   settings, hot and uncontended. Compare POST with both PRE and FIFO;
   retain the four plain-writer clients' completions and share.
3. Retain execfifo2's same-owner/same-shard/cross-owner depth sweep and
   contended-script merit. Use `exec-depth-sweep.py --mode 1s` and `--mode 2s`,
   each with `--blocks 3 --secs 10 --atomic 0 --placements
   cross,same-owner,same-shard --depths 16x1,16x4,32x4,64x4,128x4`; select each
   arm with `--binary`. Use `script-storm-merit.py --blocks 3 --secs 30` for
   the standard T6 load. POST must retain FIFO's measured advantages;
   instruction savings alone do not decide this.

The merit scripts are in `/home/user/Projects/calib/`. Supply explicit
`--reference` / `--candidate` paths, `--benchtxn
/home/user/Projects/bins/benchtxn-b6e76d422` where applicable, a distinct
`--output` directory, and maintainer-selected `--server-cores`, `--load-cores`
and `--port` for every run. Keep `LC_ALL=C` on every boot. Retain execfifo2's
Redis 7.4 comparison if judging the original hot-EXEC-versus-Redis condition.

All throughput cells, load generators and full `iteration` are **NOT RUN**:
they remain maintainer work. Correctness uses only selected gate jobs, the
Redis 7.4 oracle, differential suites and serverless fixtures.
