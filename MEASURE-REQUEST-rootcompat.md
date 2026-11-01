## rootcompat

Status: final review found a further item-4 defect: staged scripts lose the `expired` event when collecting an already-elapsed SET image. The new oracle-directed witness fails 32/192 candidate checks on PRE and POST; same-shard controls pass. A mechanism repair is in progress. The preceding arm passes the original nine directed compatibility jobs (1,816 candidate checks), both Tcl modes and all 80 instruction-count comparisons. Broader regression and differential proof is still running. No throughput measurement or claim. Do not merge this lane as fully closed: item 11 remains unresolved (32-bit value/slice representation), and the scheduler self-test retains one deadline failure. HX-3 is retained under the explicitly allowed S2 exception. Item 9 takes the authorized guard-removal fallback. Item 3's cap proof does not cover first-sidecar-allocation OOM; see `docs/rootcompat/residuals.md`.

Branch `cx-rootcompat`; PRE `7d2f8a2051961a1942735fb6dc9b507d778e09d1`. All correctness servers, oracle boots, builds and finite command-scope counts are confined to CPUs 48–63 and ports 20300–20399, with `LC_ALL=C`. The full iteration and performance traffic remain maintainer-owned. No push.

| Item | PRE directed witness | POST result | Mechanism / residual |
|---|---|---|---|
| INFO-PROC-ABORT | Fault shim denies `/proc/self/task/<pid>/stat`; abort in all 8 legs; oracle survives | Final 8/8 geometries pass | Failed resource reads produce zero CPU fields; no abort |
| HSCAN-ATOMIC1-SKIP | Held cross-owner RENAME retains a compact predecessor; COUNT 1 then promotion loses 7 continuously present fields, all 8 legs | Final 8/8 geometries pass | Compact snapshots return all pairs and cursor 0, as Redis listpacks do |
| TRACK-KEYLESS-CAP-DROP | 46 completed 100k-key attempts lose 34,464 SCAN or 33,440 MGET invalidations; the 2s/uring/db1/atomic1/read-local0 setup expired before enrolment, leaving its two triggers unproved | Final 48/48 SCAN/MGET legs pass (96 checks), zero missing | Bounded queue overflow coalesces tracking into a retained whole-cache null invalidation; retries delivery to every current IO. First-sidecar-allocation OOM remains a separate residual (`docs/rootcompat/residuals.md`) |
| XS-NOTIFY-1 | Cross-owner and same-owner/two-shard scripts omit all events/invalidations, 32 geometries × 3 attempts; same-shard controls pass | Final 576/576 checks pass; all 384 multi-shard attempts arm, including forced escalation | Refresh private workbench observer mask; use notify-selected handlers and execution scope; speculative expiry belongs to the commit batch |
| SET-PASTDEADLINE-DUP-HANDLER | 1,024-byte EXAT/PXAT past values over all 16 shards expose missing fused foreign-key events (112 failed assertions) | Final 8/8 geometries pass, 768 checks | L4 prebuild notify specialization installs the elapsed value, emits SET/EXPIRE and lets owner expiry emit EXPIRED |
| ACL-BINARY-PASSWORD-TRUNC | Embedded and leading NUL passwords fail/full or accept/truncated in all 8 legs | Final 8/8 geometries pass, including leading-NUL boot authentication (56 checks) | `user` config definitions use argument byte lengths; boot authentication uses `cfg_requirepass` length |
| SORT-ACL-IN-MULTI | Both SORT forms reject BY/GET at queue time and EXEC aborts, all 8 legs | Final 8/8 geometries pass | Queue special pattern checks and return Redis's exact error inside EXEC. Caller identity already exists in `prepare_commands`; no new executor identity transport |
| SV4.1 | GETUSER/DELUSER names visible in SLOWLOG in all 8 legs | Final 8/8 geometries pass, SLOWLOG and fenced MONITOR (40 checks) | One argument-redaction routine shared by SLOWLOG and MONITOR; a caller-owned cursor parses HELLO once. Expanded PRE: 24/40 failed checks; final POST: 40/40 pass, including 200 repeated AUTH/SETNAME groups |
| GUARD NOGROUP-ERRORSTATS | Five distinct errors report only one NOGROUP; all 8 legs | Guard removed; generic counters remain unsupported | Prototype added instructions on successful scopes and double-counted nested Lua errors. Removed it, the old NOGROUP counters and fake XREADGROUP timing/failed_calls. INFO omits the unsupported total. Tcl assertions are re-skipped. The six errorstat/total checks and failed_calls component in compat3_blockfix2 are explicitly skipped too; real NOGROUP replies, surviving-group behavior and generic calls/rejections remain checked. Evidence in `docs/rootcompat/rejected-errorstats/` |
| GUARD INFO-REPLICATION | Only role and offset; all 8 legs miss standalone fields | Final 8/8 geometries pass | Full Redis 7.4 standalone replication section, including IDs and inactive backlog fields |
| GUARD SETRANGE-CLAMP | Small configured limits match Redis; configured 5 GiB permits >4 GiB SETRANGE/APPEND/SETBIT on Redis and is rejected in all 8 Tomo legs (24 mismatches) | UNRESOLVED, no source change | `KvObj::vlen`, `Slice::n`, growth buffers and reply paths use 32-bit lengths. Removing the cap alone truncates lengths and permits out-of-bounds stores. Needs a representation change, beyond a check-only fix. Owner scope question pending |
| HX-3 | An unrelated key in a versioned store expires during a held group; GET returns null without EXPIRED, all 8 legs | Retained S2 residual, no source change | Version resolution suppresses physical reaping for unrelated expired keys too. A notification predicate change alone can duplicate or invent events; correct repair changes resolver/reaping ownership, exceeding the one-function/no-algorithm exception |

The initial SORT PRE assertion incorrectly used SORT_RO in the error text. Redis spells SORT in both errors; the corrected fresh PRE run fails all 96 checks, with all 12 oracle checks passing. Earlier tracking enrolment misses and script setup failures and the rejected unwitnessed escalation attempt are retained as failed attempts, not silently counted as passes. The final directed/Tcl partial gate (`QQjXt6`) passes all 12 scored rows: release, two Tcl modes and nine directed jobs, against the POST SHA below. Raw candidate/oracle checks and lifecycle receipts are in `docs/rootcompat/proof/post-final/`. The predecessor arm results remain in `proof/post-release/`. The corrected PRE escalation matrix is in `docs/rootcompat/proof/pre-escalated/`.

Final arms are built; SHA-256s are in `docs/rootcompat/arms.sha256`:

| Arm | SHA-256 |
|---|---|
| PRE | `2e07ea8a5be37d357ba05370b3a00f4bf473e09a40f91e94016ee8d5953e5309` |
| POST | `2fe828086c1619a85f1c0726859547f3f334f255ceeccc31041abafe54921341` |
| POST-layout | `27704a5e366fced4e8965eb8bbdc192f8d0229b318ab56af431588d1b5b80c45` |
| PAD-A | `138cea72cdd2d0b824e76e295675f3f24fff1d06932ac38aa3b3f1db517c07f1` |

The final paired-image gate controls pass on POST-layout and reproduce PRE's replication/HSCAN/redaction failures on PAD-A, in both modes, engines and namespaces. `docs/rootcompat/pad-a.json` records equal sections/symbols and exactly five changed bytes.

PAD semantics: **A, behaviour twin**. `tools/rootcompat_pad.py` builds a common image containing POST and a symbol-isolated PRE. `POST-layout` executes POST; `PAD-A` changes only the five-byte main-entry jump to PRE. Sections, symbols and addresses match within that pair. Execution selects different PRE/POST function ranges, so this does not establish equal placement of the active instructions. The ordinary `POST` release binary is smaller; its null comparison against PRE remains separate. Do not describe PAD-A as an exact layout twin of the ordinary release binary.

Maintainer measurement request: the 18 frozen recipes in `docs/rootcompat/merit.cells.txt`: the 14 generic cells from `tests/wbland_merit_cells.txt`, plus 2s GET/SET at p1/p32 (`h53 h54 h21 h22`), on PRE/POST and the POST-layout/PAD-A control pair. `merit-cells.json` binds the source recipes and exact selection. Use the gate's normal ABBA instrument and matched offered load. Report rate, cycles/op, instructions/op and IPC per cell. Use each recipe's declared latency/rate score and the gate's unchanged acceptance bands. A candidate is acceptable only with no repeatable headline regression and a flat layout control; a regression cannot be averaged away across cells. No rate has been measured by this lane.

Finite zero-cost proof: GET/SET/INCR/MGET/MSET on the notification-disabled path, batch 1/32, 1s/2s, normal/db0 namespaces and atomic 0/1 (80 cells per arm), via `tools/rootcompat_counts.py`. Final production rerun after the linear redactor: **80/80 exact PRE counts, zero added instructions**. The script observer scope is outlined; compile-only budget trials preserve ordinary scatter inlining (`docs/rootcompat/budgets-outlined/selected.json`). Complete final production receipts are in `docs/rootcompat/counts/`. The rejected generic error-counter prototype failed this condition; its complete counts and nested-error failures are retained.

| Command | Cells (namespace × mode × batch × atomic) | PRE→POST instruction delta, every cell |
|---|---:|---:|
| GET | 16 | 0 |
| SET | 16 | 0 |
| INCR | 16 | 0 |
| MGET | 16 | 0 |
| MSET | 16 | 0 |

Gate count accounting by physical collection location: **DQ=+9, DF=+9**. Nine `rootcompat-*` directed rows are collected at `tests/gate.sh:6339`, before the quick-tier exit at line 6482. `rootcompat-errorstats`, `rootcompat-stringlimit`, and `rootcompat-hx3` are diagnostic-only partial jobs and add zero complete-gate rows. From the checked-in 999/1016 constants, the maintainer's new counts should be **1008/1025**. EXPECT_QUICK and EXPECT_FULL were not edited.

Validation in progress:

| Proof | Final result / evidence |
|---|---|
| Nine directed jobs | PASS, 1,816 candidate checks; combined directed/Tcl gate 12/12 scored rows; `proof/post-final/` |
| Diagnostic residuals | Expected FAIL: stringlimit 24/48 mismatches, HX-3 8/8, unsupported error counters 56/72; `proof/final-runs/residuals-final/` |
| Production units | All 51 primary targets and the four auxiliary readiness groups built; all required `make -q` checks return 0; `proof/build-final.json` |
| Notification units | PASS, 17/17 rows; `proof/units-release/`. Earlier private-shard fixture failure and repair are recorded separately |
| Tcl passing-subset job | PASS in 2s and 1s, 39 file jobs / 1,874 passing assertions each, five known setup errors and 433 skips each, zero manifest validation errors; `proof/tcl-final/`. This preserves the manifest's existing known setup errors and skips |
| Broader touched jobs | Running, both modes/engines; one blocked-command fixture row initially failed before execution because companions were absent beside external POST. Companions are placed and the entire job is queued to rerun. `GATE_PROOF_NO_RATES=1` excludes performance checks |
| Standard differential seeds | PASS on uring: 954 comparisons, seeds 7/19/20/23/22, all five partial jobs; epoll running. `proof/final-runs/differ-final-uring/` |
| `tests/gates_test.py` | FAIL: 82/83 on two isolated CPU allocations. The one-slot full-inventory fixture exceeds its unchanged 45 s bound; PRE control passes at 44.217 s, POST times out at 45.188 s after nine added jobs. All 293 POST jobs finalized in the first isolated failure. No deadline/assertion was weakened; `proof/gates-test-final.log`, `proof/scheduler-single-controls.json` |

Tcl accounting: the XGROUP DESTROY/NOGROUP counter assertion is re-skipped after guard removal. The two Lua error_reply statistics assertions remain skipped. No other entire upstream test was made passing by these fixes: the combined SLOWLOG privacy test also requires unsupported replication/TLS configs, and the adjacent redaction test requires MIGRATE. Their fixed ACL assertions are covered by the new oracle-directed SLOWLOG/MONITOR job. The first Tcl attempt used the rejected counter prototype; a focused PRE control reproduced its intermittent 2s pubsub unsubscribe failure. Final POST passes the full checked-in manifest in both modes.

Performance cells and the full iteration: **NOT RUN**, reserved for the maintainer. No throughput claim.
