## protofix

NET-INLINE-1 is fixed on `cx-protofix`, based on wave8 `83e0b809d0fdeb4bf43647bd0cada7a4f14f241d`. Native source and compiler flags are frozen at `4fa243af1`; later commits contain proof scripts and receipts. Nothing is pushed. Performance and the full landing gate remain **NOT RUN**, as required; the maintainer's requested null is still outstanding. Correctness results below will be completed from the ongoing whole-job campaign.

### Behavior and ownership

`src/net/resp.h` implements Redis 7.4 `sdssplitargs` semantics for quoted inline requests: double-quote escapes including binary `\xHH`, single-quote `\'`, literal unquoted backslashes, empty arguments, unquoted prefixes before an opening quote, and mandatory whitespace/end after a closing quote. Invalid or unfinished quoting produces the exact protocol error and closes the connection. The existing NUL/LF search, empty-line behavior and unfinished-line 64 KiB bound are retained. Redis only applies that bound while waiting for LF; it is not an unconditional maximum for an already complete line.

One cold detector replaces the old validation scan. Only a quote enters the decoder; ordinary inline requests retain their existing argument storage and allocate nothing extra. The decoder first validates/counts, then allocates one block containing the argv slices and their decoded bytes. The Op owns that block through its existing argv pointer and retirement cleanup. Receive bytes and reply storage are never overwritten. `src/exec/op.h` only grants decoder access; no structure grows. No ownership, MVCC, QSBR or ordering rule changes.

The plain tokenizer also matches Redis's less obvious whitespace grammar: leading ASCII whitespace is skipped; within an unquoted argument, VT/FF remain literal while space/tab/CR delimit it. RESP parsing source is unchanged. The common inline path adds zero instructions in the measured parser scopes below.

### Frozen artifacts

| Arm | File in this worktree | SHA-256 |
| --- | --- | --- |
| PRE, exact `83e0b809d` | `build/tomokv-protofix-PRE` | `37b3a2f583859dff5e9bc74dd864f7257b6f486371883a0df4d12a0d5393912b` |
| POST | `build/tomokv-protofix-POST` (same bytes as `build/tomokv`) | `e99c3f23182c0872214c2e1475cb64cb4d8aa3dd27ebeaf769ca0197c4b5ba5b` |
| PAD-A, **kind A: behavior twin** | `build/tomokv-protofix-PAD-A` | `f78a694afa361d939699df9993f98239c67adf8b6bf589671a1a051b0af9f9a8` |

PRE was built from a `git archive` of the named commit under `build/protofix/pre-source`. Builds use CPUs 0–15 and `-j16`. PRE `.text` is 8,435,415 bytes; POST and PAD-A `.text` are 8,437,351 bytes (+1,936).

PAD-A is an exact POST-layout control, built by `docs/protofix/pad_a.py`. PRE's two namespace-specific inline parsers replace POST's parser slots; PRE validators occupy unused decoder slots. Direct-call and literal displacements are relocated with instruction-boundary checks. All other bytes, section sizes and function addresses remain POST-identical, apart from the new build-id. The byte-level manifest is `docs/protofix/pad-a.json`. This is a disposable measurement binary, with POST debug/unwind metadata in the transplanted parser slots; do not use it for parser stack-unwind diagnostics.

### Instruction and identity proof

The established serverless counter from `tools/execindex_scope.py` runs with only artifact paths and affinity changed. `docs/protofix/counts.py` uses fresh final destinations, avoiding stale traces from earlier compiler trials. All **24** command-scope PRE/POST comparisons match exactly: GET/SET/INCR × batch 1/32 × 1s/2s × normal/db0. Every total, per-function count and excluded external-call count agrees. Atomic is 1, slowlog threshold is -1. These counts cover named production command routines and inlined code, exclude external-library bodies, and are not cycles/op or throughput measurements. Full numbers and trace receipts: `docs/protofix/instructions-final/`.

The instrument supplies deterministic clock results (one intercepted clock call per command scope). Wrapper guards refuse to overwrite or reuse existing traces; reproduce into new directories with, for example, `PROTOFIX_COUNT_TAG=review1 python3 docs/protofix/counts.py` and the same environment setting for `parser_counts.py`. The following counts are instructions per batch.

| Command / mode | normal batch 1 | normal batch 32 | db0 batch 1 | db0 batch 32 |
| --- | ---: | ---: | ---: | ---: |
| GET 1s | 939 → 939 | 18,578 → 18,578 | 818 → 818 | 18,705 → 18,705 |
| GET 2s | 1,559 → 1,559 | 18,423 → 18,423 | 1,051 → 1,051 | 18,163 → 18,163 |
| SET 1s | 1,068 → 1,068 | 22,706 → 22,706 | 955 → 955 | 23,089 → 23,089 |
| SET 2s | 1,688 → 1,688 | 22,551 → 22,551 | 1,188 → 1,188 | 22,547 → 22,547 |
| INCR 1s | 1,531 → 1,531 | 38,051 → 38,051 | 1,314 → 1,314 | 35,106 → 35,106 |
| INCR 2s | 2,151 → 2,151 | 37,896 → 37,896 | 1,547 → 1,547 | 34,564 → 34,564 |

The separate bounded parser witness checks exact parsed arguments and no extra allocation for ordinary requests. PRE → POST instruction counts:

| Protocol / command | Batch 1 | Batch 32 |
| --- | ---: | ---: |
| Plain inline GET | 502 → 482 | 14,979 → 14,339 |
| Plain inline SET | 754 → 720 | 23,043 → 21,955 |
| Plain inline INCR | 534 → 510 | 16,003 → 15,235 |
| RESP GET | 211 → 211 | 5,667 → 5,667 |
| RESP SET | 267 → 267 | 7,459 → 7,459 |
| RESP INCR | 211 → 211 | 5,667 → 5,667 |

`docs/protofix/parser-instructions/` retains all 12 comparisons and trace logs. External-call counts match in every pair. `parser-provenance.json` binds all three entered out-of-line parser/helper bodies in each arm to identical instruction bodies in the corresponding production executable; the standalone fixture requires these parser symbols instead of unrelated executor-policy symbols, with a missing-body negative control. The trace therefore measures the production inline parser's instructions.

GCC inlining budgets in `Makefile` are adjusted to keep the larger cold inline parser from changing unrelated hot bodies. No runtime knob is introduced. The final strict linked audit has **765/765 hot groups with relocation-aware instruction identity**, including all 81 named groups entered by the command traces, both database images, late-listener parser clones, and the existing main command/dispatch selections. Additional checks cover `r7_run_loop` and fused `flip_control_pass`. The object audit compares 118 objects and 19,388 bodies: all 1,744 non-inline bodies in its hot selection agree; its other 30 selected occurrences are the deliberately replaced inline parser/validator. Opcode, register and immediate changes are not masked. Reproduce with `docs/protofix/identity.py`; receipts are `docs/protofix/linked-identity-frozen.json` and `docs/protofix/identity-frozen/`.

This is not whole-executable identity: the linked inventory has 16 changed groups. Twelve are the intended inline bodies/helpers in the two namespaces; three cold bodies differ in resolved reference annotations, and normal `pubsub_append_ack` has one additional `u64_to_dec` inlining (972 → 1,068 bytes). These differences remain visible in the strict report and go to the maintainer's null. Compiler trials and earlier audits are retained in `docs/protofix/compiler-exploration.tar.gz`.

### Directed oracle and gate accounting

`tests/inline_protocol.py` is the single directed battery. It requires Redis **7.4.10**, compares each endpoint independently to explicit wire bytes, and verifies EOF after protocol errors or continued operation after success. It covers every specified escape, all 256 hex bytes in both hex alphabets with both line endings, invalid/short hex, embedded NUL, empty/quoted command names and arguments, malformed quotes, all ASCII whitespace, fragmented input, the 64 KiB boundary, a 257-turn mixed RESP/inline pipeline, heap argv, and transaction retention. An armed read-local leg must increase `read_local_hits` on decoded keys. There are 148 cases per endpoint, including 1,024 individually checked hex steps.

The existing `respcompat` job runs both its original protocol battery and the new battery over the complete 32-way mode × atomic × read-local × reorder × database-image product. The whole job is selected under both engines (64 target boots). It remains one aggregate row and adds no row count. The serverless ASAN+UBSAN lifetime witness additionally checks receive-buffer overwrite, reply growth, 100 reparses/reuses, 1,001 decoded arguments and error cleanup.

The exact `inline_quoted` test and four-leg job were taken from cx-gaterows5 commit `033e94d79326f50c61cce54ee1c7ec63da69f9a3` by a partial cherry-pick, committed as `2403bab77`. PRE fails all seven valid cases in each 1s/2s × epoll/uring leg. Final POST passes all four legs (seven cases each). PAD's corresponding negative-control receipts are pending below.

**DQ=+4, DF=+4**, counted by the four row emissions collected at `tests/gate.sh:5554`, above the quick-tier exit block beginning at line 5785. The imported job is four scored rows, despite being one job name. Wave8's actual 806/823 becomes **810/827**. The stale maintainer-owned constants remain untouched at 798/815; do not apply this delta again if importing the same four rows through the full gaterows5 branch.

The four corresponding receipt-fixture labels are also copied from that gaterows5 commit. Source inventory and fixture both contain exactly 827 rows, with no missing/extra labels. The standard fixture guard deliberately still exits 1 solely because protected `EXPECT_FULL=815`; `docs/protofix/row-inventory.json` retains the diagnostic. This is not a runtime failure or a passing full-gate receipt.

### Correctness campaign

All gate invocations are **selected whole jobs** via `GATE_ONLY_JOBS`; the positional `iteration` argument selects the gate's job interface, never the forbidden full iteration. Ordinary boots use eight server CPUs 0–7, ratio 6:2, 16 shards, load CPUs 8–15, and owned ports 20300–20329; a job's explicit specialized geometry is retained (for example, the 64-shard ownership-debug row). Extra native builds stay on 0–15 with `-j16`; gate self-tests use port 20398 and the isolated pipeorder supplement uses port 20350. The Redis oracle and every test server are confined to the authorized lane. The gate's existing correctness-only `GATE_PROOF_NO_RATES=1` is used for partial atomic batteries; their mechanism/window checks still run, and their rate assertion is explicitly skipped.

`docs/protofix/matrix.py` and `supplement.py` declare the complete job selections. `docs/protofix/jobs/` retains every command, source/gate/binary hash, log, ledger and verdict; a failed earlier attempt is never overwritten. The remaining runtime outcomes are pending completion of this campaign.

`make all`, all 45 `job_production_units` targets, both MDB parked/no-wake arms and the blockfix target have built successfully. **49/49 concrete `make -q` checks pass** with the POST digest unchanged. The phony MDB entry is checked through each concrete build root with its actual flags. Commands, logs and hashes are in `docs/protofix/production/receipt.json`; `production_build.py` reproduces them.

Earlier diagnostic attempts are retained: both servers rejected an incorrectly written single-quote fixture (corrected without changing production behavior); an intermediate build's broad run passed 111 rows and failed the DEBUG SLEEP window witness while compiler trials were active. The final matrix reruns that complete job without concurrent compile trials. These attempts are not final-binary pass claims.

The final fused/uring batch has a real reply failure: `debug-1` / `txn_nx` returned `[1, ERR no such key]` instead of `[1, 0]` at bare round 5,712 of 8,192. Values were `[nil, winner-b, winner-a]`; its 8,192 transactional rounds passed. Source/destination geometry was `[[10,2],[10,2],[3,3]]`. All requests in this battery are RESP. The full batch finished **50 passed / 1 failed**, retained under `docs/protofix/jobs/verified-fused-uring.*` and `build/gate-run.yUxg0h`. PRE and POST whole `debug-1` comparisons are queued; a later pass will not erase this failure.

The register's 2026-10-26 execindex addendum identifies the same live signature as **AT4-WOUND-1**, assigned to `woundfix`. The existing analysis, `docs/execindex/wound-window/DEFECT.md`, describes the D2 violation: a fragment can see `Wounded` and finish with an empty source image before the epoch cancellation is published, then commit a terminal `NoSuchKey` reply. `tests/txnorder_wound_window.cc` is its deterministic, serverless witness. This lane is running that unchanged witness on PRE and POST in both modes and both namespaces; source identity and results will be retained in `docs/protofix/wound-window/`.

### Maintainer merit request — NOT RUN

Use the gate's own ABBA instrument on the quiet box, with its normal cell geometry, matched offered load and contemporary identical-arm controls. The exact 18 cells are in `docs/protofix/null-cells.txt`:

- Generic 14: `h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0 v1g_l0 d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`.
- 2s GET/SET p1/p32: `h53 h54 h21 h22`.

Compare PRE/POST and PRE/PAD-A, and keep POST/PAD-A visible. **Every cell must be null** under the gate's existing rule. Report rate at matched offered load, cycles/op, instructions/op and IPC, plus depth-1 latency. A PAD shift identifies a code-placement effect; instruction equality alone does not establish the required null. No throughput claim is made.

The performance-bearing `atomic_floor` whole job, its memtier floor, all ABBA/performance jobs and the full `tests/gate.sh iteration` are **NOT RUN** because the lane authorization excludes performance benchmarks. The isolated `pipeorder.py` correctness leg will be recorded separately rather than relabeling a partial `atomic_floor` as a complete job.

The full `redis_tcl`/`compat2` job is also **NOT RUN**: its frozen subset contains four `SORT speed` benchmarks. A separately labeled protocol-only Tcl diagnostic retains the exact `unit/protocol` assertions and existing manifest exclusions in both declared thread modes; it is not a complete-job pass claim.
