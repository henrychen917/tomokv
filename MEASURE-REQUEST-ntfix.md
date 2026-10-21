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

## ntfix3

N4 now uses PRE's conservative computation on the common path and consults the
saved parser frontier only when the existing bound would constrain input.
This is a candidate for merit review, with no throughput claim. The maintainer's
ntfix2 result motivating it was `d8s_l1` at −1.77 / −0.16 / −1.96% over three
ABBA blocks (median −1.77%, measured two-standard-deviation band 1.63%);
the earlier PAD-A/PRE result there was −0.10%. Those are supplied results,
not measurements made by this lane.

### Source and common-path accounting

The only new production source edit is `src/net/conn.h`; three compiler budgets
change in the Makefile. N1, N2, N3, and the epoll output-accounting fix remain.

- The query check first evaluates `queued > limit || rlen - rpos > limit - queued`.
  Only the conservative overflow branch evaluates the frontier-aware suffix.
  Equality stays legal, and queued MULTI arguments remain included.
- The receive path first computes PRE's cap using `rpos`. Its existing growth
  clamp and receive-offer clamp comparisons enter an unlikely, out-of-line cold
  refinement when that cap binds. The ordinary path does not read either the
  pending-frontier flag or `RespFrontier::next`.
- Cap equality also refines: a saved prefix can permit growth that the
  conservative cap suppressed, or invalidate the exact-limit exception for a
  short receive. Two added cases in the existing frontier unit require an
  actually armed parser frontier and check both growth and no-growth outcomes.
- A compile-time helper shares the allocation logic between the ordinary and
  cold bodies. There is no new runtime predicate beyond the existing bound/clamp
  comparisons, no runtime mode, field, allocation policy, retry, or lock.

[Common-path disassembly and explanation](docs/ntfix/ntfix3/common-path/README.md)
show the production receive body and a compile-only wrapper around the actual
query predicate. The query wrapper returns at +0x21 when the conservative bound
passes; frontier access begins only on the branch to +0x30. The receive helper's
frontier accesses reside in `read_space_refined`, marked `noinline,cold`.
This proves conditional access, not byte identity or performance.

The Redis 7.4 rule remains exactly the ntfix2 rule described above: check before
parsing newly received bytes, exclude only headers/arguments consumed on an
earlier parse pass, retain incomplete headers/payloads, and include queued MULTI
arguments. No buffer bytes move as part of accounting.

### PRE reconstruction and identity attempt

The pruned PRE objects were rebuilt from `git archive 567d3b8e3` in
`build/pre-src`, with that commit's unchanged Makefile. The only extra compiler
option maps the archive's debug directory back to the original worktree:
`-fdebug-prefix-map=/home/user/Projects/cx-ntfix/build/pre-src=/home/user/Projects/cx-ntfix`.
The rebuilt complete ELF is SHA-identical to frozen PRE **5c8ca908** before any
identity comparison or PAD link. [Rebuild receipt](docs/ntfix/ntfix3/pre/rebuild.json).

Eight PRE and 31 POST compile-only trials cover all eight receive/dispatch
translation units. All eight PRE recompiles reproduce every reference body.
The initial IPA sizes grow by 127 instructions in main, 142 in genthread, and
172 in rl2s/reorder. Three selected budget changes restore eight selected hot
bodies relative to the initial ntfix3 build:

| Object | ntfix2 budget | ntfix3 budget | Unedited hot differences before → after |
|---|---:|---:|---:|
| `src/core/genthread.o` | 129487 | 129557 | 3 → 0 |
| `db0/src/core/genthread.o` | 129744 | 129830 | 1 → 0 |
| `db0/src/core/reorder.o` | 148398 | 148538 | 5 → 1 |

Other existing budgets remain. The attempted explicit budget for src reorder
made identity worse and was rejected. Exact commands, hashes, all trial
differences, and selection rationale are in
[identity-attempt](docs/ntfix/ntfix3/identity-attempt/README.md).

| Unmodified strict audit against PRE | Final POST result |
|---|---|
| Command handlers | **1,211/1,211 identical** |
| `ccfix_audit.py`, all emitted bodies | 16,294/16,546 identical; **252 changed** |
| `ccfix_audit.py`, selected hot bodies | 1,160/1,214 identical; **54 changed** |
| `lbstall_artifacts.py compare` | 1,156/1,210 identical after resolving relocations; 1,148 raw-byte identical |
| Linked `.text` | 7,655,116 → **7,661,036 bytes** |

All three strict identity tools exit 1; those failures are retained, not called
passes. Every remaining changed hot body, object copy, and clone has its sizes
and reason in [changed-hot-bodies.md](docs/ntfix/ntfix3/identity/changed-hot-bodies.md).
The [receive/parse/writeback inventory](docs/ntfix/ntfix3/identity/changed-receive-parse-bodies.md)
also covers receive bodies outside the strict tool's hot-name filter;
[the complete table](docs/ntfix/ntfix3/identity/changed-bodies.md) lists all 252.
Reasons distinguish N1 epoll accounting, N2 TLS wakeup/output accounting, N3's
error-exit classifier, N4's cold refinement, and compiler inlining/codegen.

Full receive/parse identity is **not restored**. In particular, the common
receive helper is newly outlined in main and grows from PRE's 337-byte reorder
copy to 371 bytes plus a 38-byte cold clone. Src reorder retains three unedited
flush/sweep differences; db0 reorder retains the 796 → 729-byte fused sweep
difference. These are explicit merit-review limitations, not reasons to stop.

### Correctness and builds

All builds use CPUs 80–95 and `-j16`; correctness servers use 80–87, the pinned
Redis 7.4 oracle uses 88, and clients use 89–95. Candidate boots use 16 shards,
one database, fused/read-local 1 or split/ratio 6:2. Ports are 22800–22802;
the gate self-test's socket fixture reserves 22899. The in-process migration
unit requires eight allowed CPUs and runs within 80–95.

The oracle has no TLS listener: decrypted candidate TLS replies are compared
with the pinned oracle over TCP, as in ntfix2. The driver records boot commands
and stops only its owned children. `runtime.json` locks the final POST hash
before each job.

| Required proof | ntfix3 result |
|---|---|
| N3/N4 directed rows, PRE fail / POST pass | **PASS**: PRE fails all 8 defect/mode/engine legs; POST passes all 8, with TCP and TLS in each. [PRE](docs/ntfix/ntfix3/pre/rows.log), [POST](docs/ntfix/ntfix3/post/rows.log) |
| Retained N1/N2 rows on POST | **PASS**, all 8 legs; all 16 N1–N4 POST rows pass. [Ledger](docs/ntfix/ntfix3/post/rows.log) |
| `netcap-unit frontier` | PRE **FAIL as required** at the queued-MULTI assertion; POST **PASS**, including both added cap-equality cases. Full netcap unit also passes. [PRE](docs/ntfix/ntfix3/pre/frontier-unit.log), [POST](docs/ntfix/ntfix3/post/frontier-unit.log), [full unit](docs/ntfix/ntfix3/post/netcap-unit.log) |
| Unchanged limits corpus: 2 modes × 2 engines × TCP/TLS | **PASS, 0 differences** in every geometry. [Ledger](docs/ntfix/ntfix3/post/limits.log), exact compressed streams and differences in the adjacent `limits/` tree |
| Fragment corpus, including close cases | **PASS**, 4,692 trials × 8 combinations = **37,536 trials**, zero differences; RESP2/RESP3, seeds 7/19/20/23, all close-case families enabled. [Ledger](docs/ntfix/ntfix3/post/fragments.log) |
| RESP/netcap/TLS batteries with their gate boot contracts | **PASS**, 12/12 mode/engine/battery legs. [Ledger](docs/ntfix/ntfix3/post/batteries.log) |
| Respresume unit and migration witnesses | **PASS**, all three parser groups and all six ordinary/R7 migration witnesses. [Unit](docs/ntfix/ntfix3/post/respresume-unit.log), [migration](docs/ntfix/ntfix3/post/respresume-migration.log) |
| `python3 tests/gates_test.py` | **PASS**, 66 tests in 315.429 seconds, plus the nested 14-test persistence self-test. [Log](docs/ntfix/ntfix3/post/gates-test.log) |
| `make all`, all `job_production_units` targets, freshness | **PASS**: 31 named targets plus both live-control binaries; all 36 build/freshness commands succeed. [Results](docs/ntfix/ntfix3/production/results.json) |
| Full gate / ABBA / performance benchmarks / measurement load generators | **NOT RUN** — maintainer-owned and excluded from runtime authorization |

The final netcap unit reports the unchanged locked layouts: `Op=336 Client=1984 ThreadCtx=1408 Shard=1440 FlatStore=944 Rob=192 AtomicEntry=144 Config=624`.

The completed `make -W Makefile -j16 all` and production-target builds supersede
the retained interrupted preliminary build logs. All 34 final concrete freshness checks also pass ([receipt](docs/ntfix/ntfix3/production/final-freshness.json)). The production server build has no warnings; the unit build repeats the same 13 custom-allocator mismatch warnings present in ntfix2, in unchanged `atomic_survivors_unit.cc` and `lbplanner_unit.cc`. The unit additions add no gate
row: **ntfix3 DQ = 0, DF = 0**. The lane's existing total remains +4/+4 relative
to PRE; its collection sites and quick-tier position are unchanged from ntfix2.
`EXPECT_QUICK` and `EXPECT_FULL` are untouched.

The broad standard `differ_gate.sh`/INFO matrices are **NOT RUN in ntfix3**:
they are outside this refinement's requested matrix. The earlier one-millisecond
HPTTL finding, default-cipher kTLS gauge finding, and AUTH-versus-arity difference
remain documented in ntfix2; this work does not claim to resolve them.

### Artifacts and maintainer merit request

| Arm | Path | SHA-256 |
|---|---|---|
| PRE `567d3b8e3` | `/home/user/Projects/bins/ntfix-pre-5c8ca908` (identical rebuild at `build/ntfix-pre/tomokv`) | `5c8ca908bc4babe1a2ef6dcae4d3d3a60900aa8de6ecc78019a02c8c7c30b8c5` |
| ntfix3 POST | `/home/user/Projects/cx-ntfix/build/tomokv` | `2a102311d91b99bcff78af38742c1176bec5634ae9f1875af8cb74e645d9075b` |
| **PAD A — behaviour twin** | `/home/user/Projects/cx-ntfix/build/tomokv-ntfix-pad-a` | `65c81751a6c56e6c96f19102d788cffec0e71a86ce5799b19de58404fa2c6ddd` |
| Previous ntfix2 POST, diagnostic reference | `/home/user/Projects/bins/ntfix-post-d6876ec3` | `d6876ec3e8ff9a1d6df911ffac8e0f93cf609c1ecbb82a9014d12780bc280c01` |

**PAD A is PRE behaviour with POST's aggregate `.text` size/layout control.**
It relinks the verified PRE objects in their original order and appends 5,920
unreachable NOP bytes, matching POST's 7,661,036-byte `.text`. All 10,144 PRE text
function addresses and sizes, GNU IBT/SHSTK properties, and PLT layout remain
unchanged. It controls total text size; it does **not** reproduce POST's internal
function placement. [Build/validation receipt](docs/ntfix/ntfix3/pad/receipt.json).
All 16 directed PAD row outcomes match frozen PRE exactly. [Behaviour receipt](docs/ntfix/ntfix3/pad/behaviour.json).

Use the maintainer's scheduled quiet box and the gate's unchanged ABBA instrument,
qualified pins/load plans, these exact hashes, and contemporary same-binary nulls:

| Cells | Arms and blocks | Deciding result |
|---|---|---|
| First, **`d8s_l1`**, then **`p8g` and `p8s`**; unchanged [p8 focus file](docs/ntfix/ntfix3/merit/p8-focus.cells.txt) | PRE/PRE null, PRE/POST, PRE/PAD A; at least the same three ABBA blocks used for ntfix2 | Per-cell matched-load rate and its qualified band; determine whether the d8s_l1 regression is removed without a p8 control regression |
| All existing **14 generic cells**, unchanged [cell file](docs/ntfix/ntfix3/merit/generic14.cells.txt) | Same arms and instrument | Every cell retains its existing rate or p1 latency score at matched offered load; no averaging away a losing cell |

The three priority cells are already members of the generic 14; there are 14
distinct required definitions, not 17. `d8s_l1` is 1s, read-local 1, SET, p8,
512 connections, eight memtier instances; `p8g/p8s` retain their existing
read-local-0 GET/SET definitions. Depth-1 cells cannot clear a receive-cost
regression in the server-bound p8 cell.

Report per-cell rate/latency, cycles/op, IPC, and instructions/op. Matched-load
rate/latency decides; instructions and IPC explain it. Keep the existing
per-cell qualification rules and contemporaneous nulls; the historical 1.63%
band is context, not a newly invented tolerance. PAD A should remain flat if
POST's movement is behavioural; this aggregate-size control cannot exclude all
internal placement effects. An optional old-POST/new-POST p8 comparison can
isolate recovery from ntfix2, but cannot replace PRE/POST acceptance.

No performance measurement, gate coordinator, or push is run by this lane.

All requested ntfix3 correctness jobs passed on the recorded POST. [Runtime manifest](docs/ntfix/ntfix3/runtime.json) and [final artifacts](docs/ntfix/ntfix3/artifacts.json) record commands, hashes, CPU/port allocation, unchanged gate constants, and completed listener cleanup. Python compilation, shell syntax, and `git diff --check` also pass. Work is committed on `cx-ntfix`; no push.

## ntfix4

Merged `origin/cpp` at **bce4eb0aa6ab5b855903e201f6f19b321e09cba0** into
`cx-ntfix` in `339b546e2`. N1/N2/N3, N4's ntfix3 cold refinement, and epoll
output accounting are retained alongside all wave3 changes. The three network
headers are unchanged from ntfix3. No throughput claim is made; the maintainer
owns the merged/headline null and landing gate.

### Merge and gate accounting

The actual conflicts were `Makefile`, `tests/gate.sh`, and the root
`MEASURE-REQUEST`. The merge retains the respresume/lottery/aoforder targets,
both `aoforder` and `ntfix_input` job registrations, the new wave3 count
comments, and both request-file histories. The Makefile initially takes the
headline's budgets, then the compile-only derivation below adjusts four.

The fixture merged automatically but lacked the four ntfix labels. It now
retains every headline label and adds exactly N1–N4. The old conditional N3/N4
label assignment was invisible to the source-only inventory parser, which
counted N3 twice. An explicit finite case/label list now names both rows
without changing their tests or collection sites.

**DQ = +4, DF = +4 versus bce4eb0aa; required counts are 669 quick / 686 full
(665/682 + 4/4).** ntfix4 adds no further row beyond the lane's existing four.
The actual `EXPECT_QUICK=665` and `EXPECT_FULL=682` lines remain byte-identical
to the fetched headline; only the maintainer may change them.

| Row | Definition/label line in `tests/gate.sh` | Collection line |
|---|---:|---:|
| N1 INFO received bytes exact (also exact output bytes) | 1908 | 3910 (`ntfix_input`) |
| N2 TLS silent-peer close after reply | 3341 | 3997 (`tls`) |
| N3 RESP pre-AUTH limit errors | label 3358; `row_begin` 3362 | 3997 (`tls`) |
| N4 RESP query-buffer frontier | label 3359; `row_begin` 3362 | 3997 (`tls`) |

All four collection sites precede the **quick-tier exit at line 4047**.
[Source/fixture receipt](docs/ntfix/ntfix4/ledger.json): source 669/686,
fixture 686, **zero missing and zero extra labels**, including multiplicities.
The unmodified fixture checker exits **1 solely because EXPECT_FULL remains
682**, while source and fixture both contain 686. Its refusal is retained;
source-count validation with 686 in memory passes and does not edit a file or
claim a gate pass.

### Compile-only derivation and remaining body differences

The headline reference is built from an unmodified `git archive bce4eb0aa`
inside this worktree, with its original Makefile and `taskset -c 80-95 make
-j16 all`. Its freshness check passes. Before rebuilding POST, ntfix3's binary
and production objects were frozen in `build/ntfix4/ntfix3/`; that binary still
has SHA-256 **2a102311d91b99bcff78af38742c1176bec5634ae9f1875af8cb74e645d9075b**.
[Reference provenance](docs/ntfix/ntfix4/references.json).

Eight headline reference trials reproduce every emitted body. **56 merged
compile-only trials** cover main/genthread/rl2s/reorder in both namespaces.
The initial IPA-size growth over headline is +127 / +142 / +172 / +172,
respectively. Selection first minimizes hot bodies differing from both eligible
references, then other residual bodies, then total differences; no difference
is silently normalized away. The db0 reorder `max-inline-insns-auto=14` and
db0 main `=18` options remain.

| Object | Headline budget | Merged budget |
|---|---:|---:|
| `src/core/genthread.o` | 129975 | 130084 |
| `db0/src/core/genthread.o` | 130179 | 130316 |
| `src/core/reorder.o` | 147778 | 147950 |
| `db0/src/core/reorder.o` | 148779 | 148944 |

Main and rl2s keep their headline budgets; the main/db0-rl2s alternatives
produce the same bodies, while changing src rl2s introduces four extra hot
differences. All other production unit budgets remain at headline values.
The selected budgets restore the initial merged build's three unedited db0
reorder hot differences. [Derivation, ranges, and selection](docs/ntfix/ntfix4/budget-README.md),
[exact chosen trials](docs/ntfix/ntfix4/selected.json),
[final production objects equal all eight chosen trials](docs/ntfix/ntfix4/final-equals-selected.json).

| Final inventory | Result |
|---|---|
| Command handlers versus headline | **1,211/1,211 identical** |
| All emitted bodies versus headline | **16,435/16,683 identical; 248 changed** |
| Selected hot bodies versus headline | **1,168/1,218 identical** |
| Additional hot bodies equal to ntfix3, which changed those bodies | **30** |
| Remaining hot bodies equal to neither reference | **20 ordinary/R7 dispatchers** |
| All remaining bodies equal to neither eligible reference | **37: 20 hot + 17 other** |
| Linked `.text` | **7,730,449 → 7,735,985 bytes (+5,536)** |

The 20 parser bodies compose ntfix's N3/N4 behaviour with mkfix2's new
scatter-reply marker in inlined `release_op`. For example, db0 genthread's
`parse_and_dispatch<true,32,false>` keeps its 18,561-byte size but changes the
single `-2` scatter-marker check into the mask/comparison accepting both `-2`
and `-6`. GCC also changes control-flow placement and some inlining; db0 R7's
false dispatcher inlines `RespFrontier::finish`. These bodies cannot be called
byte-identical to either reference. [Explanation and exact disassembly](docs/ntfix/ntfix4/identity/dispatcher-composition.md).

Every one of the 248 changed bodies, object copies, and clones has both reference
sizes, POST size, and its reason in [the complete table](docs/ntfix/ntfix4/identity/changed-bodies.md).
The [50 changed hot bodies](docs/ntfix/ntfix4/identity/changed-hot-bodies.md) and
[20 remaining hot bodies](docs/ntfix/ntfix4/identity/residual-hot-bodies.md) are
also listed separately. The [machine-readable comparison](docs/ntfix/ntfix4/identity/dual-reference.json.gz)
records reference eligibility and equality. Remaining non-hot differences are
compiler inlining/codegen in unedited functions, not hand edits to force identity.

The unmodified `ccfix_audit.py`, `lbstall_artifacts.py compare`, and
`linked_bytes.py` each exit **1**, and those strict failures are retained in
[tool receipts](docs/ntfix/ntfix4/identity/tools.json). The smaller hot selector
finds 1,164/1,214 equal after relocation resolution (1,156 raw-byte equal).
Identity remains a proxy; the 20 compositions are explicitly handed to the
maintainer's merit review, with no identity stop and no performance verdict.

### Correctness receipts and build coverage

All builds/trials use CPUs **80–95**, `-j16`; correctness servers use **80–87**,
Redis 7.4 uses **88**, clients use **89–95**, and all listener ports are within
**22800–22899**. The proof driver boots 16 shards / one database, fused with
read-local 1 or split with ratio 6:2. The focused differential retains its
existing 16-database geometry. The in-process migration witness needs at least
eight allowed CPUs and runs on 80–95. Temporary gate-test state stays under
this worktree's `build/ntfix4/tmp`; its socket fixture uses port 22899.

The pinned oracle is `/home/user/Projects/redis74/src/redis-server`, SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.
It has no TLS listener, so the unchanged corpus compares decrypted candidate
TLS replies and close outcomes with the oracle's TCP stream. `limits-redis-tls`
files are that TCP reference, not evidence of a Redis TLS boot.

| Requested proof | Result |
|---|---|
| N1–N4 on merged POST | **16/16 PASS**, both modes and engines; N3/N4 include TCP and TLS. [Ledger](docs/ntfix/ntfix4/post/rows.log) |
| Same rows on bce4eb0aa | **12 expected failures / 4 unaffected controls pass**: N1 fails epoll, N2 fails uring, N3/N4 fail both engines, in both modes. The driver requires this exact outcome set. [Ledger](docs/ntfix/ntfix4/headline/rows.log) |
| Current `netcap-unit frontier` on headline / POST | **Headline FAIL as required, POST PASS**, including cap equality and queued MULTI. Full POST netcap unit also passes. [Headline witness](docs/ntfix/ntfix4/headline/frontier-unit.log), [POST frontier](docs/ntfix/ntfix4/post/frontier-unit.log), [full unit](docs/ntfix/ntfix4/post/netcap-unit.log) |
| Unchanged respresume limits corpus | **0 differences**: nine cases × 2 modes × 2 engines × TCP/TLS; exact streams retained. [Ledger](docs/ntfix/ntfix4/post/limits.log) |
| Fragment corpus with close cases | **37,536 trials, 0 differences**: 4,692 × eight mode/engine/transport combinations, RESP2/RESP3, seeds 7/19/20/23, every close-case family enabled. [Ledger](docs/ntfix/ntfix4/post/fragments.log) |
| RESP/netcap/TLS batteries | **12/12 PASS**, using their unchanged gate boot contracts. [Ledger](docs/ntfix/ntfix4/post/batteries.log) |
| Parser and migration units | **PASS**: all three parser groups and all six ordinary/R7, 1s/2s, client-LB/FLIP migration witnesses. [Parser](docs/ntfix/ntfix4/post/respresume-unit.log), [migration](docs/ntfix/ntfix4/post/respresume-migration.log) |
| Epoll `infofix`, both geometries, atomic 0/1, seeds 7/19/20/23 | **16/16 INFO legs PASS**. Split: 8/8. Armed fused: eight INFO + eight unchanged string controls + two read-local activity witnesses, 18/18. [Split](docs/ntfix/ntfix4/differ/epoll-split-infofix.log), [armed fused](docs/ntfix/ntfix4/differ/epoll-armed-fused-infofix.log) |
| `python3 tests/gates_test.py` | **66/66 PASS**, plus the nested 14-test persistence check. [Log](docs/ntfix/ntfix4/post/gates-test.log) |
| `make all` and every `job_production_units` target | **PASS**: 33 named targets plus both `mdbqsbr-live-arms` binaries; all 38 build/freshness commands return 0. [Build](docs/ntfix/ntfix4/post-build.log), [target inventory](docs/ntfix/ntfix4/production/targets.txt), [receipts](docs/ntfix/ntfix4/production/results.json) |

The locked layouts remain `Op=336 Client=1984 ThreadCtx=1408 Shard=1440
FlatStore=944 Rob=192 AtomicEntry=144 Config=624`. The server build has no
compiler warnings; the unit builds retain 13 custom-allocator mismatch warnings
in the unchanged atomic-survivors/lbplanner fixtures and one nested-make
jobserver notice. Every target is built and fresh despite those notices.
The phony live-arm aggregate is checked through each concrete binary's original
`BUILD_ROOT` and flags.

The armed INFO proof includes the unchanged string suite because INFO ends in
`CONFIG RESETSTAT`. Its read-local witnesses observe peaks of **29** hits for
atomic=0 and **27** for atomic=1, while the final counters are zero as expected
after reset. Both witnesses pass without changing an assertion or suite.
This focused proof does not claim coverage of the full standard differential
matrix. [Differential commands, environments, and results](docs/ntfix/ntfix4/differ/results.json).

The runtime driver verifies POST's hash before each job; the differential
records it before each geometry, and the final check requires all hashes to
agree. [Runtime manifest](docs/ntfix/ntfix4/runtime.json).
All **36 final concrete `make -q` checks return 0**, including `all` and both
live-control binaries with their original flags.
[Final freshness](docs/ntfix/ntfix4/production/final-freshness.json).
Python syntax, shell syntax, and `git diff --check` pass. The final listener
check finds no listener on 22800–22899; only owned child PIDs were stopped.
[Final artifacts and cleanup](docs/ntfix/ntfix4/artifacts.json).

### Final artifacts and maintainer handoff

| Arm | Path in this worktree | SHA-256 |
|---|---|---|
| Headline `bce4eb0aa`, fresh normal reference build | `build/ntfix4/headline-src/build/tomokv` | `247bb68cf027485c61269762216c73fc81de6cdb968b84c28b44f7ad1da87ca5` |
| **ntfix4 merged POST** | **`build/tomokv`** | **`db07cacf524e03f9907ac7c42c1c79b668792c322f9d73e3d127b2d07b18afae`** |
| Frozen ntfix3 body reference | `build/ntfix4/ntfix3/tomokv` | `2a102311d91b99bcff78af38742c1176bec5634ae9f1875af8cb74e645d9075b` |

The production source/budgets are fixed at `47fa7d9b1`; subsequent commits retain
proof and documentation. Use the final merged POST above for the maintainer's
**merged-versus-bce4eb0aa null** with the gate's unchanged instrument, cells,
CPU/load plan, and acceptance rules, then the landing gate. The 20 composed
hot bodies are explicit merit-review input. This lane supplies no rate,
latency, cycles/op, IPC, instruction-count, or throughput claim.

**NOT RUN:** performance benchmarks, measurement load generators, ABBA/null,
and `tests/gate.sh iteration` / landing gate: these remain maintainer-owned
and outside the correctness authorization. The broad standard differential
matrix is **NOT RUN in ntfix4**, because this task requests the focused epoll
INFO matrix; no claim is made to resolve the older ntfix2 findings outside
that coverage. A Redis TLS listener is unavailable in the pinned oracle;
all requested candidate TCP/TLS corpus legs were run against its TCP reference.

All requested ntfix4 correctness/build work is complete and passes. The source
fixture matches 686 labels; the maintainer still changes the required EXPECT
counts to **669/686**. Work is committed on `cx-ntfix`; nothing was pushed.

## ntfix5

2026-10-21; starts at `8ae8e65e5` on `cx-ntfix`. The three failed landing-gate
rows now run successfully through **`tests/gate.sh`'s actual `tls` job**.
`tlsboot` reads the argument following `--thread-mode` and omits its default
`--ratio 6:2` only for `fused` / `1s`. All row bodies and existing assertions
are unchanged. No production code changed and **`build/tomokv` was not rebuilt**.

### Boot argv preservation

[Every before/after argv](docs/ntfix/ntfix5/argv-before-after.txt) lists all
**15 expanded `tlsboot` invocations**, with source lines and shell quoting that
preserves empty and multiword arguments. The [NUL-delimited capture comparison](docs/ntfix/ntfix5/argv-before-after.json)
records each argument and both byte-stream hashes. The three historical boots
(`yes`, `optional`, and the explicit userspace coexistence cipher boot) and the
six ntfix split boots are **byte-identical**. The six ntfix fused boots differ
**only by removal of the two arguments `--ratio` and `6:2`**. Fixed environment
values are identical across captures; this is an argv audit, not a server run.

[The replayable audit](docs/ntfix/ntfix5/argv_audit.py) also requires the entire
gate source outside `tlsboot` to equal `8ae8e65e5`, including all call sites,
assertions, rows, and EXPECT constants. The added serverless regression test
covers both engines, the `fused`/`1s` and `split`/`2s` aliases, repeated mode
options, and unrelated password values `fused`/`1s`. Against the old helper it
fails exactly the four fused/1s × engine subtests; the other cases pass.
[Negative-control output](docs/ntfix/ntfix5/argv-negative-control.log.gz).

### Exact gate interface and geometry

The documented `GATE_ONLY_JOBS=tls` selection runs `release`,
`production_units`, and `tls` through the normal worker/finalizer machinery.
`quick` selects the correctness-only tier; no full iteration, ABBA, NIC tier,
or performance load generator runs. The explicit candidate bypasses the
release rebuild. The real production-unit prerequisites ran and were already
up to date, including the two live-arm binaries.

Both commands ran from `/home/user/Projects/cx-ntfix`:

```sh
taskset -c 80-95 env \
  REDIS74_ROOT=/home/user/Projects/redis74 GATE_ONLY_JOBS=tls \
  GATE_HISTORY="$PWD/build/ntfix5/history-post" \
  GATE_LEDGER="$PWD/build/ntfix5/post-ledger" \
  bash tests/gate.sh quick \
  --server-cores 80-87 --load-cores 88-95 --server-smt '' --load-smt '' \
  --ports 22800-22899 --candidate-binary "$PWD/build/tomokv"

taskset -c 80-95 env \
  REDIS74_ROOT=/home/user/Projects/redis74 GATE_ONLY_JOBS=tls \
  GATE_HISTORY="$PWD/build/ntfix5/history-pre" \
  GATE_LEDGER="$PWD/build/ntfix5/pre-ledger" \
  bash tests/gate.sh quick \
  --server-cores 80-87 --load-cores 88-95 --server-smt '' --load-smt '' \
  --ports 22800-22899 \
  --candidate-binary "$PWD/build/ntfix4/headline-src/build/tomokv"
```

This is one normal eight-server-core slot, not a changed server geometry:
**CPUs 80–87, 16 shards, split ratio 6:2; fused has eight unified threads and
read-local 1**. The coordinator and protocol clients use 88–95; prerequisite
build commands use only 80–95. TCP/TLS listeners are **22800/22801**. No
quiet-screen bypass, assertion relaxation, or alternate row driver was used.
The gate's optional quiet-file setting was not enabled. Separate row histories
keep these diagnostic failures out of the maintainer's standing history.

The pinned Redis directory contains binaries but lacks `src/server.h`,
`src/acl.c`, and `src/commands.def`, so both jobs print that preflight warning.
The selected TLS job has no ACL-source-generation row and does not boot Redis;
all selected jobs complete. The separately run oracle check below validates the
unchanged byte corpus against the requested binary.

### Actual results and failure witnesses

| Check | POST | Headline PRE `bce4eb0aa` |
|---|---|---|
| N2: silent peer closes after reply | PASS, all eight mode × engine × TCP/TLS legs | Aggregate FAIL; both io_uring modes receive the complete TLS reply but time out waiting for EOF; both epoll controls PASS |
| N3: pre-AUTH limit errors | PASS, 23 exact cases in each of eight legs | FAIL in all four mode/engine boots: the first TCP case returns `invalid multibulk length` instead of the unauthenticated-length error |
| N4: query-buffer frontier | PASS, four exact cases in each of eight legs, plus frontier unit | FAIL in all four mode/engine boots: the first TCP case closes before unconsumed input exceeds the limit |
| Other TLS rows | **17/17 PASS** | **17/17 PASS** |
| TLS job | **20 PASS / 0 FAIL** | **17 PASS / 3 expected FAIL** |
| PARTIAL gate including release prerequisite | **21 PASS / 0 FAIL, exit 0** | **18 PASS / 3 expected FAIL, exit 1** |
| Actual TCP+TLS listener boots | **15/15**, including six fused boots | **15/15**, including six fused boots |

POST has **all 12 mode/engine output files and all 24 transport legs**: eight
per new row. PRE has all 12 output files too; its failures occur inside the
unchanged defect assertions. PRE's N3/N4 TCP failures stop those scripts before
their TLS loop, and PRE's N2 io_uring EOF timeout stops before its TCP loop;
these unvisited PRE transports are not claimed as exercised. No PRE or POST
server log contains the ratio refusal. Each fused server log records
`thread-mode=1s`, `read-local=1`, both live listeners, and a shutdown report.
The `netcap-unit frontier` invocation remains the current worktree unit even
when `--candidate-binary` is PRE; PRE's N4 verdict is established by the live
server failures, not by an assertion that this unit is a PRE build.

Receipts: [POST partial ledger](docs/ntfix/ntfix5/post/ledger.partial),
[PRE partial ledger](docs/ntfix/ntfix5/pre/ledger.partial),
[POST TLS output](docs/ntfix/ntfix5/post/tls/output.log),
[PRE TLS output](docs/ntfix/ntfix5/pre/tls/output.log),
[verified per-leg results and compressed boot-log index](docs/ntfix/ntfix5/results.json),
[verification replay](docs/ntfix/ntfix5/verify_results.py).
Original runs remain in `build/gate-run.8snCc5` (POST) and
`build/gate-run.mX3NSO` (PRE). Their plans, ledgers, prerequisite logs, battery
outputs, and all 30 server logs are retained under `docs/ntfix/ntfix5/`.

### Harness self-test, oracle, and scope

The first `gates_test.py` attempt passed 67 tests plus its nested 14-test
persistence check, but the nested persistence socket fixture used `bind(..., 0)`
and therefore requested a port outside the lane's fixed allocation. That
attempt is **not counted as port-compliant**; its
[unmodified output is retained](docs/ntfix/ntfix5/gates-test-initial-port-exception.log.gz).
The one-line fixture change in `tests/persistfix.py` makes it honor the existing
`GATE_TEST_PORT` variable, matching the main harness fixture. No assertion
changed. The final rerun uses:

```sh
taskset -c 80-95 env TMPDIR="$PWD/build/ntfix5/tmp" GATE_TEST_PORT=22899 \
  python3 tests/gates_test.py
```

The final port-constrained rerun **passes 67/67 tests plus the nested 14/14**,
exit 0. [Complete output](docs/ntfix/ntfix5/gates-test.log). Shell syntax and
`git diff --check` also pass. The final listener check finds no listener on
22800–22899; both gate finalizers and the oracle cleanly reaped their children.

The supplemental oracle uses `/home/user/Projects/redis74/src/redis-server`
on CPUs 80–87 / port 22802. Redis identifies itself as **7.4.10** and passes
all **23 N3 + four N4 exact cases** over TCP, with the unchanged corpus.
[Corpus output](docs/ntfix/ntfix5/oracle/corpus.log),
[exact server argv and digest](docs/ntfix/ntfix5/oracle/result.json),
[replay](docs/ntfix/ntfix5/oracle_check.py).
This supplements, and does not replace, the actual gate-job results above.

| Binary | SHA-256 |
|---|---|
| Unrebuilt POST `build/tomokv` | `db07cacf524e03f9907ac7c42c1c79b668792c322f9d73e3d127b2d07b18afae` |
| PRE `build/ntfix4/headline-src/build/tomokv` | `247bb68cf027485c61269762216c73fc81de6cdb968b84c28b44f7ad1da87ca5` |
| Redis 7.4 oracle | `ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b` |

ntfix5 adds **zero gate rows**. ntfix remains **DQ/DF +4/+4**: N1 is collected
at `tests/gate.sh:3918`, the TLS job containing N2–N4 at line **4005**, both
before the quick-tier exit at line **4055**. Required counts remain **669/686**;
`EXPECT_QUICK` / `EXPECT_FULL` are unchanged from the supplied HEAD.

**NOT RUN:** full `tests/gate.sh iteration`, performance benchmarks, measurement
load generators, ABBA/null, and NIC measurements: these remain maintainer-owned
and outside this lane's correctness authorization. No performance claim or PAD
arm is introduced. Nothing was pushed.
