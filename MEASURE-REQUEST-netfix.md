# Network refinement merit request

## netfix

Base: `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`. Branch `cx-netfix`; no push.
All execution is restricted to CPUs 64–79, builds `-j16`; correctness servers use
64–71, drivers 72–79, shards 16, split ratio 6:2, fused eight threads.
Directed new-row boots use client-lb=0 for stable ownership; every boot command
is retained beside its result. Existing batteries use their own declared knobs.

### Final verdicts (continuation run, 2026-10-23 01:50–05:20)

Every row below ran through `tests/gate.sh`'s own job interface (`GATE_ONLY_JOBS`), which
plans its legs and owns every process, port and watchdog. POST is the gate's own source build
(`make -q all` fresh); PRE and PAD-A are `--candidate-binary` runs. For jobs that boot the
default engine, an exec-preserving wrapper (`tools/netfix_verify.py`) selects epoll, or fused
mode for the split-only TLS battery; jobs that choose their own engine keep their choice.

| New gate row (legs it declares) | PRE a7dfb9d23: candidate legs passing | POST: candidate legs passing | Redis 7.4 oracle legs |
|---|---|---|---|
| NT4.6 `netfix_query_stats` (1s/2s × epoll/uring × TCP/TLS) | 0 of 8: field missing (worse) | 8 of 8 | 2 of 2 |
| NT4.11 `netfix_unix` (1s/2s × epoll/uring × regular/stale/live/symlink path) | 4 of 16: only the stale socket (worse) | 16 of 16 | 4 of 4 |
| NT4.8 `netfix_config` (1s/2s × epoll/uring × TCP/TLS; 95 oracle-compared replies) | 0 of 8: error texts differ (worse) | 8 of 8 | 2 of 2 |
| NT4.7 `netfix_tls` (1s/2s × epoll/uring; 23 default suites, TLS 1.2 resumption) | 0 of 4: 2 of 23 suites accepted (worse) | 4 of 4: 23 of 23 | 1 of 1 |
| NT4.19 `netfix_idle_buffers` (1s/2s × epoll/uring × TCP/TLS; 10,000 idle clients) | 0 of 8: all 10,000 keep burst input (worse) | 8 of 8 | 2 of 2 |
| NT4.19 on PAD-A (periodic reclamation disabled, negative control) | — | 0 of 8, as required | 2 of 2 |

Verdict: all five rows FAIL on PRE and PASS on POST in every declared leg; PAD-A fails the
memory row on all eight legs for the same reason as PRE; PAD-B passes all five rows in every leg,
like POST (`c2-pad-b-newrows`). Receipts: `docs/netfix/evidence/`
`c2-pre-newrows`, `c2-post-newrows` (`c2-post-config` reruns NT4.8 with the final battery),
`c2-pad-a-idle` (`.log` gate output, `.json` command and binary digests); per-row copies in
`{pre,post}-{query,unix,config,tls,idle}/` and `pad-a-idle/`; full run archives in `gate-attempts/`.

| Existing jobs (rows), touched or required | POST uring (source build) | POST epoll | PRE uring | PRE epoll |
|---|---|---|---|---|
| tls (TLS battery, split) | 20/20 | 20/20 | 20/20 | 20/20 |
| respcompat (RESP) | 1/1 | 1/1 | 1/1 | 1/1 |
| netcmd_units (serverless) | 16/16 | 16/16 | source-tree units (not the PRE binary) | source-tree units (not the PRE binary) |
| config_unit (serverless) | 2/2 | 2/2 | source-tree units (not the PRE binary) | source-tree units (not the PRE binary) |
| auth (touched: auth.py) | 7/7 | 7/7 | 6/7 FAIL: AUTH/HELLO/protected state machine | 6/7 FAIL: AUTH/HELLO/protected state machine |
| authfix | 5/5 | 5/5 | 5/5 | 5/5 |
| notify | 6/6 | 6/6 | 6/6 | 6/6 |
| debug-0/1 | 28/28 | 28/28 | 28/28 | 28/28 |
| clientfix | 14/14 | 14/14 | 14/14 | 14/14 |
| climonfix | 7/7 | 7/7 | 7/7 | 7/7 |
| feature-split-0/1 (2s; limits.py touched, infofix) | 68/68 | 68/68 | 66/68 FAIL: limits battery (atomic 0); limits battery (atomic 1) | 66/68 FAIL: limits battery (atomic 0); limits battery (atomic 1) |
| feature-armed-0/1 (1s armed; limits.py, infofix) | 70/70 | 70/70 | 68/70 FAIL: fused+armed limits battery (atomic 0); fused+armed limits battery (atomic 1) | 68/70 FAIL: fused+armed limits battery (atomic 0); fused+armed limits battery (atomic 1) |
| fused-0/1 | 14/14 | 14/14 | 14/14 | 14/14 |
| aof-epoll + aof-uring (touched: knobs.py) | 108/108 | in uring column (job runs both engines) | 104/108 FAIL: configuration reduction + actual geometry (epoll, atomic 0); configuration reduction + actual geometry (epoll, atomic 1); configuration reduction + actual geometry (uring, atomic 0); configuration reduction + actual geometry (uring, atomic 1) | in uring column (job runs both engines) |
| netcap (1s/2s × both engines) | 4/4 | in uring column (job runs both engines) | 4/4 | in uring column (job runs both engines) |
| ntfix_input (INFO, 1s/2s × both engines) | 1/1 | in uring column (job runs both engines) | 1/1 | in uring column (job runs both engines) |
| netio-1s/2s (both engines) | 2/2 | in uring column (job runs both engines) | 2/2 | in uring column (job runs both engines) |
| respresume-* (12: 3 cases × 1s/2s × both engines) | 12/12 | in uring column (job runs both engines) | 12/12 | in uring column (job runs both engines) |

Cells are passing rows / rows. PRE is worse only on rows whose assertions this lane corrected to
Redis 7.4's exact replies, each backed by a retained oracle run: `auth` (protected-mode 0/1),
the `limits` battery in all four feature legs (client-output-buffer-limit diagnostics) and the
`knobs` row of both aof jobs (duplicate parameter). POST passes every row on both engines.
Two POST failures surfaced in the continuation and were fixed: `configuration docs match parser`
(the new constant shifted CONFIGURATION.md's config.h anchors; regenerated in 23a7d627d) and the
`knobs` row, which still expected TomoKV's old duplicate-parameter text (corrected in 73a9ef329);
the POST uring column shows their reruns (`c2-post-aof-config`, 111 of 111). Receipts:
`c2-{post,pre}-required-{uring,epoll}`; the uring runs also cover the engine-iterating jobs.
`release_batteries` + `atomic_batteries` (torture, RYOW, ACL tables, idle-loop ceiling, shutdown invariants, direct-reply, atomic torn/RYOW/owner-local batteries) pass 12/12 rows on uring and on epoll (`c2-post-batteries-{uring,epoll}`). NT4.19 arms the client cron unconditionally; the idle-loop ceiling row records 0 spins on every idle thread.

| Proof | Result |
|---|---|
| `tests/differ_gate.sh` standard seeds (gate jobs differ-split-0/1, differ-armed-0/1, differ-equivalence) | POST 6/6 on uring (source build; seeds 7, 19, 20, 23 + rotating 26) and 6/6 on epoll (seeds 7, 19, 20, 23 + rotating 27): split and armed-fused geometries, atomic 0/1, plus the equivalence part (`c2-post-differ-{uring,epoll}`). DIFF-TRK-1 did not fire: epoll armed-fused climon, atomic 0, seed 19 ran 4318 ops with 0 diffs. With nothing to classify, no PRE differential was run (see NOT RUN) |
| TLS battery, both modes | split: `tls` 20/20 rows on uring and on epoll; fused: 20/20 on uring and on epoll (`c2-post-tls-fused-{uring,epoll}`); PRE fused also 20/20 on both engines (`c2-pre-tls-fused-{uring,epoll}`) |
| netcap battery, both modes | `netcap` 4/4 (1s/2s × uring/epoll) |
| RESP battery, both modes | `respcompat` 1/1 (1s+2s, atomic 0/1) on uring and epoll; `respresume-*` 12/12 |
| INFO battery, both modes | `ntfix_input` 1/1 (1s/2s × uring/epoll); `infofix` in feature-split (2s) and feature-armed (1s) on both engines |
| `python3 tests/gates_test.py` | OK: 67 tests + 14 nested, rc 0 (`c2-gates-test.log`) |
| `make all` + every `job_production_units` target, then `make -q` | all fresh: `all` and 37 of 37 unit targets, plus `mdbqsbr-live-arms` built (`c2-production-units.log`) |
| Identity against PRE (proxy; merit decides) | Strict all-body audit: 708 changed linked bodies, each listed with its reason in `docs/netfix/identity/changed-bodies.md`; 0 GET/SET/MGET/MSET command bodies changed. `reorder_noop.py` (PRE inventory 321 bodies): commands 16/16 and multi-key commands 31/31 identical; scheduler 64/66, dispatch 55/80, envelope 16/120, retire 8/8 identical. `r7shadow_noop.py --inventory overlapaxe`: 165/293 identical. No per-unit budget re-derivation was needed |
| Standalone parser unit `tests/respcompat_unit.cc` (not a gate row) | 204,263 checks, 0 failures on the POST and PRE trees (`c2-respcompat-unit.log`) |
| Label fixture vs source | 707 source rows = 707 fixture rows, none missing or extra; refused only by the maintainer-owned EXPECT_FULL=702 (`c2-label-fixture.log`) |

| Arm | Path | SHA-256 | .text bytes |
|---|---|---|---|
| PRE (a7dfb9d23) | `build/tomokv-pre-netfix` | `dd273ba7c7382a7f58fcbc0e030487538dd760ec1aa3e7391698b2d6d83a36fb` | 7,747,526 |
| POST | `build/tomokv` | `9cfcbcb1ea030cf2f2182931bc86d485d363bd6fc70124ad4d28f44f33b59c47` | 7,729,190 |
| PAD-A (behavior twin) | `build/tomokv-pad-a-netfix` | `9f9516081a074eb59f5db61d000e48b27814e63f33e87662d5e4fcde15ee28dc` | 7,729,190 |
| PAD-B (size control) | `build/tomokv-pad-b-netfix` | `47dbcb996e713b996e2aeaf1d4298a53830a98b32d0a4ab96d6308dd2eb559fb` | 7,747,526 |

PRE provenance: its loadable sections are byte-identical to a clean `git archive a7dfb9d23`
rebuild; only DWARF path strings and the build-id differ (`pre-provenance.log`).

DQ/DF: five literal rows collected before the quick-tier exit, DQ +5 / DF +5. The
continuation added assertions inside existing rows only (no new rows). Proposed
EXPECT_QUICK=690, EXPECT_FULL=707; neither constant was edited.

### Review of the maintainer's WIP commit e33345ec5

| WIP change | Decision | Reason |
|---|---|---|
| `tests/auth.py`: CONFIG SET protected-mode 0/1 now expect "argument must be 'yes' or 'no'"; live SET uses yes/no | Kept | Exact Redis 7.4 reply: the oracle legs of `netfix_config` record it for protected-mode 0 and 1 (TCP and TLS). `auth` 7/7 on POST uring and epoll. |
| `tests/netfix_config.py`: protected-mode 1 case | Kept | Oracle-compared like every other case. |
| `tests/netfix_config.py`: LONG_MAX proto-max-bulk-len plus a wrapped bulk header sent after the array header | Kept, and the bug it exposed was fixed | It reproduced a POST defect at 01:44 (ECHO answered "abcd" on all eight legs, `post-wide-limit-reproduction*`). Fixed in 88d10ec55 (below). |
| `tests/netfix_config.py`: inline `import time` | Fixed | Hoisted; the battery also gained a single-write wrapped header, a reply-count check and candidate-only 32-bit bound assertions. |
| `tests/netfix_tls.py`: trailing whitespace | Kept | No behavior. |
| Report edits | Kept as the base | Superseded here by final receipts. |
| Evidence: deleted `memory-*`/`suites-*` JSON, rewritten per-row logs | Kept | They were superseded attempts; the per-row directories now hold the final gate runs. |
| `oracle-tls-build.log` replaced by `.gz` | Kept | Byte-identical (SHA-256 2e8c68f4…). |

### Item notes

NT4.6: reproduced in all eight mode/engine/TCP-or-TLS legs. Counts follow 0,1,2,3,0 across
three silent limit closes and RESETSTAT, including queued MULTI bytes. The field is in Stats
immediately before the output-limit counter. epoll deferred closes are counted once.

NT4.11: both registers and the round-3 owner paper-constraint list contain no ruling to retain
path refusal. PRE refuses regular files, symlinks and live sockets in all four mode/engine legs;
Redis replaces all three. POST matches Redis and retains the stale-socket, permissions, serve and
exit-cleanup checks.

NT4.8: exact oracle error payloads cover network immutable names (including the original
request spelling), integer/memory/bool grammar and ranges, output-limit parser diagnostics and
duplicate parameters. proto-max-bulk-len's configuration range matches Redis through LONG_MAX at
boot and runtime. Runtime bind/port is deliberately not implemented; the handoff and rollback
requirements are in `docs/netfix/runtime-bind-port.md`.

NT4.8 follow-up (88d10ec55, continuation). Widening the range exposed two paths that relied on
PRE's ~4 GiB ceiling:

| Defect on POST before the fix | Redis 7.4 / fixed POST | PRE |
|---|---|---|
| Cold resumed and tail bulk-header decoders passed the configured limit to `parse_len_crlf`, whose bound is its only overflow guard: `$18446744073709551620` wrapped to 4 and `ECHO` answered `abcd` | `ERR Protocol error: invalid bulk length`, for single-write and split frames | Unreachable (limit rejected above 4,294,901,759) |
| APPEND/SETRANGE/SETBIT/BITFIELD bounded growth only by the configured limit and narrowed lengths to 32 bits: `SETRANGE k 4294967296 x` aborted the server (`buffer overflow detected`) | Fixed POST refuses with `ERR string exceeds maximum allowed size (proto-max-bulk-len)`; Redis would attempt the >4 GiB allocation | Same refusal |

The resumed decoders now use the complete-frame path's 512 MiB fast bound and fall back to the
overflow-checked decoder; `command_proto_max_bulk_len()` keeps the 32-bit representable bound
(the pre-netfix ceiling) for string growth while CONFIG keeps Redis's range. The hot
complete-frame parser is unchanged. Remaining deviation, by architecture (32-bit string values
and argv Slices): a string can never exceed 4,294,901,759 bytes. Evidence: `wide-limit-bound.log`,
`c2-prefix-config-control*` (the final NT4.8 row fails on all eight legs of the pre-fix tree).

NT4.7: default cipher acceptance and session caching match Redis's defaults: all four
mode/engine legs accept the oracle's 23 suites with the RSA test certificate, and TLS 1.2
sessions resume. The installed OpenSSL default set is retained, with AES-GCM moved first.

| Default suite class (RSA certificate) | PRE: accepted / two-direction kTLS | POST: accepted / two-direction kTLS |
|---|---|---|
| TLS 1.2 ECDHE-RSA-AES128-GCM-SHA256 | yes / yes | yes / yes |
| Other TLS 1.2 AEAD: AES128/256-GCM and CHACHA20-POLY1305 with RSA, DHE-RSA or ECDHE-RSA (7) | no / — | yes / yes |
| TLS 1.2 CBC (AES128/256-SHA, -SHA256, -SHA384; 12) | no / — | yes / no (userspace) |
| TLS 1.3 TLS_AES_128_GCM_SHA256 | yes / no (RX userspace) | yes / no (RX userspace) |
| TLS 1.3 TLS_AES_256_GCM_SHA384, TLS_CHACHA20_POLY1305_SHA256 | no / — | yes / no (RX userspace) |

Offload went from one TLS 1.2 suite to eight. The kTLS gauge counts two-direction TLS 1.2
offload; TLS 1.3 keeps RX in OpenSSL with eligible TX offload (`ktls-pre-accepted-suites.log`,
`{pre,post}-tls/results.json`). This is not full TLS configuration parity: optional
key-password/client-identity/DH/cache controls and live TLS reload (NT4.7 b/c) remain absent.

NT4.19: the owner cron applies Redis's 4 KiB spare, >2 s idle, 32 KiB active-query threshold,
half-capacity peak comparison and five-second output-peak window, using existing cursors and
capacity growth as peak samples (no request-path stores). Input keeps the 16 KiB floor; two
512-byte inline outputs give the 1 KiB floor. Only empty outputs shrink, under ROB/send/TLS
pointer fences; io_uring cancels a pinned recv and waits for the original CQE before moving
input. Freed jemalloc pages are purged on the cold beat, coalesced across owners.

| 10,000 idle clients after a >128 KiB echo burst | POST (8 legs) | PRE (8 legs) | PAD-A (8 legs) | Redis 7.4 (TCP / TLS) |
|---|---|---|---|---|
| Resident memory after idling, above the warmed baseline | 9.4 to 12.1 MiB (bound: max(32 MiB, 5%)) | row fails: all 10,000 keep burst input | same as PRE | −69.5 MiB / +3.1 MiB |
| Burst peak | 1.96 to 3.05 GiB | — | — | 1.26 / 1.23 GiB |

No MEMORY PURGE and no allocator settings are used; partial input and pending output are
preserved across the idle interval on every leg.

### Merit request (maintainer only; no rates measured in this lane)

Use the gate's own instrument and the frozen 14 rows in `docs/netfix/merit-cells.txt` (verbatim
from `tests/headline_cells.txt`): h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64.
Keep the checked-in workload fields, mode, read-local, reorder, depth and atomic settings
exactly; use the owner's scheduled quiet-box geometry. No full iteration, ABBA, benchmark or
measurement load generator was run by this lane.

Arms (absolute worktree root `/home/user/Projects/cx-netfix`), digests in the table above:

- PRE: `build/tomokv-pre-netfix`, baseline a7dfb9d23.
- POST: `build/tomokv`.
- PAD-A: `build/tomokv-pad-a-netfix`, **A, behavior twin of periodic reclamation**. Exactly six
  bytes differ from POST: both namespaces' cold `IdleBuffers::visit` return false. Section sizes
  and addresses are identical to POST. It fails the memory row on all eight legs. Compatibility
  fixes and removal of the old request-time sheds are shared with POST; this control isolates the
  new periodic mechanism, not all compatibility edits or the shed removal.
- PAD-B: `build/tomokv-pad-b-netfix`, **B, inverse control**: POST objects plus 18,336 bytes of
  unreachable NOP padding restore PRE's exact `.text` size (POST's `.text` is 18,336 bytes
  smaller than PRE's).

Construction receipts: `tools/netfix_pad.py`, `tools/netfix_pad_b.py`, `docs/netfix/pad-{a,b}.json`;
section sizes in `docs/netfix/binaries.json`.

Run PRE/POST ABBA and POST/PAD-A ABBA, with PRE/PAD-B as the size-control pair, using the same
offered load per paired cell. Use at least three complete ABBA blocks and the instrument's
reference/null checks; preserve all raw trials. The verdict is matched-load rate for rate cells
and the declared latency metric for latency cells. Report cycles/op, instructions/op and IPC per
cell alongside those verdicts. A gain must survive the controls; any GET/SET/MGET/MSET
regression requires rejection or revision. Purging all arenas on a cold reclamation beat may
affect tail latency during a burst; include the per-cell tail readings and do not infer its cost
from instruction identity. There is no throughput claim here.

### Identity

| Changed bodies (strict audit, 708) | Count | Reason |
|---|---|---|
| IoLoop dispatch/envelope and owner loop | 283 | NT4.6 query-limit accounting (a short-circuited cold call when the limit trips), NT4.19 cold cron and the original-recv `-ECANCELED` edge, and removal of the old request-time sheds from `reset_rbuf_at_quiescence` |
| Network CONFIG, INFO, Unix path | 36 | NT4.8 grammar/errors, NT4.6 counter and RESETSTAT, NT4.11 replacement |
| TLS context | 27 | NT4.7 OpenSSL default cipher order and Redis default session cache |
| IdleBuffers / client cron | 14 | NT4.19 cold reclamation |
| `resp_parse_tail`, `resp_resume` (both namespaces) | 4 | NT4.8 follow-up: cold resumed decoders keep the 512 MiB fast bound |
| `command_proto_max_bulk_len` (both namespaces) | 2 | NT4.8 follow-up: 32-bit representable string bound |
| Other bodies | 342 | Compiler/link propagation (layout, inlining and constant addresses); strict diffs retained |

Identity is a proxy, not a verdict: the hot GET/SET/MGET/MSET command bodies are identical and the
changed dispatch envelope is for the merit run to judge. `reorder_noop.py` needs
`--expected-functions 321` (its default 169 is another lane's inventory; PRE has 321 bodies) and
ran with `--report-only --literal-pools`; `r7shadow_noop.py` exits 1 because the inventory is not
a strict no-op, as expected. Receipts: `c2-identity.log`, `c2-reorder-identity.log`,
`c2-r7-identity.log`, `docs/netfix/identity/{summary.json,reorder,r7}`; the complete strict diff
archive (3.7 MB, `changed-bodies.json.gz`) and both objdumps are kept locally under
`build/netfix-receipts/` because they exceed the 1 MB commit rule.

### NOT RUN

| Item | Reason |
|---|---|
| ABBA / merit cells, benchmarks, measurement load generators, NIC cells, the full `tests/gate.sh` iteration and push tiers | Maintainer-only by the lane instructions; the merit request above is for the maintainer |
| Full-tier-only jobs other than the differential (`asan_batteries`, `replyoff`, `zc`, `rlcache`, `globcase`) | Part of the maintainer's full iteration; not selected by this lane |
| PRE differential matrix | POST passed every differential part on both engines and DIFF-TRK-1 did not fire, so there was no failure to compare against PRE |
| Re-verifying the TLS oracle's source tree | `build/redis74-tls` no longer exists; provenance rests on its build log and the TCP-oracle cross-check (95 equal replies) |
| `tests/cdfix_checks.py` | Standalone CD audit, not a gate row and unrelated to the touched paths |

Authoritative receipts for this request carry the `c2-` prefix (plus the per-row directories,
`wide-limit-bound.log`, `ktls-pre-accepted-suites.log`, `oracle-knobs-duplicate.log`,
`reply-text-sweep.log` and `pre-provenance.log`). Every other top-level receipt in
`docs/netfix/evidence/` is a previous-run attempt, kept and never counted as a pass.

### Remaining compatibility scope

NT4.7's default cipher acceptance and default session caching are fixed; its optional TLS
key/password/client-identity/DH/cache controls and live TLS CONFIG reload remain unimplemented,
so the row is only partially closed. Runtime bind/port is a design note for fliplisten, as
requested. Strings stay bounded by the 32-bit representable size even when proto-max-bulk-len
is configured larger. Architecture constraints (including IPv4-only bind and TLS 1.3 RX staying
in OpenSSL) remain as recorded by the owner. The TLS oracle is an unmodified Redis 7.4.10 build
(`BUILD_TLS=yes`, jemalloc) of `/home/user/Projects/redis` at f103d127 made inside this
worktree's `build/`; its version banner's `sha=e509335d` is this worktree's HEAD at build time,
picked up by Redis's release-header script, not a Redis commit. Its build tree is gone; on the
NT4.8 battery its 95 replies equal the TCP oracle's (`/home/user/Projects/redis74`, f103d127).
Earlier failed or superseded attempts are kept as evidence and are not counted as passes.
