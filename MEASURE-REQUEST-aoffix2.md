## aoffix2

AOF correctness lane on `cx-aoffix2`, based on `5146b78ee89b64748dd46db970efa8086f653fa0`.
The final fetch still resolves origin/cpp to that baseline, so no merge was
needed. Production source and flags are frozen at `713fca972`; later commits
contain tests and proof receipts. No push. The task-specific focused PROOF runs use only CPUs 112–127, targets
112–119, differential oracle 120, differential clients 121–127, and ports
25000–25006. No full gate or throughput benchmark is invoked. Shared-core load
is recorded beside timings; these are correctness receipts, not quiet-box
performance claims.

### Findings and implementation

| Finding | PRE observation | POST behavior and implementation | Gate case |
|---|---|---|---|
| PS4.1 | First AOF boot serves the saved key; second boot loses it. | **4/4 pass.** Preserve the snapshot: before serving clients, `main.cc` asks `aof.cc` to durably copy it into a base, create an empty increment, and publish the manifest. Both boots serve the same dataset. | `snapshot` |
| PS4.2 | A rewrite with a space in appendfilename cannot reload its manifest. | **4/4 pass.** `aof.cc` writes Redis-style quoted/escaped names and uses the existing sdssplitargs-compatible lexer. Legacy bare names, including literal quotes, remain readable. Configuration validation is unchanged. | `filename` |
| PS4.3 | A writer-owned 5 MiB SET wedges fused execution, including SIGTERM. | **4/4 pass.** On seal backpressure the elected fused writer drains persistence through its bound IO ring, reaping only AOF completions. It suppresses rewrite start during record serialization. | `large`, `large_placed` |
| PS4.4 | An RLIMIT_FSIZE write error with always leaves the process alive and write clients waiting. | **4/4 pass.** `AofManager::fail` logs the durability failure and exits 1 for always. Already-failed always completion admission also exits, including a later policy change to always. | `error` |
| PS4.5 | MSET and ordinary EXEC reuse tickets, fail on boot 3; a retained undecided group can reappear. | **12/12 pass.** Recovery takes the maximum ticket from committed groups **and undecided fragments**, all retained increments, and the base commit. Initialization restores both the allocator and visible commit cut before owners run. | `tickets`, `exec_tickets`, `resurrection` |
| PS4.7 | Off-writer everysec/always SET acknowledgements wait about 50 ms. | **8/8 pass.** AOF and snapshot producers send one wake on the existing empty-to-flagged notification edge. A full wake SQE reservation submits/reaps and retries; wake traffic stays batched. No IO park, `arm_blocked`, or TLS pump change. | `off-writer acknowledgement everysec/always` |
| PS4.8 | Two failed rewrites label the old base with the failed epoch and prevent restart. | **4/4 pass.** Pending rewrite epoch/commit live in the optional writer channel until successful manifest publication. Abort discards the pending cut. | `rewrite_fail2` |
| PS4.9 | With the manifest removed, boot serves empty and unlinks the real segments. | **4/4 pass.** Recovery refuses startup when a missing manifest leaves nonlegacy segments, preserving their exact bytes. The legacy single `.1.incr.tomo` remains supported. | `manifest_missing` |

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

**POST: all 44 rows pass.** The initial final-candidate run passed 43/44; split/
uring always measured p50 11.230 ms during compilation and failed the unchanged
10 ms bound. A fresh 24-sample run after all our compiles passed at
**3.147/7.054/7.054 ms p50/p99/max**. Both results remain recorded; no threshold,
sample count, arming condition, or failure output was removed.
[Initial final-candidate rows](docs/aoffix2/post-final-rows/commands.json),
[strict rerun](docs/aoffix2/post-recheck/commands.json).
The [44-row ledger](docs/aoffix2/verification-summary.json) binds each PRE failure
to its final POST pass; the slowest final row took **9.91 seconds**. Split 5 MiB
and fused AOF-off 5 MiB controls also pass in both engines on both arms.
[POST controls](docs/aoffix2/post-controls/commands.json).
Owned server logs and events are retained in
[the receipt archive](docs/aoffix2/owned-server-receipts.tar.gz), with
[a SHA-256 file index](docs/aoffix2/owned-server-receipts.json).

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

### Focused build and correctness proof

- PRE and POST `make -j16 all` passed. POST `make -q all` passed. Exact commands,
  exits and load are in [final-build/commands.json](docs/aoffix2/final-build/commands.json).
- **28/28 production-unit targets built and passed make -q**, including
  persistfix-units and shutdown-unit. Both `mdbqsbr-live-arms` binaries built.
  [All 30 build/freshness receipts](docs/aoffix2/units/commands.json).
- The serverless persistence schedules and their three named broken controls
  passed, as did the frame-order unit and its Python frame-walker tests.
  [Persistence checks](docs/aoffix2/static/persistfix-checks.log),
  [writer framing unit](docs/aoffix2/static/persistfix-frameorder.log),
  [frame walker](docs/aoffix2/static/frame-order.log).
- Differential against Redis **7.4.10**: **64/64 comparison legs passed**, zero
  differences: psfix, multi, xshard, servertail × seeds 7,19,20,23 × atomic 0/1 ×
  split 6:2 and armed fused. Both additional fused read-local witnesses passed.
  [Commands](docs/aoffix2/differ/commands.json),
  [split](docs/aoffix2/differ/split.log), [fused](docs/aoffix2/differ/armed-fused.log).
- Existing AOF batteries passed across **1s/2s × uring/epoll**: aof.py (including
  live LOADAOF and exact snapshot stream comparison), rewrite, rewrite triggers,
  frame ordering, torn groups, all three fsync policies, and persistfix kill/term.
  Atomics 0/1 are covered where supported; aof_torn_group explicitly requires 1.
  There are **140 successful phase points**, combining 136 from the corrected
  matrix with four fresh uring frame runs. All restart checks passed.
  [Matrix](docs/aoffix2/batteries-final/commands.json),
  [uring frame witnesses](docs/aoffix2/uring-frame/commands.json).

The first AOF battery runner put its state file outside the database directory;
`aof.py` deliberately locates increments beside that state. It also tried the
historically epoll-only framing entry point on uring. Both rejected the setup;
[those failures remain](docs/aoffix2/batteries/commands.json). The corrected runner
uses the actual directory and ordinary gate balancing defaults except the frame
fixture's explicitly stable placement.

For uring, a 273-frame record can finish submission before the first 256-frame
write batch completes, so there is no **ready** GCMT to defer during the open
large record. The initial adapted runs correctly failed their mandatory witness.
The opt-in uring fixture now spans **four full writer batches (64 MiB)**. Every
mode/atomic case observed **3 deferrals, 1 control frame, 0 interleaves**, in
about 1.5 seconds. The existing epoll gate keeps its 17 MiB fixture. No deferral
assertion, timeout, or physical frame check was relaxed. The full matrix runner
uses this same corrected fixture on future runs.

The snapshot and ratio-1:1 accessory timing shapes did not show a 50 ms PRE
stall in this loaded run; their recorded values are retained below. PS4.7 itself
reproduced on every strict 6:2/fused acknowledgement row. No paper-quality
snapshot speedup or exact microsecond overhead is claimed from unequal shared
loads. Runtime LOADAOF completed in all eight corrected matrix cells; its
reported separate audit spin was not changed here.

### PRE/POST acknowledgement latency

Milliseconds, **p50 / p99 / max**. Sequential rows use one connection proven off
the writer. Twelve-connection and default rows report the maximum of each
statistic across all 12 connections, not a pooled percentile. Each connection
has 20 measured SETs after four warmups; sequential rows have 200. Payload is
100 bytes. Both arms use eight target cores; split uses 6:2 and 16 shards.
Defaults preserve the shipped placement, shard count and balancers. The
[per-connection CSV](docs/aoffix2/latency-connections.csv) retains every statistic.

Host one-minute load ranges are included in each row. Raw logs also retain
per-target-CPU activity and concurrent process samples. These runs share the
reserved cores with sibling lanes; use them to assess the 50 ms wait, not
as a paper-quality microsecond performance comparison.

| Shape | Policy | PRE p50/p99/max ms | POST p50/p99/max ms | PRE load | POST load |
|---|---|---:|---:|---:|---:|
| 1s-seq | off | 0.459/5.746/7.011 | 0.341/2.960/3.957 | 73.2–73.2 | 41.2–41.2 |
| 1s-seq | no | 0.742/7.010/8.615 | 0.465/4.951/5.885 | 73.2–73.2 | 41.2–41.2 |
| 1s-seq | everysec | 50.073/56.706/57.931 | 1.070/5.535/5.917 | 73.2–75.0 | 41.3–41.3 |
| 1s-seq | always | 52.804/63.252/78.664 | 2.781/6.629/6.900 | 77.1–80.0 | 41.3–41.3 |
| 2s-seq | off | 1.976/13.013/13.993 | 0.129/6.049/8.013 | 84.1–84.1 | 40.6–40.6 |
| 2s-seq | no | 0.356/13.084/13.963 | 0.478/6.988/8.028 | 84.1–84.7 | 40.6–40.6 |
| 2s-seq | everysec | 50.160/56.419/57.707 | 2.023/6.097/7.796 | 84.3–84.7 | 39.9–40.6 |
| 2s-seq | always | 51.076/63.800/64.567 | 3.964/8.899/10.590 | 83.0–84.3 | 39.9–39.9 |
| 1s-conns | off | 3.451/10.487/10.487 | 2.857/5.010/5.010 | 80.0–80.0 | 41.3–41.3 |
| 1s-conns | no | 3.011/11.623/11.623 | 2.501/6.249/6.249 | 81.2–81.2 | 41.3–41.3 |
| 1s-conns | everysec | 50.172/59.320/59.320 | 2.998/4.997/4.997 | 81.2–82.8 | 40.6–40.6 |
| 1s-conns | always | 55.041/65.818/65.818 | 3.996/6.017/6.017 | 82.8–84.1 | 40.6–40.6 |
| 2s-conns | off | 4.000/12.000/12.000 | 2.632/8.410/8.410 | 82.2–83.0 | 39.9–39.9 |
| 2s-conns | no | 3.324/12.255/12.255 | 3.021/8.046/8.046 | 82.2–82.2 | 39.9–39.9 |
| 2s-conns | everysec | 50.369/56.068/56.068 | 2.473/8.074/8.074 | 78.3–82.2 | 39.3–39.9 |
| 2s-conns | always | 55.320/66.701/66.701 | 6.306/11.064/11.064 | 77.2–78.3 | 39.3–39.3 |
| defaults | off | 3.958/11.833/11.833 | 2.495/7.006/7.006 | 76.4–77.2 | 39.3–39.3 |
| defaults | no | 4.113/12.903/12.903 | 2.973/10.003/10.003 | 76.4–76.4 | 39.1–39.3 |
| defaults | everysec | 50.227/61.144/61.144 | 2.739/7.995/7.995 | 75.4–76.4 | 39.1–39.1 |
| defaults | always | 53.773/60.684/60.684 | 5.537/11.998/11.998 | 73.3–75.4 | 39.1–39.1 |
| 2s-conns-everysec-ratio1to1 | everysec | 2.620/18.908/18.908 | 0.944/6.002/6.002 | 105.1–105.1 | 39.1–39.1 |

### Snapshot wake and reply head of line

BGSAVE seconds for 400,000 keys with 200-byte values, observed by snapshot-file
publication. Unpoked does not poll the server; poked sends PINGs every 1 ms.

| Mode | PRE unpoked/poked s | POST unpoked/poked s | PRE load | POST load |
|---|---:|---:|---:|---:|
| 1s | 0.683/0.652 | 0.407/0.449 | 73.3–73.3 | 39.4–39.4 |
| 2s | 0.717/0.615 | 0.309/0.312 | 66.9–68.4 | 34.2–34.2 |

For two connections proven on the same nonwriter IO thread, the median PING
latency alone / behind SET (five pairs) was:

- PRE: **0.192/41.458 ms**, host load 105.9–105.9.
- POST: **0.161/0.085 ms**, host load 39.4–39.4.

### TLS report-only check

TLS 1.3 GET pipelines, depth 32, eight batches per cell, three fresh boots.
The table shows the median of the three per-boot p50s in milliseconds.
Idle/poked cells use no extra traffic / PING every 1 ms. The complete
[TLS CSV](docs/aoffix2/tls-connections.csv) retains p50/p99/max for every repeat.

| Mode | Value | PRE idle/poked p50 ms | POST idle/poked p50 ms | PRE load | POST load |
|---|---:|---:|---:|---:|---:|
| 1s | 1 KiB | 0.206/0.500 | 0.172/0.117 | 71.2–73.3 | 36.2–38.5 |
| 1s | 4 KiB | 154.181/3.049 | 152.957/3.250 | 71.2–73.1 | 36.2–38.5 |
| 1s | 16 KiB | 618.083/15.791 | 614.559/11.759 | 68.4–73.1 | 35.2–38.5 |
| 2s | 1 KiB | 0.303/0.192 | 0.284/0.698 | 103.7–106.6 | 31.5–34.2 |
| 2s | 4 KiB | 158.195/6.777 | 152.576/4.151 | 103.3–105.4 | 31.5–34.2 |
| 2s | 16 KiB | 624.070/26.303 | 610.582/12.747 | 103.0–105.1 | 31.1–34.2 |


**TLS verdict:** the approximately 3/12 park-timeout steps remain on POST at
4/16 KiB. Poking shortens them on both arms. No IO-loop/TLS path was edited;
its selected bodies are byte-identical. PFPERSIS.1 remains outside this lane.


### Final binary identity

| Check | Result |
|---|---|
| Selected hot bodies, `tomo` | **601/601 identical** |
| Selected hot bodies, `tomo_db0` | **603/603 identical** |
| Full audit hot selection, including executor run bodies | **1,208/1,208 identical** |
| Command handlers | **1,210/1,210 identical** |
| Full emitted-body union | 16,175 equal; 162 changed; 16,337 total |
| `.text` | PRE 7,582,188 B; POST/PAD-A 7,596,604 B; POST growth **14,416 B** |
| PAD-A versus PRE selected hot bodies | **1,204/1,204 identical** |
| Eight locked layouts, both namespaces | All sizes **and field offsets** identical |
| Manager/server layouts, both namespaces | All sizes **and field offsets** identical |

**Changed hot bodies: none.** All 162 changed emitted bodies are in the two
namespaces' AOF, snapshot, main, and xshard objects: cold recovery/rewrite/wake
work and generated helpers affected by those additions or the recovery-plan
layout. See the complete [changed-body list](docs/aoffix2/identity-final/full/changed-bodies.json).
The linked image is intentionally different: cold code and section/function
placement move. `linked_bytes.py` returns 1 for that section difference; this
is not a claim of identical runtime images or a measured performance null.

Layout sizes: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944,
Rob<64> 192, AtomicEntry 144, Config 624. AofManager remains 976 in both
namespaces; Server remains 108736/108352 and SnapshotManager 792/528 for
`tomo`/`tomo_db0`. AofReplayPlan grows 176→184 bytes. ChunkChan remains 896 bytes; its new
writer-only metadata fits existing padding. PAD-A has the exact POST field
layout for both types in both namespaces. AOF off allocates neither channel
storage nor a replay plan.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/aoffix2/pre/tomokv` | `a39cfaf4a3e1d827bb3f24305460f0c1ba72154c59e64d7c20d37001ce0dd17c` |
| POST | `build/tomokv` | `96d96dca188610aa569c8e05f0dd5e22cfee6f602cf6e733fb8db2bc196c044e` |
| PAD-A | `build/aoffix2/pad/tomokv` | `6d486382887e3d284d161023787b46ecdf4af10dc792031640a1d8e2f0e29cdb` |

Receipts: [hot](docs/aoffix2/identity-final/hot.log),
[full summary](docs/aoffix2/identity-final/full/summary.json),
[full body inventory](docs/aoffix2/identity-final/full/bodies.json.gz),
[linked sections](docs/aoffix2/identity-final/linked.json),
[layouts](docs/aoffix2/identity-final/layouts.json),
[arm binding](docs/aoffix2/proof.json),
[PAD kind and layout proof](docs/aoffix2/pad/kind.json).

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
[Literal checker failure](docs/aoffix2/static/ledger.log),
[projected count and exact label agreement](docs/aoffix2/static/ledger-projection.json).

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
`docs/aoffix2/static/null-*-cells.json`. The split rate cells h17/h18 still require the instrument's normal load pinning.
No load calibration was run by this lane.

Collect a fresh PRE/PRE null, then PRE/POST, PRE/PAD-A, and PAD-A/POST ABBA blocks
at identical offered loads. Report rate, cycles/op, instructions/op and IPC for
every arm/cell. Acceptance requires **every POST cell to stay inside the fresh
matched same-binary envelope**, including each latency-scored cell. An identical-
arm spread above **2%** invalidates the comparison; do not widen a threshold or
average away a losing cell. No speedup is claimed by this correctness lane.
PAD-A matches the changed data layouts and total text size; it does **not** match
every function address, so a POST/PAD difference alone cannot prove a behavioral
speedup rather than a function-placement effect. Re-run the acknowledgement shapes on that quiet allocation if exact
microsecond costs are needed for the paper.
