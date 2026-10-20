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
