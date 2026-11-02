## cfgfix2

Lane `cx-cfgfix2`, PRE `bc80de80b87ce482cf067a446a8411f7baef074a` (lane cfgfix's
final commit). No push. Every build, correctness runner and server used CPUs
32-47 only (gate server 32-39, load 40-47; pool b mirrors them), `LC_ALL=C`,
and ports 21800-21899. Gate servers boot 16 shards at split ratio 6:2. No
performance workload, ABBA, NIC, or full `iteration` gate was run by this lane.

This lane fixes the six severe (S1) configuration/ACL/INFO/shutdown defects the
round-5 audit confirmed, on top of cfgfix. It continues the codex lane that
stopped on a content-filter false positive: the two committed items (CG5.1
`2f70d3e99a`, SV5.2 `f26358d157`) were verified on the final binary, and the
maintainer's WIP `9a09b5093a` (SV5.1) was reviewed and completed. Wave 14 is not
in this base; conflicts with it are noted at the end.

### Items

| Item | PRE witness (TomoKV legs vs Redis 7.4.10) | POST result | Mechanism changed | Residual |
|---|---|---|---|---|
| 1 CG5.1 (SECURITY) | All 4 legs (1s/2s x uring/epoll) boot each malformed file and admit an unauthenticated SET with `requirepass` cleared; Redis rejects every file (exit 1). | All 4 legs + scalar-password control pass: every malformed physical line fails the boot with Redis's `*** FATAL CONFIG FILE ERROR` banner, exact line number, line text and reason. | Config-file lines parse one physical directive at a time: a `--` inside a file argument no longer starts a new option (`src/core/config.h`, per-line `parse_config_file`); a file-only `help` is rejected; diagnostics print Redis's own reason. | Redis defers the unknown-command ACL rule in `user ...` to ACL init (its own error), checked separately. |
| 2 SV5.2 (SECURITY, CONFIG LOSS) | 16/16 restart cases fail (4 legs x db1/db16 x inline/aclfile): after REWRITE+restart a deleted user's old password still authenticates and an added user is gone; Redis 4/4 preserve the edits. | 16/16 candidate cases and Redis 4/4 pass; the restarted ACL LIST equals the pre-REWRITE registry exactly. | CONFIG REWRITE drops the file's `user` lines and writes the live ACL registry in ACL LIST form (`acl_registry_text_locked`), or none when `aclfile` owns the users, as Redis's `rewriteConfigUserOption`. | ACL grammar limits unchanged; no binary-password or redaction code touched (that is cx-rootcompat). |
| 3 SV5.1 (WRONG REPLY) | Torn INFO LATENCYSTATS replies in every leg (mixed p10/p90 lists and non-ASCII reply bytes; 2s/uring db1 also SIGSEGV); Redis clean over ~6,400 reads/leg. | All legs clean; INFO copies one complete percentile list. | The percentile side vector is rebuilt into a fresh list and swapped under `g_config_mu`, the lock INFO copies it under (`t_server.cc`). | None. |
| 4 SO5.1 (CRASH) | 0 -> N `CONFIG SET maxmemory` with one injected clock-allocation failure aborts the server (1s/uring rc -6) or answers `ERR out of memory` with the value published; Redis returns OK. | All 4 legs: CONFIG SET returns OK, no abort, server serves; the one owner that could not allocate logs a warning and its OBJECT IDLETIME reads 0. | `configure_object_idle` returns false instead of throwing and frees the partial clock; the limit/policy still apply (eviction uses the 5-bit LRU meta). **Deviation**: see note below -- a clean refuse-and-rollback needs an algorithm change, so this degrades instead of refusing. | That store's OBJECT IDLETIME reads 0 until the clock can be built; eviction and data are unaffected. |
| 5 CC5.7 (SECURITY) | `CONFIG SET requirepass ""` with the default user off admits 84-128 of ~48,000 fresh unauthenticated connections per leg (GET answered instead of NOAUTH); Redis admits 0. | 0 of ~47,700 per leg admitted; every new connection gets NOAUTH. | The requirepass admission bit is published once, from the ACL default-user recompute under `g_acl_mu`, instead of being cleared before the recompute (`auth.inc`, `acl.inc`). | None. |
| 6 SHUTDOWN ABORT (CRASH) | SIGTERM during a ~8.7 s command in the default databases-16 no-save runtime aborts (SIGABRT "worker shutdown timeout", rc -6) at ~3.8 s in all 4 legs; a 2s/epoll AOF-everysec run also lost 10 of 40 last-window acknowledged writes; Redis exits 0 after the command. | All 4 legs exit 0 after the whole command (~8.3-8.9 s waited); every acknowledged key and the in-flight command survive the AOF-everysec restart (0 missing of ~20,040). | `join_workers` restarts the worker-shutdown bound while a worker is still inside one pass (odd client-work epoch unchanged since the previous tick), as Redis waits for a running command (`multidb.cc`). | A pass that never ends still aborts after the bound. In multi-DB builds the epoch stays odd through a worker's 50 ms idle wait too, so the test means "a pass longer than one check interval"; a genuine hang that keeps cycling long passes would also delay the abort. A second SIGINT still forces exit, as on Redis. |

The witnesses are in `tests/cfgfix2.py` (cases `file`, `acl`, `latency`, `auth`,
`shutdown`, `maxmemory`), driven by the gate jobs `cfgfix2-file/-acl/-latency/-auth/-shutdown/-maxmemory`,
each running Redis 7.4.10 as the oracle in both modes and both engines. The SO5.1
case preloads `tests/cfgfix2_alloc_fail.cc`, a test-only `LD_PRELOAD` object that
fails one `ObjectIdleClock` allocation after every owner has begun building its
clock; the production binary is unchanged. PRE/POST partial-gate receipts are
under `docs/cfgfix2/receipts/`.

### SO5.1 deviation from the brief

The brief asked to "refuse the CONFIG SET with cfgfix's apply-error rollback,
leaving maxmemory at its old value". I first built that: the 0 -> N enable ran in
cfgfix's stop-the-world configuration rendezvous so a failed clock on any owner
rolled the whole family back. Measured, that regressed the maxmemory config path
and is an algorithm change, so per the brief I STOPPED and reverted it:

- `CONFIG SET maxmemory` enable latency went from 0.16 ms to ~40 ms (5 s with two
  clients), because the enable now waits for every owner to park;
- the `maxmemrace` gate row timed out at 900 s, because the enable can no longer
  interleave with a deliberately-busy owner -- the exact property that row exists
  to check;
- a code review found a hang (disabling the clock inside the rendezvous hands it
  to a read-local retire ring that waits on the parked threads) and a
  publish-before-rebind eviction side effect.

The S1 is the crash. The idle clock drives only OBJECT IDLETIME; the eviction
victim chooser reads the 5-bit LRU meta. So the smallest correct fix keeps the
existing per-fragment apply, never stops the world, and never aborts: catch the
failure, free the partial clock, keep the limit, degrade that store's OBJECT
IDLETIME to 0 with a warning. CONFIG SET maxmemory then returns OK as on Redis
(whose CONFIG SET maxmemory allocates nothing per key) and its latency is
unchanged (0.16 ms); `maxmemrace` passes in 52 s. The smallest change that would
instead refuse and restore the old value is a two-phase allocate-then-publish
protocol on the maxmemory apply path (stage every owner's clock, publish only if
all succeeded); that is an algorithm change to a hot config path and is left to
the owner.

### Arms

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/cfgfix2/arms/tomokv-PRE` | `81aa6c321760aa92568c9b4430b12274ab2ada92091e54a77d497d2293bcd329` |
| POST | `build/cfgfix2/arms/tomokv-POST` | `b525d76155ce9a141c66db38789443cb5d19b8d6285245450928305f4a196e91` |
| PAD-A | `build/cfgfix2/arms/tomokv-PAD-A` | `f97748175b3d927db7b6cb9df2e6ed1c6e757e39e91c4c4526f3617b828d363d` |

PRE `.text` is 8,924,055 bytes at 0x2cc30; POST and PAD-A are 8,926,119 bytes at
0x2cc50 (+2,064). PRE rebuilt from `build/cfgfix2/pre-source` (the exported base
tree) reproduces the PRE SHA-256 exactly. Full linker receipt:
`docs/cfgfix2/arms.json`.

Reproducibility: the Makefile embeds `git rev-parse --short=8 HEAD` and the
`src`/`Makefile` dirty flag into `info_stats.o` (INFO server `redis_git_sha1`/
`redis_git_dirty`). The POST arm was built with the item-4 rework staged, so it
embeds `a6859176` with `dirty:1`; a clean build of the identical final source
(e.g. `git checkout c1b9b4f120 && make`, SHA-256
`3ed5b2926e5cf54dabb7d64e433c1c8a01b5f90e7a4242fbab99ee1595da9347`) produces
**byte-identical `.text`, `.data` and `.bss`** -- only that INFO git-sha `.rodata`
field differs. The instruction census below (which measures `.text` execution)
and every behavioural receipt are therefore identical for either binary. PRE
embeds `bc80de80` (its own commit), built clean.

PAD-A is type **A, behaviour twin**: PRE behaviour linked at POST's `.text` start
and total size. It controls aggregate text extent only; internal function
placement and data layout remain PRE, so it is not an exact symbol-layout twin
and cannot isolate every layout effect.

### Zero cost

Serverless command-scope census (`tools/cfgfix2_counts.py`, table in
`docs/cfgfix2/instructions/table.md`): **0 added instructions in 48/48 cells**,
and all 48 counts are identical PRE to POST. GET/SET/INCR/MGET/MSET, both
namespaces (`normal`/`db0`), both modes (1s/2s), batch 1 and 32, atomic 1 (MSET
also atomic 0). The PRE census server hash is the PRE arm; the POST census server
hash is the POST arm. This is instruction accounting, not a cycles/IPC/throughput
result.

### Gate arithmetic

Six rows are collected before the quick-tier exit (`tests/gate.sh:6348-6353`,
exit at 6591): `cfgfix2-file/-acl/-latency/-auth/-shutdown/-maxmemory`, one row
each. **DQ=+6, DF=+6.** `EXPECT_QUICK=1046` and `EXPECT_FULL=1063` are untouched;
from PRE the maintainer sets **1052/1069**. No Tcl promotion or EXPECT edit was
made.

### Maintainer measurement request

Run the unchanged 14 generic cells plus 2s GET/SET at p1 and p32 with the gate's
own ABBA instrument, matched offered load and identical geometry/allocator/
keyspace; contemporaneous PRE/PRE and POST/POST nulls, PRE/POST and PRE/PAD-A.
Acceptance is no main-command regression in any cell; do not average away a
failing cell. Compare PAD-A against PRE for layout effects. This lane makes no
throughput claim.

### Verification and jobs run

All jobs ran through `tests/gate.sh`'s partial job interface
(`GATE_ONLY_JOBS`, `GATE_PROOF_NO_RATES=1`) on CPUs 32-47, ports 21800-21899,
against the Redis 7.4.10 oracle, with the candidate binary hash checked
unchanged across each run (`tools/cfgfix2_gate.py`). Receipts under
`docs/cfgfix2/receipts/`.

- Each item's PRE row fails and its POST row passes, both modes and engines:
  `pre-{file,acl,latency,auth,shutdown,maxmemory}` vs `post-lane`,
  `post-shutdown-clean` and `item4b-maxmem`.
- `post-lane` on the final POST recorded 45/47. Its two reds were
  `cfgfix2-shutdown` -- a timing false-fail: a build I was running on the same
  cores starved the ~8.7 s command so SIGTERM found none in flight; re-run with
  the box idle (`post-shutdown-clean`) all four TomoKV legs exit 0 after the
  whole command (waited 4.5-4.7 s), 0 acknowledged keys lost -- and `netcmd
  config regression`, the pre-SV5.2 "inline ACL survived rewrite" assertion the
  stopped codex lane left stale; corrected this lane and re-run green
  (`post-netcmd`, 17/17).
- Config/ACL/INFO adjacency on the final POST, all green: `config_unit`,
  `boot_grammar`, `serverfix_lines`, `serverfix_config`, `netcmd_units`,
  `authfix` (5), `auth` (7), `acl_metadata`.
- `maxmemrace` passes on the POST binary in 52 s (no stop-the-world; the
  rendezvous regression is gone); `datafix2_idle` passes; `cfgfix` still passes.
- `python3 tests/gates_test.py`: **83/83** (149 s), confirming the six new
  `collect_job` rows and `JOB_NAMES` edits keep `gate.sh` well-formed (feature
  rows precede the quick exit, independent-failure rows, instrument helpers).
- `redis_tcl` passing subset on POST: **green in both modes** (`post-tcl`, 2s
  225 s / 1s 229 s). Every config/ACL/INFO/latency file passes
  (introspection, acl, info, latency-monitor, slowlog). The per-file "1 fail"
  the raw runtest prints for `unit/type/list` and `unit/type/stream-cgroups`
  is the manifest's predeclared known setup error (list-compression config /
  appendonly setup), reconciled by `validate_passing`; no assertion count or
  skip was changed, and no Tcl promotion was made.
- The declared job list for this lane is `docs/cfgfix2/required-jobs.txt`.

### Not run in this lane (reasons)

- Full `tests/gate.sh iteration`, ABBA, NIC cells and the 18 performance cells:
  maintainer-owned; this lane makes no throughput claim.
- `flip_saturated`: its job launches `memtier_benchmark`; load generators stay
  with the maintainer.
- `tests/differ_gate.sh` (both engines) and the full AOF/snapshot/flip/multidb
  regression set: NOT RUN here. My changes are on the configuration/ACL/INFO/
  shutdown control paths, not the data path the differential exercises; these
  broad regression nets are re-run by the maintainer's whole-gate iteration,
  which the brief keeps with the maintainer. `tools/cfgfix2_units.py` builds and
  `make -q`-checks every `job_production_units` target, and
  `tools/cfgfix2_tcl_compare.py` diffs Tcl surveys, on request under the quiet-box
  schedule. (`production_units` did build green inside `post-lane` and
  `post-netcmd` as the prerequisite for `netcmd_units`.)

### Wave-14 integration notes

The integration lane merges cfgfix2 with wave 14. Overlaps to expect:

- `cx-rootcompat` rewrites the same INFO Replication section this lane leaves
  alone, changes `src/cmd/acl.inc`'s SORT-option denial and `src/core/config.h`
  inline-`user` byte handling, and binary-password/SV4.1 redaction; its ACL
  changes do not touch `acl_registry_text_locked`/CONFIG REWRITE (SV5.2) or the
  requirepass publish-once (CC5.7), but both land in `acl.inc`/`auth.inc` and
  will need a textual merge.
- `cx-clientcompat` adds a line to `refresh_live_config` in `src/core/ex_loop.h`
  next to this lane's maxmemory warning, and touches `src/cmd/command.h` and
  `acl.inc`.
- `cx-rootcore` and `cx-execfifo3` touch `src/cmd/multidb.cc` and
  `src/core/ex_loop.h`/`shard.h` respectively; neither touches the shutdown-bound
  loop or `configure_maxmemory`'s signature directly, but the files overlap.
- `src/cmd/t_server.cc` is edited by rootcompat, clientcompat and execfifo3 as
  well as this lane; all six lanes edit `tests/gate.sh`'s `JOB_NAMES` and
  collection lists, so the EXPECT arithmetic is additive across lanes.
