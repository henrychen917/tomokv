# Lane ntfix

## ntfix

**STOPPED at the mandatory hot-body identity check. This is an incomplete,
non-mergeable candidate, not a completed four-defect fix.** N1/N2 pass their
directed regressions, but the normal production build changes 11 selected hot
bodies outside `epoll_recv`. N3/N4 remain unfixed. The task explicitly says to
stop and report instead of widening the change when this constraint is not met.
No compiler budgets, inlining policy, architecture, or parser algorithm were
changed to work around the failure.

The small source commits are retained for review:

- `567d3b8e3`: first fetched and merged `origin/cpp`
  (`f821104a90efd5c3258e64be337f4710df2a43cc`) into `cx-ntfix`, whose parent was
  respresume `f95da7d55695f7b46908542d3d2f03846731e206`. The only merge conflict
  was the Makefile insertion of the respresume unit and lottery targets; both
  were kept.
- `cf33f79a9`: PRE reproductions and connect-only INFO/TLS regressions.
- `8b415754f`: N1 epoll received-byte accounting.
- `a3828024c`: N2 TLS close-after-reply receive/poll wakeup.
- `2861fc37f`: two gate rows, and PRE/candidate row receipts.

No push, performance benchmark, load generator, or `tests/gate.sh` execution was
performed. There is no throughput claim and no measurement approval requested.
Do not use this incomplete candidate for the maintainer's epoll-twin null.

### PRE and oracle provenance

PRE is the merged tree at `567d3b8e3`, built with the normal Makefile using
`taskset -c 96-111 make -j16 all`, before production edits. The ELF and production
objects were copied into `build/ntfix-pre/` for independent reproduction and
identity comparisons. Both PRE and candidate `make -q all` returned 0.

Every correctness boot uses `--databases 1`, 16 candidate shards, candidate CPUs
96-103, oracle CPU 104, and clients 105-111. Mode 1s is fused with read-local 1;
mode 2s is split with ratio 6:2. All used ports were within 25800-25803. The driver
checks its ports before starting, and stops only its own child PIDs.

The requested `/home/user/Projects/redis74` has binaries but no `networking.c`.
The adjacent `/home/user/Projects/redis` contains Redis 7.4.10 source at
`f103d127b9747965e28f20615ef790332661fc68`. Its server binary is SHA-identical to
the requested pinned oracle:

| File | SHA-256 |
|---|---|
| `/home/user/Projects/redis74/src/redis-server` | `ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b` |
| `/home/user/Projects/redis/src/networking.c` | `0ed207f003c35589f97e6375bcf589c5fb22a1f905b3c2e9ec6a08d67984893c` |

The pinned oracle has no TLS support (it rejects a TLS listener with “Missing
implement of connection type tls”). As in the inherited fragment corpus, the
candidate's TCP and decrypted TLS streams are compared to this oracle over TCP.
Files named `limits-redis-tls.jsonl.gz` contain the TCP oracle reference for the
candidate TLS arm; they do not claim an oracle TLS boot.

### Reproductions and re-verified anchors

The limits payloads are imported unchanged from `tests/respresume_limits.py`.
Every case uses fresh client state, and CONFIG changes are restored after each
case. Exact replies and close outcomes, including the large ECHO reply, are in
`docs/ntfix/pre/reproduction/{1s,2s}-{uring,epoll}/limits-*.jsonl.gz`.
The accompanying `reproduction.json` and `differences.json` contain compact
per-case summaries. The 1-second silent-peer probe reports whether EOF follows
the exact reply; the separate gate regression allows 3 seconds and fails on
timeout.

| Defect | PRE result, both modes | Current source anchors | Disposition |
|---|---|---|---|
| N1 | epoll TCP input delta 0 instead of the exact 39 request bytes; uring control correct | `src/core/io_loop.h:846,855`; uring accounting at 2412 and 2593 | Candidate regression passes |
| N2 | uring TLS sends the protocol-error/QUIT reply but does not close; epoll TLS and both TCP controls close | `src/net/wb.h:486,523`; the existing release fence is `src/net/conn.h:734` | Candidate regression passes |
| N3 | count 11 and bulk 16385 produce `invalid ... length` instead of `unauthenticated ... length`, both engines/transports | `src/net/resp.h:129,147`; pre-AUTH caller in `src/core/io_loop.h:3250` | Unfixed; stopped before implementation |
| N4 | “many completed args then over limit” and “partial header crosses limit” close, while Redis keeps them open, both engines/transports | `src/net/conn.h:322,349`; limit selection/check at `src/core/io_loop.h:809,818` | Unfixed; stopped before implementation |

Each uring geometry has 10 differing reproduction entries and each epoll
geometry has 9; these are individual case/transport entries, not ten or nine
different defects. See the exact [PRE summary](docs/ntfix/pre/reproduction.log).
The inherited respresume evidence was read without modifying its worktree.

**N4's exact Redis rule, not yet implemented here:** after a successful socket
read appends bytes and before parsing that read, `readQueryFromClient` compares
`c->mstate.argv_len_sums + sdslen(c->querybuf)` against the configured query-buffer
limit and, if authentication is required, against 1 MiB. Overflow is strictly
`>`; equality is legal. `processMultibulkBuffer` advances `qb_pos` over decoded
array/bulk headers and completed argument payloads/terminators.
`processInputBuffer` trims through that position after processing input, even
when the current command remains incomplete. Therefore bytes consumed on an
earlier parse pass no longer count on the next read; an incomplete payload and
an incomplete header still count. This is not a check that first parses away
the newly received bytes before measuring them.

Verified Redis anchors: `networking.c:2337-2345` for pre-AUTH array error
precedence, 2388-2397 for bulk error precedence, 2348/2400/2459 for parser
advancement, 2659-2662 for trimming, and 2759-2764 for the actual limit test.
The two named N4 oracle cases stay open because their completed prefixes were
trimmed on earlier passes. TomoKV retains that prefix in the pending frame and
checks `rlen_ - rpos_`; its saved `RespFrontier::next` is not used by the limit
test or receive-space cap. Both are inlined into normal receive/dispatch bodies.
No claim is made that N4 was fixed or that a zero-difference POST corpus exists.

### Implemented candidate changes

N1 adds one relaxed load/add/store to the existing positive `recv` arm, immediately
before `commit_read`. It updates the same existing IO-owned `net_input_bytes`
field as uring, with no new branch, state, allocation, shared cache line, or
atomic RMW. The linked-main object adds exactly these three instructions:

```asm
mov 0x498(%rax), %rdx
add %rbp, %rdx
mov %rdx, 0x498(%rax)
```

Here `%rbp` is the positive `recv` result and `%rax` is the existing owner context.
The added instructions occupy 17 bytes; alignment makes the emitted `epoll_recv`
body grow by 16 bytes (1098 -> 1114 in each main object, 717 -> 733 in the other
emitted copies). A pre-existing `xor` and read-commit `add` exchange order.
Receipts: [PRE disassembly](docs/ntfix/identity-n1-n2/epoll-pre.asm) and
[candidate disassembly](docs/ntfix/identity-n1-n2/epoll-post.asm).

N2 changes only the empty-output return in `WbEngine::pump_tls<false,...>`.
After no send is in flight, all BIO ciphertext is consumed, all staged plaintext
is drained, and the ROB is quiescent, a closing connection with an outstanding
recv/poll gets `shutdown(SHUT_RDWR)`. Its completion clears the existing pin;
the existing release/quiescence fences remain responsible for destruction.
No wait or forced early release was added. The directed test uses TLS 1.3,
requires exact replies followed by EOF while the peer stays silent, includes
PING+QUIT reply ordering, and checks that ordinary PING remains usable.
Broader TLS validation is NOT RUN after the identity stop.

### Identity failure — why work stopped

All three requested identity tools were run unmodified:

| Check | Result |
|---|---|
| `tools/lbstall_artifacts.py compare build/ntfix-pre build ...` | **FAIL**: 1199/1210 bodies equal after resolving relocations; 1196 raw-byte equal |
| `tools/ccfix_audit.py build/ntfix-pre build ...` | **FAIL**: 1203/1214 hot bodies equal; assertion `ordinary hot-path bytes changed` |
| Full emitted-body inventory | 16415/16510 equal; **95 changed emitted bodies** |
| Command handlers | **1211/1211 equal** |
| `docs/deadswitch/linked_bytes.py` | **FAIL**: runtime sections differ; `.text` 7,655,116 -> 7,653,676 bytes |

Every changed function, including each object copy and clone, is listed in
[the full changed-body table](docs/ntfix/identity-n1-n2/full/changed-bodies.md)
and [machine-readable inventory](docs/ntfix/identity-n1-n2/full/changed-bodies.json).
The [hot log](docs/ntfix/identity-n1-n2/hot.log) lists all 11 offending bodies.
The full [audit summary](docs/ntfix/identity-n1-n2/full/summary.json) and
[linked-section receipt](docs/ntfix/identity-n1-n2/linked.json) are retained.

In particular, this is not merely address relocation or permitted epoll growth:
`tomo_db0::ExLoopT<true>::execute<false,false>` shrinks 3631 -> 3565 bytes,
its fused pass shrinks 4180 -> 4033, and ordinary R7 parsing grows 18345 -> 18394.
The non-TLS split-local parser in `src/core/rl2s.o` also changes
21207 -> 21138. These functions were not edited; their emitted instructions
changed after recompilation with the unchanged flags. The required byte-identity
result fails regardless of the optimizer's reason.
No claim is made that preserving identity is impossible under a different
implementation; this candidate fails the constraint and was not widened.

### Gate rows and completed validation

The two new rows were run directly through their battery entry points, with the
same candidate geometry; the gate coordinator itself was not run.

| New row | PRE | Candidate | Row and collection lines in `tests/gate.sh` |
|---|---|---|---|
| `INFO received bytes exact (ntfix N1)` | FAIL on epoll in both modes; uring controls PASS | All four legs PASS | row 1860; collection 3775 |
| `TLS silent-peer close after reply (ntfix N2)` | FAIL on uring in both modes; epoll controls PASS | All four legs PASS | row 3233; TLS collection 3857 |

[PRE row ledger](docs/ntfix/pre/rows.log),
[candidate row ledger](docs/ntfix/post/rows.log);
individual logs and exact boot commands are in their adjacent `rows/` trees.
These checks demonstrably fail on PRE. They neither skip a closed-window case
nor relax their assertions when the failure occurs.

**DQ = +2, DF = +2 for the current incomplete diff.** Both collection lines are
before the quick-tier exit at line 3907. If these two rows are retained, the
maintainer-owned constants would be **EXPECT_QUICK 637 -> 639** and
**EXPECT_FULL 654 -> 656**. The constants were not edited. N3/N4 gate rows were
not added; claiming +4/+4 would miscount the actual diff.

`make -j16 all` passed for PRE and candidate, with no compiler warnings/errors;
`make -q all` returned 0 for both recorded artifacts. `bash -n tests/gate.sh`,
Python compilation of the three modified drivers, and `git diff --check` passed.
Build logs: [PRE](docs/ntfix/pre/build.log),
[candidate](docs/ntfix/post/build-n1-n2.log).

### Outstanding requested proof

| Requested work | Status and reason |
|---|---|
| Implement N3/N4 and add their two discriminating gate rows | **NOT DONE** — mandatory identity stop after N1/N2 |
| POST limits corpus, both modes/engines/transports, zero differences | **NOT RUN** — N3/N4 remain unfixed; identity stop |
| POST TLS/RESP fragment corpus including close cases | **NOT RUN** — identity stop |
| Epoll infofix differential, both geometries, atomics 0/1, seeds 7/19/20/23 | **NOT RUN** — identity stop; only the directed N1 row was run |
| `tests/differ_gate.sh` standard seeds on both engines | **NOT RUN** — identity stop |
| `python3 tests/gates_test.py` | **NOT RUN** — identity stop; no assertions changed |
| Every `job_production_units` target and its freshness checks | **NOT RUN** — identity stop; `make all` is not that unit matrix |
| Layout/PAD arm | **NOT BUILT** — candidate failed identity before any measurement request |
| Full gate and performance measurements | **NOT RUN** — maintainer-owned and expressly excluded |

### Built artifacts

These hashes identify the review artifacts only; POST is the incomplete N1/N2
candidate, not a claim of four-defect completion or performance merit.

| Arm | Path | SHA-256 |
|---|---|---|
| Merged PRE | `/home/user/Projects/cx-ntfix/build/ntfix-pre/tomokv` | `5c8ca908bc4babe1a2ef6dcae4d3d3a60900aa8de6ecc78019a02c8c7c30b8c5` |
| Incomplete POST candidate | `/home/user/Projects/cx-ntfix/build/tomokv` | `ba65df4d872ab92ccd2d82afd3a979e2acba1d62694d82e0b22e342fc5c5af71` |

Reproduction driver: `tools/ntfix_proof.py` (fixed lane cores and ports).
The final worktree is committed on `cx-ntfix`; nothing was pushed.

## ntfix2

This section supersedes the identity stop above. N1 (`8b415754f`) and N2
(`a3828024c`) are retained. N3 and N4 are implemented, and the required epoll
INFO differential exposed an additional missing output-byte counter update,
fixed in the existing epoll send paths. No command handler was edited.
Performance and the full gate remain maintainer-owned; there is no throughput
claim.

**Qualification:** all requested proof was run, but the standard io_uring matrix
has one unresolved one-millisecond HPTTL deadline failure. The epoll standard
matrix, limits and fragment corpora, directed rows, gate-profile batteries,
gate self-tests, and production builds pass. This is not an all-green
correctness sign-off.

### Identity attempt and final source

`09addf4cc` changes only four Makefile inlining budgets and retains the
compile-only trial receipts under
[identity-attempt](docs/ntfix/ntfix2/identity-attempt/README.md).
Eight PRE/POST unit-size builds and 28 candidate budget trials used CPUs 96–111.
All four initial IPA units grew by 40 instructions. Recompiled PRE reproduced
its frozen object bodies exactly.

| Object | Old budget | Selected budget | N1/N2 hot differences before → after |
|---|---:|---:|---:|
| `src/core/genthread.o` | 129447 | 129487 | 2 → 0 |
| `db0/src/core/genthread.o` | 129704 | 129744 | 2 → 0 |
| `src/core/rl2s.o` | 162305 | 162357 | 2 → 0 |
| `db0/src/core/reorder.o` | 148358 | 148398 | 5 → 1 |

The residual N1/N2 body is
`tomo_db0::ExLoopT<true>::r7_fused_sweep_impl<32u,true,false,false>()`,
796 → 729 bytes. Its named calls are unchanged; GCC changes instruction and
control-flow placement. Its source was not edited. The revised identity rule
admits that difference for merit review.

Subsequent source commits:

- `1e4861741`: N3 classifies only the pre-AUTH error exit with the existing
  strict length decoder. It checks at most ten argument headers and steps over
  completed payloads. Invalid syntax, signed overflow, counts above `INT_MAX`, and the
  configured bulk ceiling retain Redis's precedence over the authentication
  bounds. The ordinary parser and frontier calling conventions are unchanged.
  Both ordinary and R7 dispatchers use the classifier before their existing
  ordered error-reply/close path. The exact limit replies are
  `-ERR Protocol error: unauthenticated multibulk length\r\n` and
  `-ERR Protocol error: unauthenticated bulk length\r\n`, each followed by close.
- `70572c702`: N4 uses `rpos + RespFrontier::next` when a multibulk is pending,
  in both the query-limit check and receive-space cap. No bytes move, no saved
  argv slices are invalidated, and no fields, allocations, knobs or waits are
  introduced.
- `7aa2b2aba`: the required epoll INFO differential got past its input-rate
  assertion and failed `instantaneous_output_kbps > 0`: the corresponding
  total was also zero although replies had been sent. The legacy-buffer,
  segmented-send and userspace TLS-ciphertext epoll paths now update the same
  existing IO-owned `net_output_bytes` field as their io_uring counterparts,
  after a successful send. These are relaxed load/add/stores, not atomic RMWs.
  The existing N1 row now checks exact output deltas too; no extra row is added.
  The interrupted build/matrix and superseded receipts are preserved under
  [before-output-fix](docs/ntfix/ntfix2/before-output-fix/README.md).

The three requested identity tools were run unmodified against PRE
`567d3b8e3` after the final production edit:

| Audit | Final result |
|---|---|
| Command handlers | **1211/1211 identical**, bytes plus resolved relocation targets |
| `ccfix_audit.py`, all emitted bodies | 16,294/16,525 identical; **231 changed** |
| `ccfix_audit.py`, selected hot bodies | 1,159/1,214 identical; **55 changed** |
| `lbstall_artifacts.py compare` | See [unmodified hot log](docs/ntfix/ntfix2/identity/hot.log); its strict identity assertion fails |
| `linked_bytes.py` | Runtime sections differ; `.text` **7,655,116 → 7,657,788 bytes** |

The strict tools' nonzero exits are reported, not converted into passes.
Every changed emitted body, including each object copy and clone, has both
sizes and a reason in the
[full table](docs/ntfix/ntfix2/identity/changed-bodies.md),
[hot table](docs/ntfix/ntfix2/identity/changed-hot-bodies.md), and
[annotated JSON](docs/ntfix/ntfix2/identity/changed-bodies-with-reasons.json).
The final inventory includes intentional N3 error-path and N4 accounting
changes, epoll accounting, N2, and compiler inlining/codegen in unedited
functions. No unrelated function was hand-edited to force identity.

The final `netcap-unit` reports the locked layouts:
`Op=336 Client=1984 ThreadCtx=1408 Shard=1440 FlatStore=944 Rob=192
AtomicEntry=144 Config=624`.

### Exact Redis rule implemented for N4

The source of truth remains
`/home/user/Projects/redis/src/networking.c`, SHA-256
`0ed207f003c35589f97e6375bcf589c5fb22a1f905b3c2e9ec6a08d67984893c`.
The Redis 7.4.10 server is SHA-identical to the pinned
`/home/user/Projects/redis74/src/redis-server`.

At lines **2759–2764**, after appending a successful read and **before parsing
that read**, Redis checks
`c->mstate.argv_len_sums + sdslen(c->querybuf)` against the configured
query-buffer limit, and also against 1 MiB when authentication is required.
The comparison is strictly `>`: equality is legal. Queued MULTI arguments
count; the current incomplete command's completed argv payloads are not added
back through `c->argv_len_sum`.

`processMultibulkBuffer` advances `qb_pos` over decoded array/bulk headers and
completed payloads plus terminators. At **2659–2662**, `processInputBuffer`
trims through `qb_pos` even if the current command remains incomplete.
An incomplete header and an incomplete payload remain in the next read's
query buffer. Newly received prefixes still count until that input pass is
parsed; the implementation does not parse away new bytes before checking.

TomoKV's saved frontier provides that already-consumed boundary while keeping
the receive allocation pinned for zero-copy argv. The receive cap uses the
same boundary and still offers exactly one byte beyond the remaining limit.
The two named corpus cases, “many completed args then over limit” and “partial
header crosses limit”, configure a 1 MiB query limit on authenticated clients;
they exercise the same accounting as the implicit pre-AUTH 1 MiB cap. Both
connections now survive, as on Redis.

The deterministic `netcap-unit frontier` witness exercises the actual parser
and receive-space implementation, requires the completed-argument frontier
to exist, checks queued MULTI accounting, incomplete-header and payload
equality/overflow, and verifies that pinned bytes stay intact. It fails on
PRE's headers/objects at “completed argv excluded even when queued MULTI
equals the limit” and passes on POST. The wire row additionally requires an
exact final reply after each surviving prefix; silence alone cannot pass it.

### Correctness receipts

All builds use `taskset -c 96-111`, `make -j16`; candidate servers use 96–103,
the oracle uses 104, and clients use 105–111. All listening ports are within
25800–25899. The new drivers use 16 shards and `--databases 1`, with fused
read-local 1 or split ratio 6:2. The unchanged standard differential coordinator
retains its explicit 16-database compatibility matrix. It is not a default
server geometry.

The oracle has no TLS listener. TCP oracle bytes are compared with decrypted
candidate TLS streams; no receipt claims that Redis was booted with TLS.

| Required proof | Result / receipt |
|---|---|
| N1–N4 directed rows, both modes and engines, TCP/TLS where applicable | **PASS**, 16/16 mode/engine defect legs; [POST ledger](docs/ntfix/ntfix2/post/rows.log) |
| N3/N4 rows on PRE `567d3b8e3` | **FAIL as required**, both modes and engines; [PRE ledger](docs/ntfix/ntfix2/pre-final/rows.log) |
| N4 deterministic production-parser unit | PRE **FAIL**, POST **PASS**; [PRE](docs/ntfix/ntfix2/pre-final/frontier-unit.log), [POST full netcap unit](docs/ntfix/ntfix2/post/netcap-unit.log) |
| Unchanged respresume limits corpus, 2 modes × 2 engines × TCP/TLS | **0 differences** in every geometry; [ledger](docs/ntfix/ntfix2/post/limits.log), exact compressed streams in its adjacent `limits/` tree |
| TLS/RESP fragment corpus including close cases | **PASS**, 4,692 trials × 8 mode/engine/transport combinations = **37,536 trials, 0 differences**. All 19 close-case families remain enabled, RESP2/RESP3 and seeds 7/19/20/23. [Ledger](docs/ntfix/ntfix2/post/fragments-batteries.log), individual `fragment-tcp.log` / `fragment-tls.log` receipts in the adjacent tree. |
| Existing RESP/netcap/TLS batteries | **PASS**, 12/12 battery legs across both modes and engines with the gate's declared boot settings; [ledger](docs/ntfix/ntfix2/post/batteries-gate-profile.log). Initial boot-contract and optional default-cipher failures are retained and explained below. |
| Epoll infofix, both geometries, atomics 0/1, seeds 7/19/20/23 | **PASS**, all 16 INFO legs. [Split](docs/ntfix/ntfix2/differ/epoll-split-infofix.log): 8/8. [Armed fused](docs/ntfix/ntfix2/differ/epoll-armed-fused-infofix-witness.log): 8 INFO + 8 unchanged string legs and both read-local witnesses pass. |
| `tests/differ_gate.sh` standard seeds, both engines | **Epoll PASS: 475/475. io_uring FAIL: 474 pass / 1 fail**, `hexpire`, atomic=0, seed=7, one HPTTL deadline comparison. Both run all 47 suites, seeds 7/19/20/23/21, atomic 0/1, four multi repeats and the 32-case mode-equivalence check. [io_uring](docs/ntfix/ntfix2/differ/uring-split-standard.log), [epoll](docs/ntfix/ntfix2/differ/epoll-split-standard.log). |
| `python3 tests/gates_test.py` | **PASS**, 66 tests in 317.224 seconds, plus the nested 14-test persistence identity self-test; [log](docs/ntfix/ntfix2/post/gates-test.log). Command: `taskset -c 105-111 env GATE_TEST_PORT=25899 python3 tests/gates_test.py`. |
| `make all`, every `job_production_units` target, freshness | **PASS**: all 31 named unit/control targets plus both `mdbqsbr-live-arms` binaries, 36 successful build/freshness commands; [results](docs/ntfix/ntfix2/production/results.json), [inventory](docs/ntfix/ntfix2/production/targets.txt). The aggregate is phony; `make -q` checked each concrete arm with its original flags. |
| Full gate / ABBA / throughput measurements | **NOT RUN** — explicitly maintainer-owned |

The only harness portability change is `GATE_TEST_PORT` for the existing
socket/TIME_WAIT fixture in `gates_test.py`; this lane reserves port 25899.
No assertion or deadline was changed. The N3 count-boundary control uses a
valid ten-argument DEL. An initially used ten-argument PING exposed a separate
AUTH-versus-arity error-precedence difference; that is not a length-limit
failure and is not silently presented as fixed here.

The initial combined fragment/battery run used the ordinary default boot.
Its **eight fragment legs and four RESP compatibility legs pass**. All four
netcap invocations correctly refused the missing fixed-ownership precondition
(`--client-lb 0`). Both io_uring full TLS batteries passed; both epoll default-
cipher TLS batteries failed the `TLSv1.3 did not retain the OpenSSL record layer`
gauge assertion. These six failures remain in the combined ledger; its nonzero
exit is not described as a successful whole run.

`6792184d2` fixes only the new proof driver's battery boot: `--client-lb 0`,
`--enable-debug-command yes`, and the TLS gate's existing TLS1.2 CBC / TLS1.3
AES-256-GCM cipher settings with `--expect-ktls no`. The unchanged batteries
then pass all twelve legs, including the userspace-cipher counters. The
fragment receipts retain their original default-client-balancing/default-cipher
boots. No battery assertion or deadline was changed. Separate frozen-PRE and
POST default-cipher controls are retained under
[controls](docs/ntfix/ntfix2/controls/results.json).

Fresh uninstrumented default-cipher controls passed on PRE in both modes and
on POST split, while POST fused failed the same gauge assertion. Five further
fresh fused boots **per arm**, recording the unchanged battery's INFO results
in memory, reproduced it **5/5 on PRE and 5/5 on POST**.
[Results](docs/ntfix/ntfix2/controls-gauges/results.json) and per-boot
`gauges.json` snapshots show TLS1.3 fallback and RX-decline counters increasing
3 → 4 while `tls_ktls_active` remains 1 from the preceding, gracefully closed
TLS1.2 probe. This is a pre-existing default-cipher kTLS gauge/lifecycle
finding, still open. The observer returns each original INFO dictionary
unchanged and writes snapshots only after the battery finishes; assertions,
the 50 ms close interval, and the rest of the battery are untouched.

The initial focused armed-fused INFO run had **zero reply/property differences
in all eight legs**, but its coordinator correctly failed both read-local
non-vacuity checks: INFO ends with `CONFIG RESETSTAT`, so every sampled counter
was zero. The retained [first receipt](docs/ntfix/ntfix2/differ/epoll-armed-fused-infofix.log)
is not called a pass. The follow-up adds the existing `string` suite before
each INFO leg, without changing either suite or the coordinator. Sampled
read-local peaks are 6 (atomic=0) and 7 (atomic=1), while final counters are
zero after RESETSTAT. The coordinator now passes all 18 checks.

The standard io_uring failure is retained at
[hexpire-a0-s7.txt](docs/ntfix/ntfix2/differ/uring-split-standard/hexpire-a0-s7.txt):
HPTTL returned 107502935413 ms for an absolute deadline of
1900000007777000000 ns. That implies a clock cut of 1792497072364000000 ns,
one millisecond before the measured request window beginning at
1792497072365000000 ns. The handler, its cached-clock source, and the
differential assertion are unchanged. The first focused PRE/POST repeat
passes 8/8 on each arm; five additional fresh PRE matrices pass 40/40.
[Initial repeats](docs/ntfix/ntfix2/expiry/results.json),
[bounded PRE rolls](docs/ntfix/ntfix2/expiry-pre-rolls/results.json).
Thus this failure was **not reproduced on PRE**, and remains unresolved;
the focused successes do not replace the failed standard run or establish
that its cause is pre-existing.

The AUTH-versus-arity difference is directly reproduced on frozen PRE and
POST in both modes: a ten-argument unauthenticated PING returns the arity error,
where Redis returns NOAUTH; all keep the connection open. See each
`auth-arity.json` under [controls](docs/ntfix/ntfix2/controls/).
The valid ten-argument DEL in N3 isolates the protocol count boundary while
retaining this separate finding.

The existing `respresume-unit` also passes all three groups. The migration
unit initially refused the seven-CPU client mask because its fixture requires
eight allowed CPUs; rerunning this in-process unit on 96–111 passes all six
ordinary/R7, 1s/2s, client-LB/FLIP migration witnesses. Both execution receipts
are retained under `docs/ntfix/ntfix2/post/`.

Final checks repeat all **34 `make -q` checks successfully**, including `all`
and both concrete parked/no-wake arms, without rebuilding or changing the
candidate. Python compilation, shell syntax, and `git diff --check` pass.
All lane listeners are gone. The final hashes, oracle/source identity, CPU
masks, unchanged EXPECT constants, and freshness results are recorded in
[artifacts.json](docs/ntfix/ntfix2/artifacts.json) and
[final-freshness.json](docs/ntfix/ntfix2/production/final-freshness.json).

### Gate accounting

N3 and N4 add **DQ = +2, DF = +2** in ntfix2. Including retained N1/N2, the
complete lane adds **DQ = +4, DF = +4** relative to PRE `567d3b8e3`.

| Row | Row definition in `tests/gate.sh` | Collection line |
|---|---:|---:|
| N1 INFO received bytes exact (also exact sent bytes) | 1860 | 3802 |
| N2 TLS silent-peer close after reply | 3233 | 3884 (`tls`) |
| N3 RESP pre-AUTH limit errors | label 3252; `row_begin` 3254 | 3884 (`tls`) |
| N4 RESP query-buffer frontier | label 3253; `row_begin` 3254 | 3884 (`tls`) |

All collection sites precede the quick-tier exit at **3934**. Thus the
maintainer-owned counts should become **EXPECT_QUICK 637 → 641** and
**EXPECT_FULL 654 → 658**. Neither constant was edited.

### Arms and maintainer merit request

| Arm | Path | SHA-256 |
|---|---|---|
| PRE `567d3b8e3` | `build/ntfix-pre/tomokv` | `5c8ca908bc4babe1a2ef6dcae4d3d3a60900aa8de6ecc78019a02c8c7c30b8c5` |
| POST (production source through `7aa2b2aba`) | `build/tomokv` | `d6876ec3e8ff9a1d6df911ffac8e0f93cf609c1ecbb82a9014d12780bc280c01` |
| **PAD A: behaviour twin** | `build/tomokv-ntfix-pad-a` | `fa5564d4e9f6b65eddb17016168a8b8ee520609a19a4820f68cbb02e8ab89a3f` |

PAD A relinks the frozen PRE objects in their original order, adding 2,672
unreachable NOP bytes to match POST's aggregate `.text` size of 7,657,788.
It retains all 10,144 PRE text-function symbol addresses and sizes, including
duplicate local names, the GNU IBT/SHSTK property, and the PLT layout.
This is a **total-text-size control**, not a
claim that every POST function has PRE placement.
[Build/validation receipt](docs/ntfix/ntfix2/pad/receipt.json);
reproducible builder: `docs/ntfix/pad.py`.
All sixteen directed row outcomes on PAD A also match frozen PRE exactly;
[behaviour receipt](docs/ntfix/ntfix2/pad/behaviour.json).

The first generic padding attempt was rejected because an assembly object
without `.note.gnu.property` dropped IBT/SHSTK and changed the PLT. Its receipt
is explicitly named `rejected-first-control-*`; it is not a measurement arm.

Use the gate's own unchanged ABBA instrument, the maintainer's scheduled quiet
box and qualified pins/load plans, these exact arm hashes, and contemporary
same-binary nulls:

| Required cells | Arms | Verdict |
|---|---|---|
| Existing **14 generic cells**, unchanged copy in [generic14.cells.txt](docs/ntfix/ntfix2/merit/generic14.cells.txt) | PRE/PRE null, PRE/POST, PRE/PAD A | Every cell must retain its existing per-cell rate or p1 latency score at matched offered load |
| Existing **32 epoll twins**, `h01-epoll` through `h32-epoll`, unchanged copy in [epoll32.cells.txt](docs/ntfix/ntfix2/merit/epoll32.cells.txt) | Same arms; the cell's existing `--net-io epoll` | Same per-cell no-regression verdict; use epoll's own qualified load floors/null |

The generic IDs are `h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,
d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`, from the existing
`docs/lbplanner/generic-cells.txt`. Cell-file hashes and offline parser counts
are in [cells.json](docs/ntfix/ntfix2/merit/cells.json). No cell definition,
instrument assertion, load plan or acceptance tolerance was changed.

Report per-cell matched-load rate/latency, cycles/op, IPC and instructions/op
for every arm. The matched-load score decides merit; instructions and IPC
explain it. A losing cell cannot be averaged away, and an unresolved identical
arm comparison is not a pass. PAD A diagnoses aggregate text-size effects;
it cannot exclude all internal placement effects. No performance measurements
were run by this lane.
