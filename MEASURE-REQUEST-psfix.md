# psfix — PS5/PS7 persistence compatibility; PS6 closed

Worktree `/home/user/Projects/cx-psfix`, branch `cx-psfix`. Started at
`7213a9405`; merged `origin/cpp` by fast-forward to `b1d931ee2` before editing.
PRE is that merge-base. No push. No benchmark or performance measurement was run.
The explicitly requested correctness runs use only CPUs 112–127.

## Redis reference and scope

Read round3-read/persist.md rows PS5–PS7 (lines 231–233). The local vanilla oracle is
Redis **7.4.10**, commit `f103d127`, `/tmp/claude-1000/redis74/src/redis-server`, SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.
Redis sources: [config.c](https://github.com/redis/redis/blob/7.4.10/src/config.c)
(local lines 1819, 3091), [server.c](https://github.com/redis/redis/blob/7.4.10/src/server.c)
(local Persistence lines 5757–5805), and [rdb.c](https://github.com/redis/redis/blob/7.4.10/src/rdb.c)
(local lines 1640, 3983).

**Semantic distinction explicitly retained from the task:** `rdb_saves` counts
completed successful snapshot saves here, excluding failed saves and AOF rewrite
bases. Redis 7.4 increments this counter on accepted SAVE/BGSAVE attempts, including
attempts that later fail. The task specifically requested completed saves; this
lane does not claim equality of counter values on failures. An optional clarification
was offered; the explicit completed-save scope was used.

| Item | Redis 7.4 behavior | PRE | POST and exact bytes |
| --- | --- | --- | --- |
| PS5 | Mutable case-insensitive `yes`/`no`; applies to next AOF load | `CONFIG SET aof-load-truncated no` gives `-ERR parameter is immutable at runtime\r\n` | SET `no`/`yes` gives `+OK\r\n`; GET below. Numeric `0`/`1`, `true`, empty and trailing-space values are rejected byte-exactly against Redis. |
| PS7 names | `aof_rewrites`, `aof_rewrites_consecutive_failures`, `rdb_saves`, `loading` | First two misspelled; last two absent | Renamed, no aliases. Added `rdb_saves:0\r\n` initially and `loading:0\r\n` after boot. A completed first snapshot yields `rdb_saves:1\r\n`. |
| PS6 | No TomoKV `load` knob; fallback recovery is a TomoKV boot contract | docsregen already removed the nonexistent knob and explicit-load sentence; prose explained fallback | **CLOSED.** Made `dbfilename` row explicit at docs/CONFIGURATION.md:152; fallback prose lines 170–172. No `load` row or “Snapshots need explicit --load” sentence remains. |

Exact CONFIG GET replies (RESP2):

```text
*2\r\n$18\r\naof-load-truncated\r\n$2\r\nno\r\n
*2\r\n$18\r\naof-load-truncated\r\n$3\r\nyes\r\n
```

RESP3 uses `%1\r\n` instead of `*2\r\n`. Invalid boolean values return:

```text
-ERR CONFIG SET failed (possibly related to argument 'aof-load-truncated') - argument must be 'yes' or 'no'\r\n
```

Duplicate parameters use Redis's `duplicate parameter` error, preserving the
second requested spelling. Invalid boolean errors use the canonical name, as Redis does.

The live value stays in the existing mutex-protected CONFIG table. Recovery reads
it once, falling back to parsed startup configuration before that table exists.
Both legacy and manifest recovery use it; older increments remain strict. CONFIG
REWRITE already serializes this table. No ordinary write/read operation consults it.

INFO still emits every other previous field: **33 → 35 fields**, exactly two
renames plus two additions. Shared fields follow Redis order, including
`loading`, RDB changes/in-progress/last-save/saves, then AOF status/rewrites/failures,
then current size before base size. The counter is a process-wide atomic in the
snapshot module, read only by INFO and written at init/successful finalization.

Updated existing consumers in tests/aof_rewrite_triggers.py and
 tests/edgetime_persist.sh, plus obsolete immutable expectations in tests/knobs.py
and tests/redisgap.py. Remaining old strings in tests are deliberate PRE/no-alias
negative assertions. There is no calib directory in this worktree; external
`/home/user/Projects/calib` top-level text consumers have no matches. Old source
copies in its separate `harness-*` worktrees and historical binaries were inspected
but not edited (own-worktree rule).

## Validation

- `tests/differ.py psfix`: **8/8 protocol legs PASS**, 27 byte/property checks per
  leg (RESP2/RESP3 × 1s/2s × databases 1/16), against harness-owned fresh Redis
  processes. All 15 shared Persistence names and their order are checked with an
  explicit required set; missing fields and aliases fail. Logs:
  [2s](docs/psfix/oracle-2s.log), [1s](docs/psfix/oracle-1s.log),
  [2s/16 DB](docs/psfix/oracle-multidb-2s.log), [1s/16 DB](docs/psfix/oracle-multidb-1s.log).
- Each target performs two SAVE and one BGSAVE per protocol; each completed save
  increments once, and an INFO read does not increment. `loading` must be 0.
  A forced failed SAVE leaves the counter unchanged; the successful retry advances
  once. A completed AOF rewrite advances `aof_rewrites` while leaving `rdb_saves` unchanged.
- PRE negative control **PASS (expected rejection)**: immutable SET differs from
  Redis; old INFO names are present and `loading`/`rdb_saves` are absent.
  [Evidence](docs/psfix/pre-control.log).
- Existing `tests/aof.py loadaof` now arms a real three-byte incomplete tail,
  requires CONFIG `no` to refuse it unchanged, and CONFIG `yes` to recover and
  truncate exactly those bytes, then byte-verifies the full dataset.
- Python syntax checks, shell syntax check, and `git diff --check`: PASS.
- Selected persistence gate: **RUNNING; final result will replace this line.**

The gate command is:

```bash
GATE_ONLY_JOBS='persistfix_units aof-epoll aof-uring aof_frame snapshot-epoll snapshot-uring' \
  taskset -c 112-127 tests/gate.sh iteration \
  --server-cores 112-119 --load-cores 120-127 --load-smt '' \
  --ports 24680-24739 --candidate-binary "$PWD/build/psfix/POST/tomokv"
```

The selected jobs include the existing eight `AOF in-window {kill,term} recovery
({1s,2s}, {epoll,uring})` rows. Correctness geometry remains eight server cores,
16 shards, ratio 6:2. The gate supplies build prerequisites. No ABBA/NIC or full
receipt is claimed for this partial run.

**Rows: +0 quick / +0 full.** The new differential suite is discovered inside the
existing full-tier differential matrix, and the live policy check extends the
existing AOF byte-exact row. Existing persistence jobs are collected before the
quick-tier exit (currently line 3276). Neither EXPECT constant nor any fixture
was edited. EXPECT remains 497 quick / 514 full.

## Byte/instruction and layout audit

`python3 tools/psfix_artifacts.py build/psfix/PRE build/psfix/POST docs/psfix`
completed successfully. It uses the existing lbstall byte/relocation tooling plus
the established four-byte TLS relocation extension. Resolved symbol, target and
addend identities remain checked; changing a callee is not masked.

- **16,824 function pairs inspected** across both database namespaces.
- **1,211/1,211 ordinary command bodies identical** after relocation normalization;
  1,192 are raw object-byte identical, and the other 19 differ only in address
  displacements. Every ordinary body has identical byte length and instructions.
  Only CONFIG and INFO command bodies change (including their cold clones).
- Stock hot audit: **1,482/1,482 identical**, 1,480 raw-byte identical, two with
  address displacement differences only.
- All existing field offsets and type sizes match PRE. Locks in both namespaces:
  Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
  AtomicEntry 144, Config 624. AofManager 976; SnapshotManager 792/528;
  Server 108736/108352 (namespaced/db0). No member-layout PAD is needed.
- Four compiler-only inlining limits in Makefile preserve PRE bodies in the two
  edited translation units; no runtime knob or per-operation check is added.

Full evidence: [audit.json](docs/psfix/audit.json),
[hot-bodies.json](docs/psfix/hot-bodies.json), [audit.log](docs/psfix/audit.log).
All changed existing bodies follow; full signatures and both destructor ABI
symbols are retained in audit.json. The helper copies below are reported explicitly,
not counted as identity passes outside the ordinary/hot audited inventories.

| Object | Body | PRE → POST bytes | Reason |
| --- | --- | ---: | --- |
| `db0/src/cmd/t_server.o` | `cmd_config` | 7618 → 7553 | CONFIG validation/helper inlining |
| `db0/src/cmd/t_server.o` | `cmd_config [cold]` | 123 → 123 | CONFIG validation/helper inlining |
| `db0/src/cmd/t_server.o` | `init_config` | 7897 → 7881 | PS5 mutable registration |
| `db0/src/cmd/t_server.o` | `collect_config_updates` | 8628 → 8848 | PS5 exact boolean/duplicate error grammar |
| `db0/src/cmd/t_server.o` | `collect_config_updates [cold]` | 147 → 181 | PS5 exact boolean/duplicate error grammar |
| `db0/src/cmd/t_server.o` | `cmd_info` | 16161 → 16293 | PS7 field names/order and new cold counter reads |
| `db0/src/cmd/t_server.o` | `cmd_info [cold]` | 349 → 369 | PS7 field names/order and new cold counter reads |
| `db0/src/cmd/t_server.o` | `void reply_map_header<Op::Sink&>` | 381 → 593 | Compiler-generated helper copy in changed cold translation unit; included in full inventory |
| `db0/src/cmd/t_server.o` | `kvobj_external_bytes` | 1463 → 1606 | Compiler-generated helper copy in changed cold translation unit; included in full inventory |
| `db0/src/cmd/t_server.o` | `command_client_disconnected` | 689 → 689 | Connection/migration code relocation targets |
| `db0/src/cmd/t_server.o` | `command_client_migration_reserve` | 393 → 393 | Connection/migration code relocation targets |
| `db0/src/persist/aof.o` | `AofManager::~AofManager` | 1435 → 1435 | Cold teardown code generation / relocation targets |
| `db0/src/persist/aof.o` | `AofManager::~AofManager` | 1435 → 1435 | Cold teardown code generation / relocation targets |
| `db0/src/persist/aof.o` | `aof_read_recovery` | 6570 → 6522 | PS5 reads the current policy once per load |
| `db0/src/snapshot/snapshot.o` | `SnapshotManager::complete_file_success` | 342 → 358 | PS7 increments after successful non-rewrite save |
| `db0/src/snapshot/snapshot.o` | `SnapshotManager::init` | 2025 → 2025 | PS7 resets process save counter at initialization |
| `db0/src/snapshot/snapshot.o` | `snapshot_type_hooks` | 221 → 221 | Cold hook-table relocation targets |
| `db0/src/snapshot/snapshot.o` | `FlatStore::make_room_for` | 1546 → 1524 | Compiler-generated helper copy in changed cold translation unit; included in full inventory |
| `src/cmd/t_server.o` | `cmd_config` | 7671 → 7613 | CONFIG validation/helper inlining |
| `src/cmd/t_server.o` | `cmd_config [cold]` | 123 → 123 | CONFIG validation/helper inlining |
| `src/cmd/t_server.o` | `init_config` | 7897 → 7881 | PS5 mutable registration |
| `src/cmd/t_server.o` | `collect_config_updates` | 8600 → 8956 | PS5 exact boolean/duplicate error grammar |
| `src/cmd/t_server.o` | `collect_config_updates [cold]` | 147 → 210 | PS5 exact boolean/duplicate error grammar |
| `src/cmd/t_server.o` | `cmd_info` | 16215 → 16341 | PS7 field names/order and new cold counter reads |
| `src/cmd/t_server.o` | `cmd_info [cold]` | 353 → 369 | PS7 field names/order and new cold counter reads |
| `src/cmd/t_server.o` | `command_client_connected` | 1812 → 1812 | Connection/migration code relocation targets |
| `src/cmd/t_server.o` | `command_client_disconnected` | 689 → 689 | Connection/migration code relocation targets |
| `src/cmd/t_server.o` | `command_client_migration_extract` | 864 → 864 | Connection/migration code relocation targets |
| `src/cmd/t_server.o` | `command_client_migration_install` | 645 → 645 | Connection/migration code relocation targets |
| `src/cmd/t_server.o` | `command_client_migration_reserve` | 393 → 393 | Connection/migration code relocation targets |
| `src/cmd/t_server.o` | `cfg_client_output_buffer_limit_string[abi:cxx11]` | 5268 → 4600 | Cold CONFIG/DEBUG helper inlining |
| `src/cmd/t_server.o` | `void reply_int<Op::Sink>` | 462 → 673 | Compiler-generated helper copy in changed cold translation unit; included in full inventory |
| `src/cmd/t_server.o` | `Server::flipctl_debug_dump[abi:cxx11]` | 2430 → 2288 | Cold CONFIG/DEBUG helper inlining |
| `src/persist/aof.o` | `AofManager::~AofManager` | 1467 → 1451 | Cold teardown code generation / relocation targets |
| `src/persist/aof.o` | `AofManager::~AofManager` | 1467 → 1451 | Cold teardown code generation / relocation targets |
| `src/persist/aof.o` | `aof_read_recovery` | 6810 → 6746 | PS5 reads the current policy once per load |
| `src/persist/aof.o` | `aof_read_recovery [cold]` | 297 → 297 | PS5 reads the current policy once per load |
| `src/snapshot/snapshot.o` | `SnapshotManager::complete_file_success` | 342 → 358 | PS7 increments after successful non-rewrite save |
| `src/snapshot/snapshot.o` | `SnapshotManager::init` | 2025 → 2025 | PS7 resets process save counter at initialization |
| `src/snapshot/snapshot.o` | `SnapshotManager::start` | 5605 → 5639 | Cold snapshot compiler inlining |
| `src/snapshot/snapshot.o` | `snapshot_type_hooks` | 221 → 221 | Cold hook-table relocation targets |
| `src/snapshot/snapshot.o` | `kvobj_external_bytes` | 986 → 826 | Compiler-generated helper copy in changed cold translation unit; included in full inventory |
| `src/snapshot/snapshot.o` | `FlatStore::make_room_for` | 2049 → 2188 | Compiler-generated helper copy in changed cold translation unit; included in full inventory |

Inventory changes: both variants add `command_aof_load_truncated`, `find_config`
(outlined), `std::string == const char*` (outlined), and `snapshot_completed_saves`.
The db0 `Compact::capacity_bytes` and namespaced `FlatStore::maybe_start_shrink`
standalone copies disappear through compiler inlining; their exact inventory is in audit.json.

## Frozen binaries and mainline measurement request

| Arm | SHA-256 | .text bytes |
| --- | --- | ---: |
| `build/psfix/PRE/tomokv` | `ccc77ec229919df474122fadb11602f418f46f970f480a15d9376f4231e256fe` | 7782988 |
| `build/psfix/POST/tomokv` | `65ebd0960fca2f1b00753b59cd2529a1454d523e1bf02f4c41c00c6894c1661c` | 7783516 |

`build/tomokv` is byte-identical to POST. .text grows **528 bytes**, entirely
accounted for by the cold changes and compiler-generated helper copies above.
No performance claim follows from the instruction proof; mainline must judge the
text/address-placement null at matched offered load. No PAD arm is requested.

Use the existing 14 cells in `docs/lbplanner/generic-cells.txt`, SHA-256
`de0e56e4696f780543c5adea21aa7d7283c12fa22110be6064370a69a2a68dc6`:
`h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`.
Offline `--list-cells` confirms 14 and no pending pins; [inventory](docs/psfix/null-cells.json).

Maintainer only, on the scheduled quiet box, using the gate's instrument:

```bash
python3 tests/abbagate.py --cells docs/lbplanner/generic-cells.txt --subset full \
  --build-reference 0 --reference-binary build/psfix/PRE/tomokv \
  --candidate-binary build/psfix/PRE/tomokv --collect-null 1 \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --ports 24680-24689 --output build/psfix/null
python3 tests/abbagate.py --cells docs/lbplanner/generic-cells.txt --subset full \
  --build-reference 0 --reference-binary build/psfix/PRE/tomokv \
  --candidate-binary build/psfix/POST/tomokv \
  --null-result build/psfix/null/results.json \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --ports 24680-24689 --output build/psfix/comparison
```

Keep each cell's existing depth-1 latency/rate scoring, load pins, 512 connections,
atomic=1, overlap=1, reorder=0, default balancing and save disabled. Report matched
rate, cycles/op, instructions/op and IPC per cell. Acceptance: every POST cell stays
inside the fresh matched same-binary envelope, including latency cells. No aggregate
may hide a losing cell. Both the PRE/PRE null and PRE/POST comparison are **PENDING
MAINLINE**, not run by this lane.
