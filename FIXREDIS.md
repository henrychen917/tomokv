# Redis bindings / MSETNX investigation — 2026-09-10

## Result and limits

**Keep the parameter bindings. Fix the abandonment test's guard connection.** The quoted
`reply=1` failure is reproducible on clean mainline with eviction disabled: MSETNX commits
because its finite snapshot excludes a newer guard written by another connection. It is not
evidence that an *aborted* candidate was returned. A real abandonment leak instead occurs in
the deliberately broken control with `reply=0`; the corrected test detects it.

This is a test-fixture correction, **not a claimed production atomicity repair**. The original,
unstimulated gate sequence produced **0/10 target failures on each arm** in this investigation.
The directed experiment reproduces the exact reported row/signature, but the original event
had no captured tickets/window state, so its historical cause cannot be established conclusively.
I cannot honestly supply a parameter-source subpatch that creates this failure only on the
branch: removing *all* bindings still reproduces it, and adding them to clean mainline does not
change the directed result. That is the negative result of the requested source narrowing,
not a successful branch-specific bisection. There is no evidence here to deprecate the binding
approach or to justify changing the eviction engine as its fix.

## Frozen arms and allocation

Both `HEAD` and `origin/cpp` resolved to `c8e61f64628655bf99acb91cd986684e5c608fde`.
The older context commit `78c3e5391` was not substituted for this matched base. Fresh detached
worktrees were created inside this worktree's ignored `build/fixredis/` directory:

| Arm | Contents | Binary SHA-256 |
|---|---|---|
| `base-clean` | Unmodified `c8e61f646`, including its tests | `1f80d7959bc23d6b39d2147c412bd85869dfcb2600d7aa2dd72450a7dca924c4` |
| `bindings-clean` | Same base plus only the eight-file `src/` binding patch | `287d32e52ffa7fe729eac4d1f2dddc59824f7fdce21e538d77362bddcb505416` |
| `no-abort-filter` | Bindings arm plus the diagnostic deletion described below | `86f95e945f5ee3f129104d7be4f0e86dd012bac5fb52edd3e49ad2a5190c7f90` |

Frozen source patch SHA-256:
`4699b033c27b09d5473b168bc145941be82412b91bf8c500a43f658476c43e6c`.
Build commands, source hashes, layouts and binary hashes are in
[`clean-build-provenance.json`](build/fixredis/clean-build-provenance.json).
Builds used `taskset -c 112-119 make -j8`. No diagnostic production change was copied back.

The final allocation superseded the prompt's earlier cores 8–31 instruction. Every split
server used **eight cores, `--shards 16 --ratio 6:2 --atomic 1 --enable-debug-command yes`**.
Ordinary comparisons used server 64–71 / driver 96–103 / port 9800; directed probes used
72–79 / 104–111 / 9802; final batteries used 80–87 / 120–127 / 9806. The focused binding
suite used server 80–87 / driver 112–119 / ports 9804–9805. Fused boots used eight cores
and `--thread-mode fused` instead of the incompatible `--ratio` option. Harnesses inspected
actual worker affinity masks. Only owned PIDs were stopped; no pattern kills or full gate ran.

All timing and occurrence-rate samples are **TRIAGE measurements on a concurrently used NPS1
box**. The protocol replies, counters and assertions below were directly verified. These
counts do not establish a rare-failure bound or a quiet-box performance result. The RYOW
battery's existing `--no-rate-assertions` option suppressed its speed comparison only;
all correctness checks ran. No throughput/latency improvement or sub-7% margin is claimed.

## Reproduction and two-direction narrowing

The ordinary sequence was `atomic_torn.py --release-build`, then `atomic_ryow.py
--no-rate-assertions`, without rebooting between the two, as in the gate. Each repeat had a
fresh server. The target row remained green even when the preceding drain battery failed.

| Ordinary gate-sequence cohort | Base target failures | Binding target failures |
|---|---:|---:|
| Saved original binaries, worktree's initial helper experiment | 0/5 | 0/5 |
| Fresh complete builds, unmodified base tests | 0/5 | 0/5 |

The fresh-build cohort's separate `atomic_torn` timeout/drain failure occurred on base **2/5**
and bindings **1/5**. It is not counted as target reproduction and was not repaired here.
The initial worktree's unrelated `atomicwindow.py` experiment failed its reconfiguration
witness **5/5 on each binary**; restoring that file to HEAD removes this experiment from
the delivered patch. Its previous contents are preserved as `build/fixredis/atomicwindow-before.py`.

The directed experiment pins an old empty MGET cut, installs DEL tombstones, and then holds
one owner's commit between ticket reservation and publication. A guard SET on the other
owner completes while the safe watermark is held back. Counters must prove that window
opened; the holder and reader must both drain with their expected replies.

| Directed setup on fresh servers | Clean base | Base + all source bindings |
|---|---:|---:|
| Two-key probe: foreign guard yields committed MSETNX (`1`, candidates) | 5/5 witnessed | 5/5 witnessed |
| Same probe: writer's own guard forces rejection (`0`, guard/absent) | 5/5 witnessed | 5/5 witnessed |
| Exact original eight-key abandonment row with that window added | **3/3 FAIL**, `seq=0 reply=1`, `reads=2` | **3/3 FAIL**, same signature |
| Exact row with only the guard moved to its writer | **3/3 PASS** | **3/3 PASS** |

This supplies both directions for the *test correction*: on the bindings server, restoring
the original foreign guard restores the failure; applying just the corrected guard to clean
mainline removes it under the same witnessed window. For the *binding source*, the requested
causal distinction is refuted by these arms: subtracting the entire source patch leaves the
directed failure present, and adding that patch to clean mainline leaves the same result.
No smaller binding hunk was assigned an unsupported causal verdict.

Logs: `build/fixredis/auditprobe/{base,bindings}-2s-{1..5}/` and
`build/fixredis/auditprobe/fresh-{original,corrected}-{base,bindings}-2s-{1..3}/`.
The latter scripts preserve the original row, adding only the common arming wrapper and
the seven-line guard correction. An earlier attempt ran both variants on one server and
contaminated the second variant's empty-cut fixture; that `exact-*` cohort is excluded.
Early `cut-*` probes that never armed are likewise excluded, not reported as passes.
Historical `build/diffdiag/` results were inspected but are not included in these counts.

## Mechanism

1. `scatter_engine.inc:1929` captures MSETNX's safe read cut. Its existence preflight at
   line 2706 uses that context.
2. A recorded key's plain SET obtains a ticket through `begin_plain_version`
   (`atomics_glue.inc:51`). Another outstanding commit can hold the safe watermark below
   that ticket (`server.h:2584–2607`). The guard's own connection can read its acknowledged
   value while a foreign finite-cut operation still excludes it.
3. `flatstore_atomic.inc:1085–1098` deliberately admits own-connection versions beyond the
   cut, while excluding newer foreign versions. Thus the original **admin** SET did not
   establish the mandatory rejection that this test assumed.
4. With the guard excluded, no owner rejects MSETNX, so `scatter_engine.inc:3739` selects
   integer `1` and queues a real commit. The candidate values are then committed values.
   The aborted branch at line 3727 instead selects integer `0`.

The directed probes recorded positive `atomic_commit_windows` and `atomic_commit_holds`
deltas, and **zero evictions**. `maxmemory=0` and `maxmemory-policy=noeviction` were verified.
Both bindings already existed unchanged in base. The new hash/zset thresholds retain their
default values; HLL initialization runs before workers; Unix permissions and AOF recovery
are inactive on these TCP/no-AOF boots. DWARF comparisons preserve existing Config offsets
(maxmemory 328, policy 336, atomic 344) and this checkout's **528-byte** Config lock.
The context's older 624-byte lock was not reintroduced.

## Changes and validation

- [`tests/atomic_ryow.py`](tests/atomic_ryow.py): create `c` before the guard, require its SET
  acknowledgment, and issue the guard SET through `c`. The 256 attempts, concurrent foreign
  reader, exact rejected reply, exact own values, foreign absence checks and nonzero read
  count are retained. This uses the project's RYOW contract without adding foreign ordering.
- [`tests/redisgap_atomic.py`](tests/redisgap_atomic.py): preserve the manual directed
  reproduction and a separate installed-before-abort check. It verifies retained tombstones,
  commit-window movement, zero eviction, candidate installation and a foreign reader's
  exclusion counter. Four fresh-state attempts are the maximum; no witness means failure.
  Cleanup attempts every disarm and connection close even if one cleanup command fails.
- Restore `tests/atomicwindow.py` to HEAD, removing the unrelated failed experiment.
- Keep every existing source binding and `tomokv.conf` change. **No parameter is left unbound.**
  This includes hash/zset listpack thresholds and their aliases, HLL sparse limit, AOF
  truncated-load policy and Unix socket permissions. Boot-only controls remain boot-only.

The negative-control worktree deletes only these two lines from
`atomic_resolve_internal`'s `consider` lambda in `flatstore_atomic.inc`:

```cpp
if (owner.group_epoch && owner.group_aborted &&
    owner.group_aborted->load(std::memory_order_acquire)) return;
```

All other abandonment logic remains intact. The corrected ordinary RYOW battery fails
**3/3** against it, each at `seq=0 reply=0` with an abandoned value in the own MGET. The
manual diagnostic also fails **3/3** specifically after proving candidate installation and
foreign exclusion. The corresponding manual diagnostic passes **3/3 on clean base and
3/3 on bindings**. After the cleanup robustness review, an additional fresh run of each
arm reproduced both passes and the expected negative-control failure (`reviewed-*` logs).
This verifies that moving the guard does not hide a genuine leak.
Negative-control patch/provenance: `build/fixredis/no-abort-filter-only.patch` and
`build/fixredis/no-abort-filter-provenance.json`.

Final-tree `atomic_ryow` **and** `atomic_hazards` pass **5/5 fresh split boots and 5/5 fresh
fused boots**. The focused binding suite passes in both modes: **12 successful boots and
20 expected startup rejections**, covering aliases/grammar, actual hash/zset promotion,
HLL thresholds, Unix permissions, rewrite/restart, and strict/permissive AOF recovery.
See `build/fixredis/final-bindings-*`, `redisgap-bindings-result.json`, and the detailed
affinity/boot log under `redisgap-bindings/boots.json`.

No gate row was added or retired: the new diagnostic is manual. `tests/gate.sh` and its
`EXPECT_QUICK=325` / `EXPECT_FULL=342` constants are untouched and need no count change.
Python compilation and whitespace checks pass for the changed source/tests/config.
The automatically written `CODEX-OUT.md` has unrelated whitespace diagnostics and was
not edited as part of this fix.

The saved launchers make repeat runs reproducible, for example with an unused label:

```sh
taskset -c 120-127 python3 build/fixredis/run_post.py \
  --arm repeat=build/fixredis/bindings-clean/build/tomokv \
  --tests tests/redisgap_atomic.py --repeats 3 --port 9806
```

The maintained diagnostic itself takes `HOST PORT` and never launches or stops a server.
For a new build, run it against a fresh DEBUG-enabled server at the documented gate geometry.

## Separate static eviction findings

These paths predate the bindings and were **not dynamically reproduced**. They are reported
because they can violate the ownership/lifetime laws, not offered as the cause of this row:

- `scatter_engine.inc:2779` admits and installs a shard's candidates individually before
  publishing the pending group. Admission of a later key can select an earlier installed
  candidate, whose still-unlinked group is invisible to the linked-record eviction exclusion.
  The group retains that candidate's `stable_object`. This needs a dedicated finite-maxmemory
  lifetime test; the observed maxmemory-zero failure cannot exercise it.
- `FlatStore::choose_victim` excludes `atomic_has_record`, but plain `make_room_for`
  (`flatstore.h:2431`) lacks atomic admission's additional `atomic_needs_version` exclusion.
  An intent-only cross-owner script key may therefore be evicted without the version its
  reservation requires. This also needs an independent finite-maxmemory investigation.

Neither existing maxmemory surface was unbound or modified to conceal these findings.
No claim of exhaustive eviction/atomicity verification, a green full gate, or quiet-box
performance acceptance follows from this test correction.
