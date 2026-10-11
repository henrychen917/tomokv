## hexpread

The hash-expiry lost write is fixed and reproduced in both thread modes. The separate OBJECT no-touch expiry defect is also fixed. **This lane is not ready to merge: the strict requirement that only hash/expiry read bodies change is not satisfied.** The exact opcode audit reports 54 emitted bodies outside that scope. No performance result or full-gate pass is claimed.

Base: `991d48f651d3c6e1324c061bd9ea801ac085afe8`. Implementation commits: `b27ed98a1` (hash fix and regressions), `6085b4ce9` (OBJECT fix and its reproduction), `25d5e4b33` (isolated reply implementation). PRE evidence was committed first in `a1f61ed07`. All work stayed in this worktree; nothing was pushed. The task-specific request to reproduce and run correctness suites was treated as authorization for those servers. No performance benchmark or full gate was run.

**Arms and receipts.**

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/hexpread-pre/tomokv` | `b70fdd47b8e105199f9aaaf4ee318515d6667adde28d283fc75a0ed16b117d12` |
| POST, tested copy | `build/hexpread-post/tomokv` | `1ed66938ed638009b8774c444e74e1473ab53def920bf2ff2baca9e3e7a6eb6c` |
| Redis 7.4.10 oracle | `/home/user/Projects/redis74/src/redis-server` | `ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b` |

The PRE executable and object tree are retained under `build/hexpread-pre/`. POST is also `build/tomokv` at proof time. All build and correctness drivers were under `taskset -c 96-111`; server fixtures used CPUs `96-103`, 16 shards, and split ratio `6:2`. The oracle used CPU 104 and differential clients 105-111. TomoKV/Redis listener ports were 25800, 25802, 25810/25811 and 25820. The requested unmodified `gates_test.py` also ran its existing port-0 loopback socket test (`tests/gates_test.py:1466`); that transient test socket used an OS-selected ephemeral port outside the fixed service-port assignment. Its assertions were not changed. Directed fixtures explicitly disabled balancing, automatic flip, reorder and read-local; the differential fused cells independently armed and witnessed read-local.

The original aoforder probe was copied without assertion or workload changes: the only diff is port 25740 → 25800. Its original CPU mask was already 96-103. The other worktree was only read. [PRE original-probe receipts](docs/hexpread/pre-repro.json), [final correctness matrix](docs/hexpread/final/functional.json), and [final atomic batteries](docs/hexpread/final/batteries.json) contain commands, statuses, binary digests, server logs and event receipts.

**Cause and implementation.** All supplied PRE anchors were reverified, rather than assumed from the prompt:

| PRE anchor | Confirmed behavior |
|---|---|
| `src/cmd/t_hash.cc:1467` | HGET is registered `Readonly`; hash lookup chooses `store_find_read`. |
| `src/cmd/atomics_glue.inc:1015` | Read-only access to a versioned routed key gets the operation's read cut and origin, without a write clone. |
| `src/store/flatstore_atomic.inc:1112` | A foreign epoch-zero candidate is skipped and the eligible predecessor can be returned. |
| `src/cmd/t_hash_ttl.cc:429` | `reap_due(object, now_ms)` edits the returned hash and TTL table in place. |
| `src/cmd/t_hash_ttl.cc:439-441` | Last-field removal writes an unversioned AOF delete and erases using `op.hash` / `op.key()`. |
| `src/store/flatstore.h:2686` | `erase_in` looks up by key and retires the physical value, which can be the other group's candidate. |

`FlatStore::atomic_read_owns_value` checks both physical pointer identity and foreign undecided records for the key. The latter also covers a candidate parked beneath a newer physical value. A hash read of such a version enters `src/cmd/hexpread.cc`, filters expired fields in its reply, and leaves fields, TTL metadata, accounting, notifications and AOF untouched. It does not depend on the physical field-expiry attention index remaining armed. HRANDFIELD uses reply-local random state; HSCAN retains the physical cursor walk. No waits, reader retries, new runtime option, persisted format, or record-layout change was added.

The guard in `hash_ttl_on_access` also protects the HTTL/HPTTL/HEXPIRETIME/HPEXPIRETIME family, whose existing `field_live` check already filters expired fields. Write commands including HPERSIST retain their existing version-preparation and reaping behavior. When the read owns the current value, the original lazy-reap path still runs. Deferred expiry is left to existing maintenance or a later safe access.

**PRE versus POST.**

| Witness | PRE, 1s and 2s | POST, 1s and 2s |
|---|---|---|
| Held cross-owner MSET, HGET after field deadline | MSET replies OK; MGET returns `[nil,"1"]` | MSET replies OK; MGET returns `["1","1"]` |
| Original probe with AOF off / always | All four cells reproduce the tear | All four pass; AOF-on replay and restart retain both values |
| Parked reply matrix | Physically reaps the predecessor | Expired fields hidden; expiry counter and notifications unchanged during hold |
| Deferred reaping after held RENAME | Early `hexpired,del`, counter 0→1; later expected notifications absent | Later safe HGET reaps exactly one field and emits `hexpired`, then `del`; AOF reload agrees |
| OBJECT IDLETIME with persistent predecessor and expired RENAME candidate | GET returns `old`, OBJECT returns nil, `expired_keys` 0→1 | OBJECT reports predecessor idle time; `expired_keys` unchanged |

The eight added rows fail on PRE and pass on POST. Each arm starts with fresh state, witnesses at least two installed entries, requires an unanswered group and a live pre-deadline read, and allows at most three fresh re-arms for a missed deadline. There is no successful skip. In the PRE deferred rows, the eventual receive timeout is **missing deferred notifications after the witnessed premature reap**, not an unarmed deadline: both receipts record early `hexpired,del` and `expired_hash_fields` 0→1.

The reply row checks HGET, HMGET, HGETALL, HEXISTS, HLEN, HSTRLEN, HKEYS, HVALS, HRANDFIELD (positive/negative counts and WITHVALUES), HSCAN (COUNT/MATCH/NOVALUES), and all four read-only TTL commands. It covers complete/partial field expiry, compact/expanded hashes, RESP2/RESP3, and attention-index armed/disarmed cases.

**Other lazy-expiry reads audited.**

| Path | Verdict |
|---|---|
| GET-family through `FlatStore::find` (`flatstore.h:1240`) | No candidate erase found. Pending records use `atomic_resolve`; `atomic_live_value` (`flatstore_atomic.inc:1236`) performs logical key-TTL filtering without deletion. |
| MGET through `atomic_find_tracked` | Same resolver protection; ordinary cross-shard bodies are byte-identical to PRE. |
| OBJECT ENCODING / REFCOUNT | Use the regular read lookup; no physical candidate deletion found. |
| OBJECT IDLETIME / FREQ | **Confirmed defect, fixed separately.** The raw `find_no_touch` → `find_without_touch` path could call `live_or_expire` on the physical candidate. `objectpread.cc` now resolves at the read cut first when records exist. PRE/POST IDLETIME reproductions are retained; FREQ shares the same lookup branch. |
| RANDOMKEY (`random_live`, `flatstore.h:1843`) | Pending-record branch resolves versions; physical lazy expiry is restricted to its no-pending branch. |
| SCAN / KEYS / rehash visitation (`flatstore.h:2533`) | The reap callback checks `atomic_has_record` before physical expiration. |
| Active key expiry / active hash-field expiry (`flatstore.h:1577`, `:1616`) | Both skip recorded keys; no change needed. These remain safe deferred-reaping points after retirement/promotion. |
| Set / sorted-set / list readers | No per-element TTL or read-side collection reaper found. Key TTL uses the shared version-aware lookup. Pop, trim and other removal commands are writes. |
| Stream readers / trimming / PEL cleanup | No read-only TTL reaper found. XADD/XTRIM/XAUTOCLAIM and group-state mutations are write paths. |
| SORT hash-field dereferences | `hash_field_value_ro` plus `hash_ttl_field_lapsed` filters without field/key deletion. The existing minimum-deadline cache accessor can refresh cache metadata; that is not a demonstrated candidate-erasure path and was not changed. |
| Read-local GET/MGET probes | Logical string expiry only; no physical reaper. Hash commands fall back to owner execution. |
| PFCOUNT cached cardinality | Explicit `SnapshotWrite` preparation; not an unversioned lazy-expiry read. |
| WATCH/SWAPDB direct no-touch caller | Administrative transaction/write preparation, not the OBJECT read path; unchanged. |

One adjacent notification concern remains visible in the source audit: `find_notify` inspects the physical candidate's deadline before its version-aware `find`. It can therefore consider an expired foreign candidate for an `expired` notification even when the returned predecessor is live. That is a notification-only concern, not another confirmed physical deletion; it was not claimed fixed or dynamically proved in this lane.

**Proof status.**

| Required check | Result / receipt |
|---|---|
| `make all` | Pass, [final build log](docs/hexpread/post-build-final.log) |
| Every `job_production_units` target | 29/29 named targets built successfully and all 29 `make -q` checks returned 0; the two `mdbqsbr-live-arms` builds are recorded in [build receipt](docs/hexpread/final/builds.json) |
| Hash TTL differential | 48/48 comparison legs: hexpire/edgetime/hash × seeds 7/19/20/23 × modes 1s/2s × atomic 0/1; two additional armed-fused witnesses pass. [Split](docs/hexpread/final/differ-split.log), [fused](docs/hexpread/final/differ-armed-fused.log). |
| Ordinary notifications and INFO | 32 target observations across both modes, atomic 0/1, compact/expanded, RESP2/3, partial/final-field expiry match the eight [Redis oracle observations](docs/hexpread/common-oracle-resp3/common.json). Exactly `hexpired`, then `del` only on final-field expiry; `expired_hash_fields` matches Redis `expired_subkeys`; `expired_keys` stays unchanged. |
| Atomic batteries | Torn/window (including release assertions), RYOW/mixed-write, owner-local hazards: all six pass; both shutdowns exit 0. |
| `python3 tests/gates_test.py` | 66/66 pass, plus its nested 14/14 checks. No assertions changed. [Log](docs/hexpread/final/gates-test.log). |
| Eight layout locks | All compile unchanged: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob&lt;64&gt; 192, AtomicEntry 144, Config 624. [Locations](docs/hexpread/final/layout-locks.json). |
| GET/SET/MGET/MSET ordinary bodies | Pass. All bodies in both namespaces' `t_string.o`, `t_string_notify.o`, `xshard.o`, and `main.o` are identical under the relocation-aware opcode comparison. |
| Only hash/expiry read bodies may change | **FAIL: 54 outside-scope emitted bodies.** [Summary](docs/hexpread/final/identity/summary.json), [every changed function](docs/hexpread/final/identity/changed-functions.md), [machine-readable inventory](docs/hexpread/final/identity/changed-functions.json). |
| Full gate | Not run. The source-label fixture agrees at 650 rows but intentionally refuses the unchanged EXPECT_FULL=642. [Diagnostic](docs/hexpread/final/ledger-fixture.log). |

The opcode method is the `docs/ttlclean` / `ccfix_audit.py` method, preserving opcodes and resolved relocation targets, including TLS/local-data/function-address targets. No error-callee equivalence or instruction masking was enabled. The inventory covers 16,562 emitted object-file bodies, including the two added units; 219 differ or are added. The outside-scope changes include hash writers, snapshot helpers, storage helpers and CONFIG/shutdown helpers. Compile-only inlining trials were retained under `docs/hexpread/budget*.log`; no trial is presented as a performance result, and no speculative compiler-budget override was added to the Makefile. This failure needs resolution before accepting the lane.

Earlier failed/transitional receipts are retained. The first POST split deferred-notification check exposed a subscriber barrier race in the new harness; positive notification checks now receive their required messages before draining. The first RESP3 oracle run exposed missing verbatim-string decoding in the new client; that parser was corrected. An intermediate isolation build omitted the new source from the link and failed; the final build includes it in both server and storage-unit source lists. Final acceptance receipts are exclusively under `docs/hexpread/final/` and use the POST digest above.

**Gate accounting.** `job_hexpread` declares three hash rows plus one OBJECT row for each of two modes. Its `collect_job hexpread` is at `tests/gate.sh:3620`, before the quick-tier exit at line 3734. Therefore **DQ=+8, DF=+8**. The maintainer should change `EXPECT_QUICK` **625→633** and `EXPECT_FULL` **642→650**. Neither constant was edited. The explicit label fixture was updated with exactly those eight labels; it is source inventory, not execution evidence.

**Measurement request, after opcode isolation is resolved.** Use the retained PRE/POST binaries, CPU mask 96-111 only, eight server CPUs 96-103, clients 104-111, 16 shards, split ratio 6:2, both modes, and ports in 25800-25899. Run the gate's own matched-offered-load ABBA instrument serially on the quiet box; no concurrent builds. No PAD arm is supplied or named: no object/record layout changed, and this is a correctness candidate with an unresolved opcode-scope failure, not a claimed layout optimization.

| Cells | Arms / controls | Deciding evidence |
|---|---|---|
| Ordinary GET, SET, MGET, MSET | PRE/POST; atomic 0/1; depth 1 and 128; notifications off | Matched offered-load rate, latency, cycles/op, instructions/op and IPC. Require no regression; identical command bytes alone are not a rate result. |
| HGET/HMGET/HGETALL/HLEN and HSET | PRE/POST; no field TTL versus armed field TTL; compact/expanded; atomic 0/1 | Same metrics, with lazy-reap counts matched. This checks the added predicted branch and compiler spillover into hash writers. |
| Safe field expiry with notifications/AOF | PRE/POST; notifications `Egh`; AOF off and always; partial/last-field expiry | Preserve replies, exactly timed `hexpired`/`del`, expired counters and AOF replay; compare cost at equal expiry work. |
| Parked-version hash reads | POST correctness/latency only; witnessed held group and expired fields | No premature physical expiry, no torn group, bounded completion without waiting for commit. PRE is a failing correctness control, not a valid throughput competitor for this cell. |

`size` reports text+read-only-data 8,639,725→8,690,874 bytes (+51,149), data +32, BSS unchanged. [Raw size receipt](docs/hexpread/final/binary-size.txt). No rate, IPC, cycle, or amortization gain is inferred from this change.
