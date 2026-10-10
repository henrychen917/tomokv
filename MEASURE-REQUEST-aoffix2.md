## aoffix2

AOF correctness lane on `cx-aoffix2`, based on `5146b78ee89b64748dd46db970efa8086f653fa0`.
No push. The task-specific focused PROOF runs use only CPUs 112–127, targets
112–119, differential oracle 120, differential clients 121–127, and ports
25000–25006. No full gate or throughput benchmark is invoked. Shared-core load
is recorded beside timings; these are correctness receipts, not quiet-box
performance claims.

### Findings and implementation

| Finding | PRE observation | POST behavior and implementation | Gate case |
|---|---|---|---|
| PS4.1 | First AOF boot serves the saved key; second boot loses it. | Preserve the snapshot: before serving clients, `main.cc` asks `aof.cc` to durably copy it into a base, create an empty increment, and publish the manifest. Both boots serve the same dataset. | `snapshot` |
| PS4.2 | A rewrite with a space in appendfilename cannot reload its manifest. | `aof.cc` writes Redis-style quoted/escaped names and uses the existing sdssplitargs-compatible lexer. Legacy bare names, including literal quotes, remain readable. Configuration validation is unchanged. | `filename` |
| PS4.3 | A writer-owned 5 MiB SET wedges fused execution, including SIGTERM. | On seal backpressure the elected fused writer drains persistence through its bound IO ring, reaping only AOF completions. It suppresses rewrite start during record serialization. | `large`, `large_placed` |
| PS4.4 | An RLIMIT_FSIZE write error with always leaves the process alive and write clients waiting. | `AofManager::fail` logs the durability failure and exits 1 for always. Already-failed always completion admission also exits, including a later policy change to always. | `error` |
| PS4.5 | MSET and ordinary EXEC reuse tickets, fail on boot 3; a retained undecided group can reappear. | Recovery takes the maximum ticket from committed groups **and undecided fragments**, all retained increments, and the base commit. Initialization restores both the allocator and visible commit cut before owners run. | `tickets`, `exec_tickets`, `resurrection` |
| PS4.7 | Off-writer everysec/always SET acknowledgements wait about 50 ms. | AOF and snapshot producers send one wake on the existing empty-to-flagged notification edge. A full wake SQE reservation submits/reaps and retries; wake traffic stays batched. No IO park, `arm_blocked`, or TLS pump change. | `off-writer acknowledgement everysec/always` |
| PS4.8 | Two failed rewrites label the old base with the failed epoch and prevent restart. | Pending rewrite epoch/commit live in the optional writer channel until successful manifest publication. Abort discards the pending cut. | `rewrite_fail2` |
| PS4.9 | With the manifest removed, boot serves empty and unlinks the real segments. | Recovery refuses startup when a missing manifest leaves nonlegacy segments, preserving their exact bytes. The legacy single `.1.incr.tomo` remains supported. | `manifest_missing` |

The Redis 7.4.10 oracle boots empty for PS4.1 and PS4.9. This lane deliberately
uses the task's allowed alternatives: preserve the imported snapshot, and refuse
ambiguous recovery. A crash before snapshot-import manifest publication also
fails closed with the snapshot and partial import files preserved; it needs
operator repair instead of silently choosing an empty dataset. The AOF frame and
manifest versions remain 1. Quoted manifest tokens extend the existing grammar.

D8 (`appendfsync no` error response) is unchanged; the new fatal behavior is
limited to always, including switching to always after an earlier error. No
intentional behavior change for PS4.6, PS4.12–.14, PS4.17, or DEBUG LOADAOF.
PFPERSIS.1 is report-only and its TLS path remains unchanged. The existing IO
reply gate still waits for its persistence frontier; the missing producer wake
was fixed without relaxing that durability boundary.

### Regression evidence

All eight findings reproduced on the requested PRE, so no audited-binary fallback
was needed. The 44 new row invocations all failed on PRE; split large-write
controls passed in both engines and are not counted as failing-control rows.
[PRE commands and exits](docs/aoffix2/pre/rows.json). Every row owns fresh data,
its process and port; gate rows run after the prebooted job_aof server stops.

The filename row covers spaces, quotes/backslashes, single quotes and tab/newline,
plus legacy bare quote entries. The latency row proves the connection is off the
writer with DEBUG IO-THREAD/LBSIGNALS, then requires p50 <10 ms for 24 sequential
SETs. Timing observation mode is never used by a gate row. The torn-group row
checks four boots and requires the never-committed keys to remain absent.

The initial final-candidate run passed **43/44** rows. The remaining split/uring
always latency row measured p50 **11.230 ms** during compilation, above the
unchanged **10 ms** bound; its failed output is retained. The source had already
removed the 50 ms steps in that run (p99/max 17.555 ms). A fresh strict rerun after
our builds is required before the proof is complete. This statement is a recorded
intermediate result, superseded only by the final receipts below.

Per-finding production files:

| Finding | Files |
|---|---|
| PS4.1 | `src/main.cc`, `src/persist/aof.cc`, `src/persist/aof.h` |
| PS4.2 | `src/persist/aof.cc` |
| PS4.3 | `src/persist/aof.cc`, `src/persist/aof.h` |
| PS4.4 | `src/persist/aof.cc` |
| PS4.5 | `src/persist/aof.cc`, `src/persist/aof.h`, `src/core/server.h` |
| PS4.7 | `src/core/signal.h`, `src/persist/aof.cc`, `src/snapshot/snapshot.cc` |
| PS4.8 | `src/persist/aof.cc`, `src/persist/aof.h` |
| PS4.9 | `src/persist/aof.cc` |

`Makefile` pins only the two AOF translation units' compiler inlining budgets
(34400 / 34800 for `tomo` / `tomo_db0`). Without those budgets, cold-code growth
changed three emitted storage helpers. With them, the final 1,204-body hot audit
is **1,204/1,204 raw-byte and relocation-target identical**. No runtime selector
or per-command branch was added for this compiler control.

Final POST proof results, binary hashes and the full identity receipts follow below.

### Gate accounting

DQ **+44**, DF **+44**: eight ordinary cases × two modes × two engines =32;
two acknowledgement policies × two modes × two engines =8; two fused large-value
cases × two engines =4. Row declarations are at `tests/gate.sh:2662`, `:2675`,
and `:2690`; both job_aof collections are before the quick-tier exit. Required
counts: **511+44=555 quick; 528+44=572 full**. The arithmetic comment is above
the constants; their values remain **511/528**, as instructed.

The independent label fixture includes all 572 rows. Its source inventory has
no missing or extra labels. The literal fixture command still rejects the
maintainer-owned EXPECT_FULL=528 until the owner updates it to 572. No checker
or count assertion was weakened; a projected in-memory count check verifies the
572-label agreement separately.

### Mainline measurement request

After merging and updating the two EXPECT constants, run the normal correctness
gate and the default-build AOF-off performance null on a quiet box. Use PRE
`build/aoffix2/pre/tomokv`, POST `build/tomokv`, and PAD-A
`build/aoffix2/pad/tomokv` in ABBA order with the gate's own instrument.

PAD means **(A) behaviour twin**: PRE behavior with POST's optional AOF channel
and recovery-plan layouts and total linked `.text` size. It does not promise
identical addresses for every function. The production manager, server and
all eight locked layouts remain unchanged. Build recipe:
`taskset -c 112-127 python3 tools/aoffix2_pad.py`.

Required null cells are the existing 14 fused cells in
`docs/lbplanner/generic-cells.txt` (`h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,
d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`) and the four split cells
`h17,h18,h49,h50` in `tests/headline_cells.txt`. The latter cover GET/SET at
depths 1/32. Preserve each registered cell's load geometry, scoring and flags;
keep AOF off and save disabled. Offline inventory receipts are under
`docs/aoffix2/static/null-*-cells.json`. No load calibration was run by this lane.

Collect a fresh PRE/PRE null, then PRE/POST, PRE/PAD-A, and PAD-A/POST ABBA blocks
at identical offered loads. Report rate, cycles/op, instructions/op and IPC for
every arm/cell. Acceptance requires **every POST cell to stay inside the fresh
matched same-binary envelope**, including each latency-scored cell. An identical-
arm spread above **2%** invalidates the comparison; do not widen a threshold or
average away a losing cell. No speedup is claimed by this correctness lane.
POST-versus-PAD isolates behavioral changes subject to the stated address-layout
limitation. Re-run the acknowledgement shapes on that quiet allocation if exact
microsecond costs are needed for the paper.
