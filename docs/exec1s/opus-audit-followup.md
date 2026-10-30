I'm Claude Opus 5.5 (`claude-opus-5-5`), running at maximum reasoning effort. All four repairs are in place and correct at HEAD `5d019214a`. I found no remaining production defect in them. I only read files: nothing was built, run, delegated or edited.

I audited the working-tree files at that HEAD (confirmed via the worktree reflog, lines 112–113, and the loose ref `refs/heads/cx-exec1s`). They match `repair.diff` except for one stale test hunk, covered under evidence below.

## Verdict

| Item | Repaired? |
|---|---|
| C1 – tag collision | **Yes** |
| C2 – overlapping write on the read-local byte | **Yes** |
| C3 – stale published statistics | **Yes** |
| C4 – WATCH-first participant order | **Yes** |

Beyond the code, I found one small build-rule gap (test infrastructure, no production impact) and several test limitations. I'm not claiming any candidate build, gate row or proof passed.

## C1 – tag collision
- **Change:** `WakeSent` is now 20 (`src/net/uring.h:78-79`), so the kinds in use are 1–17 and 20. `fliplisten.cc:10` asserts it differs from the private tags 18 and 19.
- **No other collisions:** the only other private kind in the tree is the literal 18 at `shutdown.cc:73`, which is the same value as fliplisten's accept tag. No table is indexed by kind, and nothing else builds a tag with `<< 56`.
- **Failure path now harmless:** if a kind-20 completion ever reached `IoLoop`'s default arm (`io_loop.h:1165,1217`; `reorder.cc:1788,1840`), `fliplisten_cqe` would return at `fliplisten.cc:205`. The executor's dispatcher ignores unknown kinds (`ex_loop.h:2798-2809`), and the rewrite to `Wake` is unchanged (`uring.h:420`).

## C2 – overlapping write on the read-local byte

**Layout.** The bytes are `read_local_extended` at 1316, `group_installing` at 1317, `group_records` at 1318, padding at 1319 and `cleanup_fast` at 1320. Size, little-endian, adjacency and the 1316 offset are all `static_assert`ed (`atomic_mvcc.h:165-172`).

**The helper (`atomic_mvcc.h:154-162`) is legal C++.**
- The struct is standard-layout, and `offsetof` is used where the class is complete.
- It copies exactly two bytes. With the flag at 1, adding 0xFF yields flag 0 (a valid `false`) and a count incremented modulo 256.
- 1316 is a separate memory location, and the compiler may not introduce a store to it.

**The flag is always 1 on entry.**
- Each install sets the flag (`flatstore_atomic.inc:493`).
- Publish aborts unless the entry has installed keys (`:525`), and discard aborts if it has (`:467`, `:889`).
- Both publish sites are synchronous loops with no publish in between (`scatter_engine.inc:3020-3057`, `atomics_glue.inc:318-352`).
- An entry's `group` pointer is set only when it is prepared (`:446`, `:908`).

**Counter maintenance is balanced.**
- *Increments:* a group entry is linked only by `atomic_publish_group` (`:526-527`). The two plain-entry links (`:706`, `:721`) assert the entry has no group (`:696`, `:713`).
- *Decrements:* all three unlink loops (`:1768-1769`, `:1882-1883`, `:2058/2065`) go through `atomic_unlink_conn`, which decrements only for group entries (`:1193`). Nothing else edits the list.
- *Safety rule:* `atomic_may_have_blind_records` returns true if the count is nonzero or 256+ records are live (`:268`). Group records can't exceed live records, so below 256 live a zero count means zero group records. The `uint8` decrement wraps without undefined behaviour.

**Concurrent readers.**
- The foreign probes (`flatstore.h:761,793,802`, via `flatstore_atomic.inc:1015-1023`) load only byte 1316.
- The two group bytes are read only on the owner: the blind-scan guard (`:268`, called from `multi.inc:1389`) and the eviction check (`:597`).

**TSAN test.**
- `tests/exec1s_word.cc` uses the real helper in the passing leg and the old 4-byte write in a forked child.
- `tsan_unit` (`gate.sh:5287-5305`) fails the row on any report or non-zero exit. The child's expected report goes to a separate file, so it doesn't trip that check.
- The stack frames in both control logs match the current source line numbers.

## C3 – stale published statistics
- **Fix:** the MULTI owner path calls `publish_size()` unconditionally (`ex_execute.inc:66`), and `publish_size()` stores only changed fields (`storesize.cc:10-30`).
- **Every executor variant is covered:**
  - `execute_multi_unit` has one caller (`ex_execute.inc:58`).
  - That file is included in all three executor bodies (`ex_loop.h:2393,2400`; `latency_tracking.cc:417`).
  - Retry passes reach it through `execute_resumed`.
- **The test runs the real production path:** `exec1s_unit.cc:54-60` and `:322-347` drive the actual executor, the real EXEC/EXPIRE handling and line 66.
- **The test discriminates:**
  - The published expiry count is written only at `storesize.cc:24,35`.
  - Every other `publish_size` caller is off this path: active expiry, snapshot, batch end, FLUSH, AOF and snapshot load.
  - The executor has no destructor that publishes.
  - With the old guard (key count 1 equals published count 1), the assertion at `exec1s_unit.cc:344-345` must fail.
- **Limitation:** the test exercises only the non-fused executor, with a single-owner EXEC rather than a cross-owner retry fragment. That's sufficient, because line 66 runs before every result branch.

## C4 – WATCH-first participant order
- **Order restored:** command participants are added at `multi.inc:1143`, then WATCH-only participants at `:1153`. Both happen before the `database_watch` resize (`:1155`), `prepare_claims` (`:1158`) and allocation sized by slot count (`:1159`). This matches the pre-X5 baseline (pre-source `multi.inc:1050`, then `:2158`/`:2421`).
- **No early lookup:** nothing indexes a slot for a WATCH-only shard before line 1153. The only slot use in the command loop is `:1147`, on participants just added. `add_write_key` and the child-binding helpers don't touch slots.
- **Later re-adds are no-ops:** at `:2292` and `:2555`, `ensure_state_slot` returns the existing slot and `add_shard` de-duplicates (`:660-662`). The EXECABORT path creates its slots before allocating (`:2255-2257`).
- **Claim-only slots and the 255 sentinel:**
  - Claim-only slots are still created only in `prepare_claims` (`:883`, `:886`).
  - The sentinel rule (`:842-851`) is unchanged, and `nshards ≤ 256` is enforced (`server.h:289`, `config.h:1074,1509`).
  - The reorder changes only which shard receives slot 255.
- **Checked, not a problem:**
  - `:1160` now counts WATCH-only shards when deciding whether a read-only EXEC needs a read cut; pre-X5 (pre-source `:1063`) didn't.
  - However, that flag's only consumer is the dispatch check at `:2376-2377`, which already counts WATCH-only shards, exactly as pre-X5 did (pre-source `:2242-2243`).
  - So the read-cut decision is identical.
- **DEBUG hooks:** the lead-shard hooks (`:1852`, `:2404`) again pick a command participant. `exec1s_unit.cc:170-180` asserts the order and would fail with WATCH first.

## Test limitations and minor gaps
1. **The "…retires" assertions can't fail** (`exec1s_unit.cc:232`, `:245`, and the new `:272`).
   - Fixture teardown calls `release_records`, which ends in `atomic_destroy_pending()` and sets the pending state to null (`flatstore_atomic.inc:1139`, called from `:2078`). The guard then returns false through its null check.
   - So the 256 decrements across the wrap are verified by code inspection only.
   - The 256-group check itself is meaningful: `witnessed()` at `:270` with live == 256 on a fresh state implies a wrapped count of zero.
   - Possible fix: before teardown, collapse some of the groups (or a subset), then assert the guard state with 1–255 records live. Or read the count through the existing test friend (`flatstore.h:3675-3677`).
2. **Build rule gap (the one infrastructure issue).**
   - `Makefile:742` lists only `src/store/*.h` and `src/base/*.h`, but `kvobj.h:34` pulls in `src/net/resp.h`, which pulls in `src/exec/op.h` and `resp3.h` (`resp.h:18,761`).
   - So the gate's `make -q` readiness check (`gate.sh:5364,5371`) can accept a stale TSAN binary after edits there.
   - Low impact: the tested layout is asserted and comes from `src/store`.
3. **TSAN build flags:** the TSAN binary is built at `-O1` without production flags. It proves the source-level access width; production code generation is guaranteed by the memory model but not observed directly.
4. **Unchecked precondition:** the helper's "flag is 1" precondition isn't asserted. It holds today. If it were ever violated, the flag byte would become 0xFF (read at `:597`) and the count wouldn't advance, which would endanger the D3 fast exit. An optional debug-only check would cover it.
5. **C1's `static_assert` covers `WakeSent` only:** a future enumerator equal to 18 or 19 wouldn't be caught.

## Evidence and provenance
- **`repair.diff` is stale for one hunk.** Its 256-group loop passes `std::string` values to `key_on(…, const char*)` (`atomic_survivors_unit.cc:91`), which fails to compile (`post-opus-root-build.log:257-273`). The tree has the fixed version at `exec1s_unit.cc:255-258`, and `post-opus-root-build-attempt-2.log` shows no errors. I couldn't read git objects to confirm which version is in the commit's blob.
- **`build/exec1s-evidence/audit-directed/` already holds results for the runs described as pending.** It agrees with the analysis above, but it carries no source or binary hash, so it's not a receipt:
  - 12 directed unit runs and `word` exit 0.
  - The rebuilt TSAN control reports the race.
  - The old-guard control (copy in `build/exec1s/publication-old-guard`, changed only at `ex_execute.inc:64`) fails 4/4 at the expected assertion.
- **Freshness:** these predate the repair and need regenerating with the candidate if they're in the acceptance set:
  - `docs/exec1s/freshness.json` (13:42Z) doesn't list `build/exec1s-word-tsan`.
  - The POST MSET instruction counts in `command-counts.json` were taken before the C2/C3 hot-path edits.
- **C5 and C6:** C5's two invariants are unchanged and still safe (`multi.inc:1155-1158`, `:911-919`). C6 is acknowledged in `rules.md:16`.
- **Out of scope:** execfifo, owner D1–D4, LAT-OFF-EXEC-1 and X4. I also didn't re-audit unchanged features or the PRE receipt.
