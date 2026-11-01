## rootcompat

Status: correctness proof in progress. No throughput measurement or claim. Do not merge this lane as fully closed: item 11 remains unresolved (32-bit value/slice representation). HX-3 is retained under the explicitly allowed S2 exception. Item 9 takes the authorized guard-removal fallback.

Branch `cx-rootcompat`; PRE `7d2f8a2051961a1942735fb6dc9b507d778e09d1`. All correctness servers, oracle boots, builds and finite command-scope counts are confined to CPUs 48–63 and ports 20300–20399, with `LC_ALL=C`. The full iteration and performance traffic remain maintainer-owned. No push.

| Item | PRE directed witness | POST result | Mechanism / residual |
|---|---|---|---|
| INFO-PROC-ABORT | Fault shim denies `/proc/self/task/<pid>/stat`; abort in all 8 legs; oracle survives | Initial 8/8 pass; final rerun pending | Failed resource reads produce zero CPU fields; no abort |
| HSCAN-ATOMIC1-SKIP | Held cross-owner RENAME retains a compact predecessor; COUNT 1 then promotion loses 7 continuously present fields, all 8 legs | Initial 8/8 pass; final rerun pending | Compact snapshots return all pairs and cursor 0, as Redis listpacks do |
| TRACK-KEYLESS-CAP-DROP | 46 completed 100k-key attempts lose 34,464 SCAN or 33,440 MGET invalidations; one additional geometry times out on PRE | Pending | Bounded queue overflow coalesces tracking into a retained whole-cache null invalidation; retries delivery to every current IO |
| XS-NOTIFY-1 | Cross-owner and same-owner/two-shard scripts omit all events/invalidations, 32 geometries × 3 attempts; same-shard controls pass | Initial 31/32 geometries pass, one SET timeout; forced-escalation matrix pending | Refresh private workbench observer mask; use notify-selected handlers and execution scope; speculative expiry belongs to the commit batch |
| SET-PASTDEADLINE-DUP-HANDLER | 1,024-byte EXAT/PXAT past values over all 16 shards expose missing fused foreign-key events (112 failed assertions) | Initial 8/8 geometries pass; final rerun pending | L4 prebuild notify specialization installs the elapsed value, emits SET/EXPIRE and lets owner expiry emit EXPIRED |
| ACL-BINARY-PASSWORD-TRUNC | Embedded and leading NUL passwords fail/full or accept/truncated in all 8 legs | Initial 8/8 pass; expanded boot-flag proof pending | `user` config definitions use argument byte lengths; boot authentication uses `cfg_requirepass` length |
| SORT-ACL-IN-MULTI | Both SORT forms reject BY/GET at queue time and EXEC aborts, all 8 legs | Initial 8/8 pass; final rerun pending | Queue special pattern checks and return Redis's exact error inside EXEC. Caller identity already exists in `prepare_commands`; no new executor identity transport |
| SV4.1 | GETUSER/DELUSER names visible in SLOWLOG in all 8 legs | Initial 8/8 pass; MONITOR extension pending | One argument-redaction routine shared by SLOWLOG and MONITOR |
| GUARD NOGROUP-ERRORSTATS | Five distinct errors report only one NOGROUP; all 8 legs | Guard removed; generic counters remain unsupported | Prototype added instructions on successful scopes and double-counted nested Lua errors. Removed it, the old NOGROUP counters and fake XREADGROUP timing/failed_calls. INFO omits the unsupported total. Tcl assertions are re-skipped; evidence in `docs/rootcompat/rejected-errorstats/` |
| GUARD INFO-REPLICATION | Only role and offset; all 8 legs miss standalone fields | Initial 8/8 pass; final rerun pending | Full Redis 7.4 standalone replication section, including IDs and inactive backlog fields |
| GUARD SETRANGE-CLAMP | Small configured limits match Redis; configured 5 GiB permits >4 GiB SETRANGE/APPEND/SETBIT on Redis and is rejected in all 8 Tomo legs (24 mismatches) | UNRESOLVED, no source change | `KvObj::vlen`, `Slice::n`, growth buffers and reply paths use 32-bit lengths. Removing the cap alone truncates lengths and permits out-of-bounds stores. Needs a representation change, beyond a check-only fix. Owner scope question pending |
| HX-3 | An unrelated key in a versioned store expires during a held group; GET returns null without EXPIRED, all 8 legs | Retained S2 residual, no source change | Version resolution suppresses physical reaping for unrelated expired keys too. A notification predicate change alone can duplicate or invent events; correct repair changes resolver/reaping ownership, exceeding the one-function/no-algorithm exception |

The initial SORT PRE oracle assertion incorrectly used SORT_RO in the error text. Redis spells SORT in both errors; that test was corrected and a fresh PRE run is required. Initial passing results above are evidence for intermediate builds, not a final binary certification.

Artifacts and final SHA-256s: pending final build. Frozen PRE: `build/rootcompat/PRE`, SHA-256 `2e07ea8a5be37d357ba05370b3a00f4bf473e09a40f91e94016ee8d5953e5309`.

PAD semantics: **A, behaviour twin**. `tools/rootcompat_pad.py` builds a common image containing POST and a symbol-isolated PRE. `POST-layout` executes POST; `PAD-A` changes only the five-byte main-entry jump to PRE. Sections, symbols and addresses match within that pair. The ordinary `POST` release binary is smaller; its null comparison against PRE remains separate. Do not describe PAD-A as an exact layout twin of the ordinary release binary.

Maintainer measurement request: the 14 generic cells, plus 2s GET/SET at p1 and p32, on PRE/POST and the POST-layout/PAD-A control pair. Use the gate's normal ABBA instrument and matched offered load. Report rate, cycles/op, instructions/op and IPC per cell. A candidate is acceptable only with zero headline regression and a flat layout control; no rate has been measured by this lane.

Finite zero-cost proof: GET/SET/INCR/MGET/MSET, batch 1/32, 1s/2s, normal/db0 namespaces and atomic 0/1 (80 cells per arm), via `tools/rootcompat_counts.py`. Final rerun pending. The rejected generic error-counter prototype failed this condition; its complete counts and nested-error failures are retained.

Gate count accounting by physical collection location: **DQ=+9, DF=+9**. Nine `rootcompat-*` directed rows are collected before the quick-tier exit. `rootcompat-errorstats`, `rootcompat-stringlimit`, and `rootcompat-hx3` are diagnostic-only partial jobs and add zero complete-gate rows. From the checked-in 999/1016 constants, the maintainer's new counts should be **1008/1025**. EXPECT_QUICK and EXPECT_FULL were not edited.

Proof ledger and final validation results: pending. Initial Tcl 2s exposes existing unsupported setup commands and a pubsub failure; scheduler self-tests exceeded their fixed deadlines while builds were active. These are failures, not green results, and require isolated reruns/baseline checks. Any final unexecuted proof will be marked NOT RUN with its reason.
