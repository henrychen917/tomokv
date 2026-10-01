cleanup-iotemplates — 2026-10-02

The three unused IO dispatch switches are removed, with every remaining caller policy preserved. **PRE/POST are NOT byte-identical. Landing requires the mainline-controlled null.** The independent **PAD-A behavior twin matches POST's complete production code and layout**, and the additional **PAD-B inverse control matches PRE**. Builds and serverless checks passed. Live correctness, the gate, performance, and landing are **PENDING MAINLINE**. No server, benchmark, load generator, performance measurement, gate run, or push was performed.

Worktree/branch: `/home/user/Projects/cx-cleanup-iotemplates`, `cx-cleanup-iotemplates`. At launch HEAD was staging commit `5b3d9c4292bf8b332d493beb485266ecc5a289aa`; `origin/cpp` had advanced eight commits to **2a9e484035960b0ba5925824cc581148c359c0f8**. The required first merge fast-forwarded to that reference. **PRE is this merged launch reference**, as required by the launch notes, not the older staging binary. PRE was built and archived before source editing. Production substitution: `5bd61cca9`; witnesses/controls: `6a5e9c0af`, `62b946457`; complete test-caller coverage: `876d9330a`.

Builds used `taskset -c 112-127 make -j16`. All offline inspection/checks stayed on CPUs 112–127. Two existing fixtures require exactly eight allowed CPUs; their successful runs used **112–119**, within that allocation. No other worktree was edited.

**Verified diagnosis and scope.** Anchors below refer to frozen PRE unless explicitly marked POST. The supplied audit was rechecked rather than applied by its old line numbers.

| Item | Launch evidence | Disposition |
|---|---|---|
| Ordinary dispatch signature | `src/core/io_loop.h:2909–2913`; generated declaration `:5770–5774` | Remove positions 4–6 only; old position 7, `SplitLocal`, becomes explicit position 4 |
| Fused capability calculation | `io_loop.h:2916–2918` | Substitute the three inventoried false values; retain `SplitLocal || (BatchOps == kGenthreadIfidBatchOps && !IoPipe)` |
| Private-queue lambdas / ROB | `io_loop.h:2928–2949`, `:3012` | Retain ordinary queue operations and `rob.acquire<true>` in the existing Fused arm; ordinary split retains `acquire<false>` |
| MULTI dispatch alternative | `io_loop.h:3606–3610` | Retain `multi_dispatch_entry`; remove only its discarded private-queue alternative |
| Per-operation active marking | `io_loop.h:4292–4298` | Retain the mark on every ordinary operation; remove the false suppression policy and obsolete comment |
| Duplicate marking helper | `io_loop.h:4436–4449` | `mark_active_known` rejects true statically and duplicates `mark_active` for false; substitute the existing helper |
| Retire / fused completion plumbing | `io_loop.h:433–438`, `:4519–4553`; `genthread.cc:169`; `rl2s.cc:198` | Remove vacuous targeted arguments; retain lifetime guards, serve enqueue, and marking |
| Uncalled MULTI IO wrappers | `src/cmd/multi.h:47,50`; `multi.inc:1827,1917`; friends `io_loop.h:478,489` | Delete both declarations/definitions/friends; retain implementation and executor/scatter/blocking/masked-queue templates |
| Active generator | `tests/r7shadow_sync.py:4,17–21,99–116`; generated fallback `reorder.cc:2123–2124` | Change the delegation signature and regenerate through this script |
| Separate park mismatch | normal poll `io_loop.h:610`; park `:739` | **Preserve `!SplitLocal` at park**; do not replace it with `Fused` |

These three switches are **uninstantiated interface residue**, not an unimplemented safety mechanism being discarded. Every instantiated IO value is false; the targeted helper explicitly forbids true. Suppression's surviving branch still marks each operation. The two wrapper roots have no reachable callers, although their out-of-line definitions emitted real code before removal. The retained MULTI implementation templates and live executor private-queue machinery are not classified as dead.

The park mismatch is a **separate latent instantiation defect**: an ordinary split park can pass a different Fused policy than normal polling. Its correctness is not established here. POST preserves it at `io_loop.h:736`, with normal polling at `:607`; the generated copy is preserved too. **This cleanup's measured landing is the prerequisite for the separate iopark lane. Neither cleanup arm includes the park correction.** No additional correctness-law conflict was identified in the touched paths; this is not a whole-engine concurrency audit.

**Complete caller inventory.** Frozen raw searches and structured records are `build/cleanup-iotemplates/frozen/caller-inventory.txt` and `io-callers.json`. The 52 original C++ parser call sites comprise:

| File | Ordinary calls | Generated R7 calls |
|---|---:|---:|
| `src/core/io_loop.h` | 16 | 0 |
| `src/core/reorder.cc` | 1 fallback | 16 |
| `tests/reorder_engagement_unit.cc` | 7 | 5 |
| `tests/core_concurrency_unit.cc` | 2 | 0 |
| `tests/l4prebuild_unit.cc` | 2 | 0 |
| `tests/multidb_boundary_unit.cc` | 2 | 0 |
| `tests/wb_rule_phase_unit.cc` | 1 | 0 |
| Total | 31 | 21 |

The generator's explicit fallback is additionally inventoried as the source of that generated call. Both declarations and the definition are checked. The MULTI friends were enumerated separately. There are **42** targeted-mark calls (23 ordinary-header, 19 generated), **eight** retire-collection calls (five ordinary, three generated, all default false), and **five** fused-completion calls (header one, genthread one, rl2s one, generated two, all explicitly false).

The multidatabase boundary test's multiline seven-argument call is updated explicitly; its last argument remains `!Fused && ReadLocal`. The engagement test's true SplitLocal calls are likewise preserved. The new membership fixture adds two parser call sites. `tools/iotemplates_proof.py policies` discovers original callers from the frozen Git tree rather than relying on a selected-file list.

POST's authoritative parser is `io_loop.h:2907–2908`; ordinary marking is `:4409`, retire collection `:4484–4485`, and fused completion `:433`. Generated definition/fallback are `reorder.cc:2116–2121`; stamping remains `:3454`; the generated declaration is `io_loop.h:5735–5737`. Generator delegation/stamping remain in `tests/r7shadow_sync.py`. `multi.h:46,48` and `multi.inc:1823,1909` retain the ordinary entries. No handwritten generated implementation was introduced.

`run_fused` pipeline selection, CQ switches, active-set policy, R7 split entry trees, pointer lifetime/drain barriers, ownership/migration, MVCC, QSBR, RYOW, and reply ordering are unchanged. No knob, field, cache-line split, per-pass clearing, or speculative hot-path optimization was added. All layout/offset assertions compiled in both namespaces: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624.

**Build and dependency evidence.** `Makefile:39–47` links **42 normal + 42 db0 objects**. All 84 were rebuilt and compared, including every declared wildcard dependent. There is no separate IO or MULTI translation unit: IO is included by its callers; MULTI's implementation is in `xshard.o`.

The compiler dependency graph identifies nine includers in each namespace: `main`, `cmd/xshard`, `cmd/acl`, `cmd/t_server`, `cmd/climon`, `cmd/tracking`, `core/genthread`, `core/rl2s`, and `core/reorder`. These **18** transitive dependents and all **66** other declared dependents are in the audit. `frozen/object-inventory.json` records every object, exact argv, and raw dependency path; `reproducibility.json` normalizes relative include paths for the readable includer list.

PRE and POST used the same workspace, relative source/output paths, GCC 13.3.0, default release flags `-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, jemalloc, and unchanged per-TU compiler budgets. **All 84 compile commands, the link command, and all 84 compiler dependency graphs agree.** The 995 resolved dependency paths were hashed before editing; changes resolve only to the six edited production source/header files. Raw `.d` files are under `frozen/deps/` and `POST-deps/`. Compiler/assembler/linker hashes and environment are frozen; subsequently resolved compiler/link inputs and their pre-freeze timestamps are recorded separately in `frozen/resolved-link-inputs.json`. No compiler budget, Makefile flag, or link order was tuned to obtain these results.

Production, ordinary serverless, R7 witness, and additional caller builds completed with **zero warnings and zero errors**. `build/tomokv` equals the archived POST file. Actual live boot/transport behavior remains **PENDING MAINLINE**.

**Raw identity evidence.** All paths below are relative to this worktree. Each arm contains all 84 objects plus the linked executable under `artifacts/`, a SHA-256 manifest, raw `objdump -drw`, `readelf -W -h -l -S -s -r`, `nm -anSC`, every executable section's bytes/metadata, raw allocated relocation-section dumps, resolved relocation targets, and allocated symbol addresses under `dumps/`. Neither opcode bytes nor displacements are normalized in the ELF verdict.

| Arm | Binary under `build/cleanup-iotemplates/` | SHA-256 |
|---|---|---|
| PRE: exact merged launch source | `PRE/artifacts/tomokv` | `a29133d9b21317d391e5b6e319b0953f7927770fdd2196f99f1cf3f813c68b6d` |
| POST: this cleanup | `POST/artifacts/tomokv` | `ed2927ebeec3ef80515edb8d309738ae1bef258209fe0dc5083e3fd1f939c42b` |
| PAD **(A): behavior twin**, PRE behavior / POST layout | `PAD-A/artifacts/tomokv` | `942be5e65f87b52049a842d83e50583f1dcf6b85301125c13aed568381b22809` |
| PAD **(B): inverse control**, candidate behavior / PRE layout | `PAD-B/artifacts/tomokv` | `fddd26d19387a476a921935c24b501cd8b9eddefd985d9848e94ce15f430d093` |

| Code size, bytes | PRE / PAD-B | POST / PAD-A |
|---|---:|---:|
| Linked `.text` | 7,564,433 | 7,561,825 |
| All linked executable sections | 7,574,265 | 7,571,657 |
| All executable object + linked sections | 8,594 sections / 19,664,449 bytes | 8,574 sections / 19,651,311 bytes |
| Linked entry point | `0x4dc10` | `0x4dc10` |

`identity.json` reports **74/85 matching artifacts**, correctly failing overall. Ten objects change executable code; the linked image also changes. Every `.text` and executable `.text.*` section is covered, including renamed/removed section inventories. The complete per-object table is `summary.json`; changed-object executable totals are:

| Object | PRE | POST |
|---|---:|---:|
| normal `main.o` | 717,188 | 716,961 |
| db0 `main.o` | 717,775 | 718,005 |
| normal `genthread.o` | 635,751 | 635,102 |
| db0 `genthread.o` | 638,064 | 637,964 |
| normal `rl2s.o` | 797,435 | 797,382 |
| db0 `rl2s.o` | 801,267 | 800,419 |
| normal `reorder.o` | 733,870 | 732,957 |
| db0 `reorder.o` | 734,279 | 733,871 |
| normal `xshard.o` / MULTI | 633,595 | 629,799 |
| db0 `xshard.o` / MULTI | 634,632 | 630,866 |

The removals eliminate both nine-byte wrapper roots per namespace, their previously emitted true MULTI specializations, and the duplicated targeted marking body. Template identities and relocation targets change. GCC also changes instruction scheduling, outlining/inlining, and COMDAT choices in surviving large translation units; unchanged flags do not imply unchanged code. For example `noop/032.diff` retains calls redirected from the duplicate marker to `mark_active`, while `noop/022.diff` records changed instructions/internal branches in the otherwise source-unchanged executor loop. Subsequent linked addresses and displacements move. All other production objects, including both string-command objects, match the strict ELF comparison.

The retained `r7shadow_noop.py`/`reorder_noop.py` diagnostic reports **305/368 equal bodies**, **FAIL** overall: 36 envelope, 20 dispatch, five scheduler, and two multi-key bodies differ. The symbol adapter maps only the three known false parser arguments and false retire argument; true alternatives remain distinct, with negative self-checks. It does not map the changed marking target away, excuse changed instructions, or replace the raw-byte verdict. No instruction-count or performance claim is inferred from these diagnostics.

**Independent controls.** `tools/iotemplates_proof.py pad-a` starts from `frozen/reference.tar`. It explicitly propagates the inventoried false IO parameters while retaining PRE's constexpr-dead arms, uses the existing identical ordinary marker, removes the vacuous helper argument plumbing, and marks the two uncalled wrapper definitions inline so they emit no roots. It regenerates using the archived active R7 generator with the adapted delegation signature. It copies no candidate implementation body. Eighteen includers are rebuilt with frozen commands; 66 unchanged objects come from PRE; the frozen link command is used. Source and logs remain in `PAD-A-source/` and `PAD-A-source-proof.json`.

`identity-PAD-A-POST.json` passes **85/85**: every executable/allocated byte (except the documented debug-dependent GNU build ID), relocation target, section layout, program header, and entry point matches. All **10,000 defined function symbol entries / 8,790 unique function names** have the same addresses/sizes. All 3,786 linked relocations and 10,602 allocated symbol records match. Thirty-five existing zero-size `%=` marker names differ only in numeric spelling with identical attributes/addresses; no function identity or executable byte is relaxed. This is the required complete POST function-address-table match, not footer padding.

Because `.text` changes by **−2,608 bytes**, PAD-B is also supplied. It starts from the candidate archive and applies the recorded inverse mechanical substitution, restoring precisely the unused false-policy/template/wrapper source residue. This unreachable source acts as inverse padding while preserving candidate behavior; every restored production source is checked against PRE. It is independently rebuilt and linked, not a copied PRE binary relabelled as PAD. `PAD-B-inverse.patch` and `PAD-B-source-proof.json` record the construction. `identity-PAD-B-PRE.json` passes **85/85**, including all **10,016 function entries / 8,805 unique function names**, exact PRE text size/layout, 3,786 linked relocations and 10,618 allocated symbols.

`identity-PRE-PAD-A.json` and `identity-PAD-B-POST.json` both correctly fail, **74/85**. A pure cleanup's independently derived behavior twin can have POST's exact code; that does **not** discharge PRE/PAD-A or PRE/POST performance parity. PAD-A/POST and PAD-B/PRE have code-null proofs. No existing R7 PAD is used as this cleanup's layout control.

**Assertions and negative controls.** All new runtime assertions use fresh in-memory fixtures, with no listener or worker loop. Incomplete-frame entry is deterministic: withhold exactly the last frame byte, assert NeedInput/no dispatch, then supply it. An unentered state fails; nothing skips or widens a tolerance.

| Exercised state / assertion | Throwaway omission or bypass | Exact failure / result |
|---|---|---|
| All 52 original parser call sites; remaining transport/Fused/SplitLocal/Coded policies | Drop the final true SplitLocal at an actual engagement caller | Compile fails in both namespaces: named caller `Fused/SplitLocal/Coded and transport policies`; positive 52 × 128 contexts × two namespaces compiles |
| Removed parameters, marker helper, and two wrappers | Reintroduce each of the six forbidden interfaces separately | Six inventory rejections naming the restored interface |
| Every source/test caller has at most four IO arguments | Restore a seven-argument test call | `obsolete IO call arity` |
| Generated declarations/definitions stay authoritative | Alter the copied generated stamp body by hand | `stale R7 envelope`; unmodified copy passes |
| Incomplete frame is actually entered | Feed the whole frame instead of withholding its last byte | `iotemplates incomplete frame entered without dispatch or active membership` |
| Completing the frame advances parsing / publishes one ROB op | Omit the real ordinary parser's cursor advance | `iotemplates completed frame made parser progress` |
| Dispatched frame belongs to the active set | Omit the ordinary dispatch tail's real `mark_active` | `iotemplates dispatched frame has active membership` |
| Repeated marking/completion deduplicates membership and requests serving | Bypass dedupe; separately omit completion serve enqueue | Both fail `iotemplates active membership is deduplicated` |
| Dead client enters neither active nor serve set | Bypass dead guard in marker; separately bypass completion dead guard | Both fail `iotemplates dead client never enters active or serve set` |
| Completed frame reaches exactly one owner task | Pretend the actual queue push succeeded without posting | `iotemplates completed frame posted exactly one owner task` |
| Fixture requeue succeeds | Force refusal before the queue call | `iotemplates requeue owner task` |
| Owner execution and ordered retirement progress | Omit actual owner drain; separately omit actual ROB retirement | Both fail `iotemplates owner progress and ordered retirement` |
| Armed R7 tasks retain their shadow stamps | Remove `shadow_dispatch.stamp(t)` from a separately compiled generated object | Existing witness fails `dispatch shadow stamp count/PAD/FIFO witness` |
| Linked executable bytes are compared literally | Flip one `.text` byte in an inspection-only copy | `executable .text: bytes differ` |
| Executable subsections are also covered | Flip one byte in a copied genthread `.text.*` | Named subsection `bytes differ` |
| Equal opcode bytes cannot hide relocation changes | Change one executable-section relocation addend | `allocated relocation targets differ` |
| Linked function addresses are independently checked | Move one function symbol value | `allocated symbol addresses/identities differ` |

Results: **nine source/policy controls**, **12 runtime controls**, and **four ELF controls**, all rejected as intended. Runtime controls return exactly 1 with the named assertion, not an accidental crash. Receipts/logs: `source-controls/`, `runtime-controls/`, `elf-controls/`, and `policies/`. The byte-corrupted files have mode 0600, names ending `.NEVER-RUN`, and were never executed. Controls exist only in generated trees under this worktree's `build/`.

The production link contains **96 actual boot-loop specializations**, identical inventories across all four arms: per namespace 40 ordinary loops (16 plain split, eight fused, 16 split/read-local) plus eight generated fused loops, spanning all Unix/TLS/epoll Boolean combinations. Overlap chooses the retained split pipeline 0/1 and fused pipeline 0; read-local/reorder capability decisions remain unchanged. The caller witness extracts the real Fused expression and ROB coded-acquisition expression, and checks every original call across 128 Boolean/batch contexts in both namespaces. Boot/transport/writeback argument lists and the preserved park expression are also checked against PRE.

The extended engagement suite passes on **PRE, POST, PAD-A and PAD-B**, in normal and db0 namespaces, with **byte-identical textual traces across arms**. Its new membership cases cover 24 mode × read-local × overlap × raw reorder 0/1/−1 combinations per namespace: **192 successful new fixture cases across four arms**, alongside existing parser/shadow/order/demotion/database witnesses. Normal database dispatch uses 16 databases; db0 uses one. PRE/PAD-B test sources receive only the old-signature adapter. Both database-boundary modes/read-local states and both writeback parser-quantum cases also pass.

Additional serverless results: core concurrency `drain` and `route`; config parser; flip controller; reorder and R7 units; both split R7 witnesses (eight cells and eight forbidden-path/transient-allocation controls per namespace); signal accounting source/idle/R7 checks; all four L4 prebuild mode/read-local fixtures; **57/57 gate-harness tests**, including the nine-script invariant. The boundary/L4 fixtures initially rejected 16 allowed CPUs at their existing exact-eight-core precondition; they passed on 112–119 without source/tolerance changes. Both logs are retained. All reported production/test builds have zero warnings/errors.

Existing R7 shadow-disabled and FIFO-disabled **serverless test** copies pass in both namespaces under `r7-capability-fixtures/`; these exercise the retained PAD fallback and capability gates. Their receipts explicitly label them as test fixtures, **not cleanup PAD arms**. No new live assertion/control was introduced. Existing live feature/mode equivalence, read-local admission, FLIP state/load, TLS pipeline/coexistence, and instrumented gate batteries remain **PENDING MAINLINE**.

Offline replay examples (from this worktree; these never start a server):

```bash
taskset -c 112-127 python3 tests/r7shadow_sync.py
taskset -c 112-127 python3 tools/iotemplates_proof.py policies
taskset -c 112-127 python3 tools/iotemplates_proof.py source-controls
taskset -c 112-127 python3 tools/iotemplates_proof.py controls
taskset -c 112-127 build/reorder-engagement-unit on shadow
taskset -c 112-127 build/reorder-engagement-unit-db0 on shadow
taskset -c 112-127 build/signalacct-core-unit drain
taskset -c 112-127 build/signalacct-core-unit route
taskset -c 112-119 build/multidb-boundary-unit
taskset -c 112-127 python3 tools/iotemplates_proof.py identity  # expected exit 1
```

Control-arm construction is `tools/iotemplates_proof.py pad-a` / `pad-b` under the same CPU pin; capture refuses to overwrite an existing archived arm. Their exact compiler commands are retained in the source-proof receipts and generated `pad-build.mk`. No rebuild is necessary to inspect the saved arms.

**Gate accounting.** No gate script, Makefile, EXPECT constant, headline cell, or load plan changed relative to launch. Quick **+0**, full **+0**; owner constants remain **446 / 463**. Assertions extend existing binaries/checkers, not ledger emissions. Existing emission lines are core drain/route `tests/gate.sh:1254`, read-local admission `:1584`, FLIP state/load `:1930,1933`, TLS pipeline/coexistence `:2336`; the feature matrix starts at `:2823`. These remain before the **quick-tier exit at :2871–2875**. Deferred mode-equivalence rows retain their original collection locations. The supplied :2808 quick-exit anchor is stale.

Owner-only live diagnostic command (not run here):

```bash
bash tests/gate.sh iteration \
  --reference-binary "$PWD/build/cleanup-iotemplates/PRE/artifacts/tomokv" \
  --candidate-binary "$PWD/build/cleanup-iotemplates/POST/artifacts/tomokv"
```

The planner's correctness slots use eight physical cores, 16 shards and reviewed 6:2 IO/EX. This gate command's ordinary ABBA configuration does not replace the specific null contract below. A source receipt, final gate and merge belong to mainline.

**Frozen mainline null contract.** Compare PRE/POST, PRE/PAD-A, PAD-A/POST; use PAD-B as the additional inverse control (PAD-B/PRE has identical code, PAD-B/POST still needs parity). No gain is required. The exact launch `tests/headline_cells.txt` is frozen under `frozen/files/tests/`, SHA-256 **d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350**. `gate_measurements.json` SHA-256 is **883634597e70a073c6f7c011524924723a90f77dbed328a1334b4fad26e96afb**. `frozen/h01-h64-plans.json` retains each exact source line/hash and the complete launch load metadata. No historic load-plan status is promoted to validated.

Base guard inventory: **h01–h64 inclusive**, 512 total connections, 64-byte payload, GET/SET × p1/p32 × both modes × all read-local/overlap/reorder combinations. Use **16 shards**, eight physical server cores; **6 IO + 2 EX for 2s**, eight fused workers for 1s. Repeat affected profiles at databases **1 and 4**. Establish the productive-role plateau independently at both depths with sufficient load workers; a single connection's saturation is not evidence. Keep offered loads matched across every arm.

Requested supplementary profiles are separate named variants of those frozen cells, never edits to an existing cell. Use suffixes `-db4`, `-tlsmix`, `-unix`, `-park`, and `-churn`, preserving the parent cell's mode, command, depth, connection count, payload and knob values. Transport/churn variants must cover the endpoint cells **h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h49,h50,h63,h64**, both database counts and both epoll/uring engines. `tlsmix` combines TLS and plain clients; `unix` exercises the Unix transport; park/churn variants include idle-to-active transitions and active-client replacement. Their exact mixed-client shares, burst/churn schedules, load pins and offered-load points must be independently validated and frozen by mainline **before candidate measurement**, not inferred from the unextended runner or tuned after POST. No such newly validated instrument/profile was available to this lane.

The launch note's **14 generic null-cell IDs were not specified**. Their exact mainline selection is **PENDING MAINLINE**; this report does not silently invent a subset or use it to replace the named h01–h64 inventory.

| Regime, reported separately | PRE cycles/op, instructions/op, IPC, rate, p99/p99.9 | POST values / two-sided deltas | Verdict |
|---|---|---|---|
| Benefit | No gain claimed for an interface cleanup | No optimization claim | Structural cleanup only |
| Neutral: 2s FIFO, especially h17/h18/h49/h50 | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Exercised: fused / read-local / overlap / reorder, p1 and p32 | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Possible deficit: mixed TLS, epoll/park, Unix and active-client churn | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |

For every cell and nonidentical pair A/B, require stable-reference parity at that cell's independently validated resolution and:

```text
abs(100 * (B_cycles_per_op / A_cycles_per_op - 1)) <= epsilon_cyc[cell]
100 * (1 - B_rate / A_rate)                     <= epsilon_rate[cell]
100 * (B_p99 / A_p99 - 1)                       <= epsilon_p99[cell]
100 * (B_p99_9 / A_p99_9 - 1)                   <= epsilon_p99_9[cell]
cycles/op = instructions/op / IPC
```

All bands are separately fixed before POST, with independent null/holdout validation. Apply them to PRE/POST and PRE/PAD-A and, unless discharged by the complete code proof, PAD-A/POST; apply the corresponding inverse-control check too. Report instructions/op and IPC together with cycles/op, rate and tails. Do not average away a losing cell, widen bands, change the instrument, or relabel an unentered required window as a pass. Required windows must be exercised on fresh state within a fixed bounded budget, otherwise FAIL.

Available instrument evidence was copied read-only from `cx-nullrefresh/build/nullpublish-mainline-20261001T040445Z/`. Its 25 source-file hashes were verified against recorded source commit **08d1dd2dbb1d549c83eeb5a8f4792c6b9bd6230b**. Instrument digest: **ef5bb5a313f566a67f70b583708bc087da217c9ec5162a3974bb3483b61617dc**. Both frozen campaign A/B binaries were independently hashed as **49e69e30d1d3d46f46f8e5f96dad17885511e905c98fba4a3d530814885cf1a7**, recorded baseline **90ba908d3aca61f2b1e79664e839a5b8093145a4**. These are distinct from this lane's PRE.

That freeze explicitly records **`measurements_run: false`**. Its directory contains no calibration/holdout resolution result. Launch load geometry validates a correctness 8-core 6:2 shape but records ABBA geometry only for 32 cores / 16:16; the ordinary runner's shard selection also does not supply this request's 16-shard fused profile automatically. Thus the required per-cell resolution, stable-reference calibration, new transport/churn profiles and final null verdict are **PENDING MAINLINE**. Mainline must bind/freeze an independently validated instrument and those load plans before the first candidate measurement. This report supplies no guessed command that would silently measure another geometry.

Artifact ledger: `build/cleanup-iotemplates/ARTIFACT-SHA256SUMS`, **77,746 files**, SHA-256 **51c32a2c146c85d98bee85deb916925f09227f6edbf3cc2bed6e0869e1821b16**. `summary.json`, per-arm manifests and all raw artifacts are retained. No mainline measurement result is claimed.

`sha256sum build/tomokv`:

```text
ed2927ebeec3ef80515edb8d309738ae1bef258209fe0dc5083e3fd1f939c42b  build/tomokv
```

`git diff 2a9e48403 (verified launch origin/cpp) --stat`:

<!-- launch-diff-stat -->
```text
 MEASURE-REQUEST-cleanup-iotemplates.md | 246 ++++++++++++++++
 src/cmd/multi.h                        |   2 -
 src/cmd/multi.inc                      |   8 -
 src/core/genthread.cc                  |   2 +-
 src/core/io_loop.h                     | 117 +++-----
 src/core/reorder.cc                    |  97 +++----
 src/core/rl2s.cc                       |   2 +-
 tests/multidb_boundary_unit.cc         |   2 +-
 tests/r7shadow_sync.py                 |  37 ++-
 tests/reorder_engagement_unit.cc       |  92 +++++-
 tests/reorder_noop.py                  |  17 ++
 tools/iotemplates_proof.py             | 503 +++++++++++++++++++++++++++++++++
 12 files changed, 968 insertions(+), 157 deletions(-)
```
<!-- end-launch-diff-stat -->

`git diff 5b3d9c429 (original staging origin/cpp) --stat`:

<!-- staging-diff-stat -->
```text
 MEASURE-REQUEST-cleanup-iotemplates.md | 246 ++++++++++++++++
 MEASURE-REQUEST-cleanup-readreply.md   | 371 ++++++++++++++++++++++++
 src/cmd/multi.h                        |   2 -
 src/cmd/multi.inc                      |   8 -
 src/core/ex_loop.h                     |  63 ++---
 src/core/genthread.cc                  |   2 +-
 src/core/io_loop.h                     | 117 +++-----
 src/core/reorder.cc                    |  97 +++----
 src/core/rl2s.cc                       |   2 +-
 tests/gate.sh                          |   2 +-
 tests/gate_measurements.json           |   8 +-
 tests/multidb_boundary_unit.cc         |   2 +-
 tests/r7shadow_sync.py                 |  37 ++-
 tests/reorder_engagement_unit.cc       |  92 +++++-
 tests/reorder_noop.py                  |  17 ++
 tests/rltopo_unit.cc                   | 148 +++++++++-
 tools/iotemplates_proof.py             | 503 +++++++++++++++++++++++++++++++++
 tools/readreply_proof.py               | 369 ++++++++++++++++++++++++
 18 files changed, 1883 insertions(+), 203 deletions(-)
```
<!-- end-staging-diff-stat -->

The staging diff includes the upstream readreply merge and its existing gate/load-reference changes. They are not this lane's edits; the launch-relative gate/Makefile/executor-source diffs are empty. The lane stops after this report. Measurements, live results, gate, landing approval and merge remain mainline-owned.
