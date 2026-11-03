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
| 6 SHUTDOWN ABORT (CRASH) | SIGTERM during an 8.5-8.7 s command in the default databases-16 no-save runtime aborts (SIGABRT "worker shutdown timeout", rc -6) 3.82 s after the signal in all 4 legs, with and without AOF; the 2s/uring AOF-everysec leg also lost 8 of its 20,040 acknowledged writes (40 written in the final everysec window) across the restart; Redis exits 0 after the command (`pre-shutdown`). | All 4 legs exit 0 after the whole command (8.2-8.8 s waited); every acknowledged key and the in-flight command survive the AOF-everysec restart (0 missing of 20,024-20,043) (`item6-shutdown`). | `join_workers` restarts the worker-shutdown bound while a worker is still inside one pass (odd client-work epoch unchanged since the previous tick), as Redis waits for a running command (`multidb.cc`). | A pass that never ends still aborts after the bound. In multi-DB builds the epoch stays odd through a worker's 50 ms idle wait too, so the test means "a pass longer than one check interval"; a genuine hang that keeps cycling long passes would also delay the abort. A second SIGINT still forces exit, as on Redis. The witness signals a fixed 0.3 s after sending the command, so a starved server can be signalled before the command starts (a false fail, seen once with a build on the lane's cores). |

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
  `pre-file`/`pre-acl`/`pre-latency`/`pre-auth` vs `post-lane`; `pre-shutdown`
  vs `item6-shutdown`; `pre-maxmemory` vs `item4b-maxmem`. Two committed
  witnesses differ from the revision their PRE receipt ran: item 6 (corrected
  back to the receipted revision, see below) and CC5.7, whose probes later
  gained an RST close (`a685917614`) to avoid TIME_WAIT across ~48k
  connections. That changes only how the client closes each probe, not the
  server's admission check, and `post-lane` passes it on POST; a PRE run of
  the final CC5.7 witness is listed under Not run.
- `post-lane` on the final POST recorded 45/47. Its two reds were
  `cfgfix2-shutdown` -- a timing false-fail: a build I was running on the same
  cores starved the server, so SIGTERM (0.3 s after the command was sent) found
  nothing in flight and the server exited after 0.11 s; re-run with the box idle
  (`post-shutdown-clean`) all four TomoKV legs exit 0 after the whole command
  (waited 4.5-4.7 s), 0 acknowledged keys lost. Both runs used the interim
  lighter witness corrected below -- and `netcmd
  config regression`, the pre-SV5.2 "inline ACL survived rewrite" assertion the
  stopped codex lane left stale; corrected this lane and re-run green
  (`post-netcmd`, 17/17).
- Item-6 witness correction (final commit of this lane). The interim lighter
  witness (TomoKV 300k / Redis 6M start members, 3.5 s calibration floor) was
  never run on PRE, and on a box fast enough to calibrate it at 3.5-4.1 s PRE
  would finish the command before its abort (3.82 s after SIGTERM, which lands
  0.3 s into the command) and pass. The committed witness restores the start
  sizes `pre-shutdown` and `item6-shutdown` ran (400k / 4M) and raises the floor
  to 5.0 s (>= 0.88 s margin). Against the code that produced those receipts the
  only executable change in the case is that threshold, and every calibration
  step they recorded (TomoKV 8.49-8.68 s at 400k; Redis 4M doubling to 8M at
  6.22-6.74 s) decides the same under 5.0 s, so they are this witness's PRE-fail
  and POST-pass proof. It was not re-run here because the arm binaries were
  removed with `build/` (note at the end). The row's runtime returns to about
  490 s (lighter witness: about 250 s).
- Config/ACL/INFO adjacency on the final POST, all green: `config_unit`,
  `boot_grammar`, `serverfix_lines`, `serverfix_config`, `netcmd_units`,
  `authfix` (5), `auth` (7), `acl_metadata`.
- `maxmemrace` passes on the POST binary in 52 s (no stop-the-world; the
  rendezvous regression is gone); `datafix2_idle` passes; `cfgfix` still passes.
- `python3 tests/gates_test.py`: **83/83** (149 s), confirming the six new
  `collect_job` rows and `JOB_NAMES` edits keep `gate.sh` well-formed (feature
  rows precede the quick exit, independent-failure rows, instrument helpers).
- `redis_tcl` passing subset on POST: **green in both modes** (`post-tcl`, 2s
  225 s / 1s 229 s). Its 37 files include the configuration-facing ones
  (`unit/introspection` with CONFIG SET/GET/REWRITE, `unit/introspection-2`,
  `unit/latency-monitor`, `unit/slowlog`, `unit/info-command`), all passing.
  The subset has no `unit/acl`, `unit/info` or `unit/auth` file, so ACL and
  auth (items 2 and 5) are covered only by the `cfgfix2-acl`/`cfgfix2-auth`
  witnesses and the `authfix`/`auth`/`acl_metadata` jobs. The raw per-file
  fail counts (`unit/type/list` 1, `unit/type/list-3` 1,
  `unit/type/stream-cgroups` 1, `unit/scripting` 2) are exactly the manifest's
  named `known_setup_errors` -- unsupported `CONFIG SET list-compress-depth`,
  `aof-use-rdb-preamble no` and `DEBUG SET-DISABLE-DENY-SCRIPTS` -- which
  `validate_passing` requires to match by command, reply and count; those
  CONFIG SET error replies still match byte for byte, so this lane changed no
  CONFIG SET error grammar. The manifest and `tests/redis_tcl.py` are unchanged
  from PRE; no assertion count or skip changed and no Tcl promotion was made.
- The declared job list for this lane is `docs/cfgfix2/required-jobs.txt`.

### Not run in this lane (reasons)

- PRE runs of the final `cfgfix2-auth` (RST-close probes) and
  `cfgfix2-shutdown` (restored sizes, 5.0 s floor) witnesses: the arm binaries
  were removed with `build/` before these corrections; regenerate PRE (note at
  the end) and run both rows on it -- each must fail.
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

### Note added 2026-11-02 ~16:58 -- arm binaries removed with build/

After this report was delivered, the endgame cleanup removed this worktree's
gitignored `build/` (as it did for the finished `cx-cfgfix`; running lanes kept
theirs), so the three arm binaries listed under **Arms** no longer exist on
disk. Everything committed is intact: receipts, census, `docs/cfgfix2/arms.json`
(SHA-256s and `.text` extents for verification) and this report. To regenerate
(same absolute paths reproduce the SHA-256s exactly; elsewhere compare `.text`/
`.data`/`.bss`, since `-g` paths and the INFO git-sha differ):

- POST: a clean `make` of `c1b9b4f120` in this worktree gives `3ed5b292...`
  (`.text`/`.data`/`.bss` identical to `b525d761`); server source is unchanged
  from `7f06b7ca54` to HEAD, so a clean HEAD build has the same `.text`.
- PRE: export `bc80de80b` to `build/cfgfix2/pre-source` and `make` there (the
  recipe that reproduced `81aa6c32` exactly).
- PAD-A: then `python3 tools/cfgfix2_pad.py` (reads `build/cfgfix2/pre-source`
  and `build/tomokv`, writes `build/cfgfix2/arms/tomokv-PAD-A`).
