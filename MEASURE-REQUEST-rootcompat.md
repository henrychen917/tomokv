## rootcompat

Status: the final release passes all nine directed rows: **3,480 candidate checks**, including the expanded script-expiry witness. All 80 finite command-scope comparisons execute zero added instructions. Broader correctness proof is still running; the first final 2s Tcl attempt failed and remains recorded. **The lane is not fully closed: item 11 remains unresolved.** HX-3 uses the explicitly allowed S2 deferral; item 9 uses the authorized guard-removal fallback. The tracking queue-cap proof does not cover failure to allocate the first notification sidecar.

Branch `cx-rootcompat`; PRE `7d2f8a2051961a1942735fb6dc9b507d778e09d1`. Final production source is `8434cfdb69`, with compile budgets fixed by `d6f8cdcff5`; later commits contain tests and evidence. Builds, correctness servers, oracle boots and finite instruction counts use CPUs 48–63 and ports 20300–20399, with `LC_ALL=C`. No push. Full iteration and performance traffic remain maintainer-owned.

| Item | PRE directed witness | Final POST result | Mechanism changed / residual |
|---|---|---|---|
| 1 INFO-PROC-ABORT | Fault shim denies `/proc/self/task/<pid>/stat`; all 8 legs abort; oracle survives | PASS, 56 checks / 8 geometries | Failed resource reads report zero CPU fields; no abort |
| 2 HSCAN-ATOMIC1-SKIP | Held cross-owner RENAME retains a compact predecessor; COUNT 1 then promotion loses 7 continuously present fields in every leg | PASS, 24 checks / 8 geometries | Compact snapshots return every pair and cursor 0, matching Redis listpacks |
| 3 TRACK-KEYLESS-CAP-DROP | Fresh completed PRE matrix: all 48 SCAN/MGET overflow legs lose invalidations (34,464 on SCAN, 33,440 on MGET) | PASS, 96 checks; 48/48 overflow legs, zero missing invalidations | Retain and coalesce whole-cache null invalidation on bounded-queue overflow, retrying delivery to every IO. First-sidecar-allocation OOM remains separate and unproved |
| 4 XS-NOTIFY-1 | Same-owner/two-shard and cross-owner scripts omit events and invalidations. Expanded elapsed-image witness: 256/1,664 checks fail; all 128 forced windows arm | PASS, original 576 plus expanded 1,664 checks; 128/128 forced expiry windows arm | Refresh private workbench observer mask; notify-selected handler and execution scope; batch speculative expiry. Extract resident images even when already elapsed. Actual APPLY owners fence expiry publication until the script's observer batch is committed; originating-script nested expiry retains its own event position |
| 5 SET-PASTDEADLINE-DUP-HANDLER | 1,024-byte EXAT/PXAT past values over all 16 shards expose missing fused foreign-key events (112 failed assertions) | PASS, 768 checks / 8 geometries | L4 prebuild notify specialization installs elapsed values, emits SET/EXPIRE, then owner expiry emits EXPIRED |
| 6 ACL-BINARY-PASSWORD-TRUNC | Embedded/leading NUL passwords fail at full length or accept at truncated length in all 8 legs | PASS, 56 checks, including leading-NUL boot authentication | Build `user` config definitions by byte length; derive boot authentication from `cfg_requirepass` length |
| 7 SORT-ACL-IN-MULTI | Both SORT forms reject BY/GET at queue time and EXEC aborts; 96 failed checks | PASS, 96 checks / 8 geometries | Defer pattern ACL checks to EXEC preparation and return Redis's exact error. Existing caller identity is sufficient; no executor identity transport added |
| 8 SV4.1 | GETUSER/DELUSER names appear in SLOWLOG; expanded PRE has 24/40 failures | PASS, 40 checks, SLOWLOG and fenced MONITOR, including 200 repeated HELLO AUTH/SETNAME groups | Shared argument redactor; caller-owned monotone HELLO cursor avoids repeated parsing |
| 9 GUARD NOGROUP-ERRORSTATS | Five distinct errors count only one NOGROUP in all 8 legs | Authorized fallback: guard removed; generic counters remain unsupported | Rejected generic prototype added successful-scope instructions and double-counted nested Lua errors. Remove it, NOGROUP-only counters and fake XREADGROUP timing/failed_calls. INFO omits unsupported totals. Re-skip the dependent Tcl and compat3_blockfix2 statistics assertions; retain real reply and generic calls/rejections checks |
| 10 GUARD INFO-REPLICATION | Only role and offset; every leg misses standalone fields | PASS, 104 checks / 8 geometries | Full Redis 7.4 standalone replication section, including IDs and inactive backlog fields |
| 11 GUARD SETRANGE-CLAMP | Configured 5 GiB allows >4 GiB SETRANGE/APPEND/SETBIT on Redis; all 8 Tomo legs disagree (24 mismatches). Small configured-limit checks match | **UNRESOLVED**, source unchanged | Values, Slices, growth and reply paths use 32-bit lengths. Removing the clamp alone permits truncation/OOB. Requires a wide-string representation covering reads, mutation, persistence, read-local and replies; see `docs/rootcompat/residuals.md` |
| 12 HX-3 | Unrelated key in a versioned store expires during held group; GET returns null without EXPIRED in all 8 legs | Allowed S2 deferral, source unchanged | Logical version resolution suppresses physical reaping. A notification predicate change can duplicate/invent events; proper repair changes resolver/reaping ownership and exceeds the one-function/no-algorithm exception |

Eight base geometries mean 1s/2s × uring/epoll × normal/DB0 namespace. Tracking and script witnesses add atomic/read-local/expiry/escalation dimensions as recorded in their receipts. All witnesses run through `tests/gate.sh` partial jobs at 16 shards and 6:2 ratio. The late script-expiry matrix covers atomic 0/1, active expiry 0/1, staged/forced escalation, same-shard/same-owner-two-shard/cross-owner, and with/without nested GET. Only event publication waits: reads and physical expiry deletion continue. No layout-locked structure changed. Pending tracking/expiry state stays in the shard-owned sidecar; the existing ownership transfer rebinds the destination pending flag in the same transfer section. No reader retry or seqlock was added.

Final directed evidence: `docs/rootcompat/proof/release-runs/release-directed-tcl/`. Expanded PRE and rejected expiry prototypes: `proof/xsexpiry-fixed/`. The resident-image-only prototype passed 192 checks but failed 40 of the expanded 832 ordering checks; the final fence addresses that failure. Earlier bad SORT error-text expectations, tracking enrolment failures and unarmed escalation attempts are preserved as failed attempts. Corrected fresh PRE runs precede each repair. Complete PRE tracking evidence is in `proof/final-runs/pre-tracking-final/`.

Final artifacts are under `build/rootcompat/release/`; `docs/rootcompat/arms.sha256` binds them:

| Arm | SHA-256 |
|---|---|
| PRE | `2e07ea8a5be37d357ba05370b3a00f4bf473e09a40f91e94016ee8d5953e5309` |
| POST | `f3511f861a8a9a01ca24eafbb43766dca621e7c3c1f3512119c241b962ed26ed` |
| POST-layout | `8b4d40ae2a99592a877796e49be9601d3f4d6b54570838a35d565a2aad1f7912` |
| PAD-A | `28077db134ff36628eb60b1d8ef27fcbf39677da9d69a01b31e985b3d04ebfea` |

PAD semantics: **A, behaviour twin of POST-layout**. `tools/rootcompat_pad.py` creates a common image containing POST and symbol-isolated PRE. POST-layout executes POST; PAD-A changes only the five-byte main-entry jump to PRE. Sections, symbols and addresses match within this pair (`docs/rootcompat/pad-a.json`). Active PRE/POST functions occupy different ranges; this is not proof of equal active-instruction placement. Ordinary POST is smaller, so its comparison against PRE is separate. Final-image runtime controls are queued: replication/HSCAN/redaction must pass on POST-layout and reproduce PRE failures on PAD-A in all eight base geometries.

Maintainer measurement request: run the **18 frozen recipes** in `docs/rootcompat/merit.cells.txt`: 14 generic cells from `tests/wbland_merit_cells.txt`, plus 2s GET/SET at p1/p32 (`h53 h54 h21 h22`), on PRE/POST and the POST-layout/PAD-A control pair. `merit-cells.json` binds the exact selection and source recipes. Use the gate's ABBA instrument at matched offered load; report rate, cycles/op, instructions/op and IPC per cell. Each recipe's declared rate/latency score and unchanged acceptance bands decide it. A repeatable headline regression cannot be averaged away; the behaviour control must stay flat. **No rate or throughput claim is made here.**

Finite zero-cost proof uses `tools/rootcompat_counts.py` on the notification-disabled path, batch 1/32, both modes and namespaces, atomic 0/1: **80/80 cells add zero instructions; 60 exact, 20 lower**. Counts were rerun from final production objects after `make all`. Final cold-helper inlining budgets are 159000 normal / 161500 DB0. The initial fenced prototype failed this condition; complete rejected and selected receipts remain in `rejected-expiry-budget/`, `budgets-expiry/`, `counts-expiry-tuned/` and final `counts/`. These finite instruction counts do not measure IPC, latency or rate.

| Command | Cells | POST minus PRE instructions per command invocation |
|---|---:|---|
| GET | 16 | 0 in all cells |
| SET | 16 | 0 in all cells |
| INCR | 16 | 0 in all cells |
| MGET | 16 | −8 in all cells (−256 per batch of 32) |
| MSET | 16 | −8 in four DB0 atomic-1 cells; 0 in the other 12 |

Gate accounting: **DQ=+9, DF=+9**. One default worker emits nine directed rows, collected at `tests/gate.sh:6360`, before the quick-tier exit at line 6503. Individual `rootcompat-*` partial aliases remain available. Diagnostic-only errorstats/stringlimit/HX-3 jobs add zero complete-gate rows; xsexpiry is part of the xsnotify row. The maintainer's counts should become **1008/1025**, from unchanged checked-in **999/1016**. EXPECT_QUICK/EXPECT_FULL were not edited.

| Proof | Result / evidence |
|---|---|
| Final nine directed rows | PASS, 3,480 candidate checks; combined gate `25vFxB` has 11 pass/1 fail because its 2s Tcl row failed, not because a directed row failed |
| Production builds/freshness | All 51 primary production targets and four auxiliary groups built; `make all` and every required `make -q` return 0; `proof/build-release.json` |
| Notification/production unit gate | PASS, 17/17 rows, gate `ipmOrX`; final blockfix2 and DB0 companion binaries copied beside POST |
| Broad touched jobs | Final uring split PASS: 278 rows, gate `FhcI3T`, including full blockfix2. Final fused uring PASS: 41 rows. Final epoll split PASS: 189 rows. Final fused epoll PASS: 41 rows. Supplementary observer jobs are RUNNING. `proof/release-runs/` records commands, hashes and ledgers as jobs finish |
| Standard differential seeds | PASS on both final engines: 954 comparisons each, all five jobs; uring gate `4F4Z4c`, epoll gate `B4ZjaF`. Both prior-arm suites remain separately labelled under `proof/final-runs/` |
| First final-release Tcl job | 1s PASS: 39 files, 1,874 passing assertions, five accepted setup errors, 433 skips. 2s FAIL: two unsubscribe/PUBLISH count assertions and scripting incomplete at unchanged 60 s bound during compilation. One isolated full rerun is queued; first failure retained under `proof/tcl-release-first/` |
| Tcl PRE control | Actual PRE hash reproduced the 2s SUBSCRIBE-after-UNSUBSCRIBE failure (returned 1, expected 0); PUNSUBSCRIBE passed in that specific control. Full summaries preserved under `proof/pre-tcl-control/`; bounded focused control for both assertions queued |
| `tests/gates_test.py` | Isolated rerun queued. Earlier ungrouped run: 82/83, one-slot inventory hit 45 s bound. Grouped run during compilation: 80/83, three 45 s deadline failures. No deadlines or assertions weakened; both failures retained |
| Diagnostic residual jobs | Expected FAIL on predecessor release: stringlimit 24/48 mismatches, HX-3 8/8, unsupported error counters 56/72. These source paths are unchanged; `proof/final-runs/residuals-final/` |
| Final PAD runtime controls | QUEUED on the hashes above; old-image controls are retained separately and are not substituted |

Earlier broad blockfix2 attempts failed before fixture execution: first the helper was absent beside the external candidate; then a DB0 helper link failed during overlapping object/debug-strip work. Both failures remain recorded. A fresh frozen build, all freshness checks and companion copies repaired the artifact preparation; final full blockfix2 execution passes all seven rows in broad uring split gate `FhcI3T`, including the refusal fixture. No earlier failed gate is called green.

Tcl accounting: re-skip the XGROUP DESTROY/NOGROUP statistics assertion; the two Lua error_reply statistics assertions remain skipped. Six compat3_blockfix2 total/errorstats assertions and the failed_calls component are explicitly skipped after removing their unsupported guard. No whole upstream test was promoted for ACL redaction: the combined SLOWLOG privacy test also requires unsupported replication/TLS configs, and the adjacent test needs MIGRATE. Fixed ACL assertions have their own oracle-directed SLOWLOG/MONITOR coverage. Five known setup errors and 433 skips remain in successful checked-in-subset runs; this is not a claim that the complete upstream Tcl suite passes.

Performance cells and full iteration: **NOT RUN**, reserved for the maintainer. Item 11 and HX-3 fixes: **NOT IMPLEMENTED**, for the reasons above. First-sidecar-allocation OOM injection: **NOT RUN**; queue-cap evidence does not cover it.
