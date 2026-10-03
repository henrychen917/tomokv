**persistfix — PS1, PS2, PS14. Mainline validation requested.**

Worktree/branch: `/home/user/Projects/cx-persistfix`, `cx-persistfix`.
Launch HEAD: `e279aeb4cf08ae2c39f26be679388b872fed4667`.
First action after checking the clean worktree was `git fetch origin cpp && git merge --no-edit origin/cpp`; already up to date.
Implementation commits: `53e974477`, `079347f0e`; this report is committed separately.
Nothing was pushed. No server, load generator, benchmark, live test, or gate was run by this lane.
All compilation used `taskset -c 112-127 make -j16`; serverless checks and ELF/debug-info inspection used cores 112–127.

**Diagnosis confirmed from source.**

* PS1: launch `src/core/ex_loop.h:2728–2739` publishes Done/notifies inside execution; the split pass posts at `:788`. `src/persist/aof.cc:729–810` can leave the last record in `build_`. The IO gates at `src/core/io_loop.h:4554,5160` and `src/core/reorder.cc:1345` latch a global posted frontier, so the reply need not cover that record.
* Delaying only notification is insufficient: `src/net/rob.h:730` acquires Done while an IO can already be serving. Also, a previously latched gate target can be older than a newly completed operation. Posting immediately before Done still leaves that stale-target case. The serverless ack schedule deliberately keeps the IO target at zero and checks the real completion mechanism.
* The audit's blanket 1s exemption is too strong: its own flush precedes its gate, but `aof_gate_target_` can survive a waiting pass; `ExLoopT<true>::notify_sender` also explicitly handles a foreign IO owner. Neither fact guarantees that every subsequently observed Done belongs to the saved target. Therefore this patch also protects 1s AOF-always completions. **1s byte identity is not claimed; the required null is pending mainline measurement.**
* PS2: launch `src/persist/aof.cc:2123–2149` drains only posted chunks and closes inside the IO epilogue. Other physical workers can still execute/post. `DatabaseMap::join_workers` (`src/cmd/multidb.cc:263`) joins after epilogues have begun, so merely changing join order cannot repair this. Launch `aof_flush_pass` discards the distinction between a failed flush and no useful work, and the executor has no terminal owner flush.
* PS14: launch `src/core/shutdown_report.h` has no persistence object. A refused post and outstanding producer-private staging are invisible in the final schema-1 record.

**Change and ordering proof.**

The implementation stays in the AOF subsystem, with wiring at its existing completion/lifetime boundaries:

* `src/persist/aof.cc:2147` retains AOF-always write completions in owner-private batches. Ordinary writes use a release store to the new `AofWait` enum value, not an added RMW. Only blocking completion retains a deduplication claim. No Op field or persistent format changes.
* `src/core/ex_loop.h:1846` flushes producer buffers, checks the bool and remaining staging, then services completions. A full channel retains work for another pass. A batch captures one posted frontier, waits for durability without blocking the executor, then publishes Done and notifies (`aof.cc:2179`). The IO's possibly stale gate can no longer release an undurable write: it cannot see Done yet. Owners continue executing independent work while fsync is outstanding; no reader retry or seqlock was added.
* Cross-owner completion cannot assume the final owner held every journal buffer. Chunk creation publishes an owner generation (`aof.cc:402,416,2140`); a fully posted owner pass publishes its generation. Scatter, EXEC and blocking batches capture generations after fragment completion and wait for them before capturing the global frontier. They never inspect another owner's `build_`. The counter is per chunk, not per operation. The participant snapshot is conservative across producers; include multi-key workloads in subsequent performance review.
* Final MULTI and scatter publication and both blocking completion routes use the same mechanism (`ex_loop.h:2591,2741`, `scatter_engine.inc:4010`, `blocking.inc:397,581`). EXEC is explicitly covered despite its public command spec lacking Write. Cancellation cannot republish an `AofWait` slot. Slowlog's completed-command check includes the new state. Retained completions prevent the existing FLIP/LB drain acknowledgement until released; Client lifetime epochs bracket delayed publication.
* Physical-worker guards cover both split worker lambdas, fused, split read-local and R7 boot paths (`main.cc:379,506`, `genthread.cc:116`, `rl2s.cc:142`, `reorder.cc:3614`). Workers first announce the end of execution, then flush their owned producers, submit wakes and release-publish that posting has stopped. The writer keeps consuming during these barriers, avoiding full-channel deadlock, then drains/syncs/closes (`aof.cc:2262,2369`). Failed boot before writer activation bypasses the rendezvous. Role changes do not end this lifetime.
* A refused post keeps its chunk, increments an owner-private counter and logs its first refusal (`aof.cc:1454`). Full-channel backpressure is retryable, not a refused post. Final sync failure and a drain that leaves posted backlog are reported as failures.
* `shutdown_report` remains schema 1 and adds `persistence` to the immutable human/JSON snapshot (`shutdown_report.h:161,283,508`). Fields: enabled, recording, failed, drain_gave_up, posted, flushed, durable, refused, pending_chunks, records_written, producers_with_pending, producers_stopped, producers_expected, completions_pending. Posted/flushed/durable are chunk sequence frontiers; posted includes a sequence reserved before a full-channel retry. `drain_gave_up` means backlog remained after the drain and IO-completion wait. Completions_pending can legitimately count executed but unacknowledged requests at SIGTERM; it is not treated as a persistence loss.

All eight layout locks pass in **both** linked database variants: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. The GDB type-only PRE/POST audit also proves unchanged AofManager (976), Server (108608 multi / 108224 db0), and the AOF/snapshot/controller/shard-owner offsets. Channel-side state is allocated only with appendonly enabled. AOF-off allocates nothing new. AOF framing/serialization constants and record format are unchanged. No production configuration knob was added.

**Why batch publication rather than per-op sequence stamping.**

A per-op stamp must be available after the Done acquire and must cover every fragment. An eight-byte Op field breaks the layout lock; a sidecar requires per-op producer stores and IO reads plus their lifetime/reset handling. Merely sampling the global posted sequence at execution completion still misses unposted fragments.

The selected mechanism retains 16 bytes of owner-private pointers per completion and one sequence target per posted batch. It preserves pass-level chunk packing. Ignoring waits, a batch of B point writes amortizes one posted-frontier sample and one successful durability probe over B operations (2/B frontier samples per operation, 0.0625 at B=32). It adds queue bookkeeping and a second state publication; it does not claim these are free. A stamp design would instead add per-op stamp traffic and retirement probes. This is a shared-memory/cycles cost argument for choosing batching under the layout constraints, **not a measured speed claim**. Actual cycles/op = instructions/op / IPC and matched-load rate decide the cost. The batch implementation has not been proved cheaper by measurement.

**Executed proof and negative-control output.**

```sh
taskset -c 112-127 make -j16 all persistfix-units persistfix-live-controls wbland-units
taskset -c 112-127 python3 -B tests/persistfix_checks.py
taskset -c 112-127 python3 -B tests/wbland_checks.py check clauses
taskset -c 112-127 python3 -B tests/r7shadow_sync.py
taskset -c 112-127 bash -n tests/gate.sh
```

Build succeeded. Final make was up to date. Python syntax and `git diff --check` passed. The four positive persistence schedules and all three required negative outcomes passed:

```text
PASS persistfix ack-window: stale target, unposted, posted, durable
PASS persistfix remote-window: final owner waits for buffered remote fragment
PASS persistfix shutdown-window: writer waited, all producers stopped, file closed
PASS persistfix refusal: retained chunk, counter and log line
AOF refused post: producer=1 recording=0 refused=1
old-ack exit 1: FAIL persistfix: acknowledgement cannot precede post
old-close exit 1: FAIL persistfix: writer cannot close before producers stop posting
no-refusal exit 1: FAIL persistfix: refused post appears in persistence report
PASS persistfix schema: missing evidence and five dirty shutdowns rejected
PASS wbland clauses: 72/72 strict outcomes
R7 shadow production envelopes: current
```

The controls are throwaway copies of `aof.cc` emitted under `build/persistfix-controls/`, with completion deferral, shutdown ordering, or refusal counting removed. They link the actual remaining implementation. `old-ack` and `old-close` complete server binaries include both database namespaces. None of those servers was run. Receipts/logs: `build/persistfix/proofs.json`, `serverless.log`, `wbland-clauses.log`, `validation-build-3.log`, `final-build.log`.

**Exact mainline live commands — not executed here.**

The driver always creates fresh private data and owns its exact child PID. The hook requires `--enable-debug-command` and the `TOMO_AOF_ACK_WINDOW` environment variable; the driver sets both. It holds a marker SET between record and post, exposes an entered marker, and submits the old notification before waiting. A received in-window ACK tells the held executor to SIGKILL itself. Otherwise the driver releases posting and kills immediately after ACK, with no trailing INFO. It requires a fired send-gate counter and re-arms with fresh keys, bounded at 32 attempts, if the selected fused producer is itself the writer.

The TERM case records at least N=1024 acknowledged keys across four active pipelined connections, holds an additional executed marker, signals SIGTERM, witnesses writer shutdown while that producer is held, then releases it. It requires clean persistence evidence and replays every acknowledged key plus the executed marker. The marker separately tests terminal flushing even when PS1's fix prevented acknowledging it before the signal. Server logs and the acknowledged-key manifest remain in the artifact directory.

```sh
cd /home/user/Projects/cx-persistfix
for engine in epoll uring; do
  for mode in 2s 1s; do
    for check in kill term; do
      python3 tests/persistfix.py --binary build/persistfix/POST \
        --mode "$mode" --case "$check" --net-io "$engine" \
        --cores 0-7 --ratio 6:2 --port 16379 --count 1024 \
        --artifacts build/persistfix-live-positive || exit 1
    done
  done
done
```

Run these controls separately, expecting nonzero status and the named assertion, not a boot failure or timeout:

```sh
python3 tests/persistfix.py --binary build/persistfix-controls/old-ack/tomokv \
  --mode 2s --case kill --net-io uring --cores 0-7 --ratio 6:2 --port 16379 \
  --artifacts build/persistfix-live-old-ack
# Required: acknowledged/executed write lost on reload: persistfix:window:<attempt>
# The old process log must also show: AOF ack-window: SIGKILL before post

python3 tests/persistfix.py --binary build/persistfix-controls/old-close/tomokv \
  --mode 2s --case term --net-io uring --cores 0-7 --ratio 6:2 --port 16379 \
  --artifacts build/persistfix-live-old-close
# Required: persistence shutdown must drain, with refusal/backlog evidence.
```

The old-close arm retains the PS1 durability fix, so already acknowledged writes should survive; its independently discriminating assertion is the shutdown witness for the held, executed record. Live positive/negative output, boot verification, replay verification and the full gate remain **pending**.

**Gate arithmetic by collection line, not test-name intuition.**

`tests/gate.sh:1243` adds one serverless row, collected by `core_units` at line 2770. Line 2154 adds 2 modes × 2 cases, and the AOF job is collected for 2 engines at line 2850: eight live rows. Both collections precede the quick exit at line 2904. Total +9 quick and +9 full: **446 → 455 quick; 463 → 472 full**. EXPECT_QUICK/EXPECT_FULL remain 446/463, untouched. The existing delayed-SIGKILL recovery row is renamed to describe quiescent recovery; it adds no row. After the maintainer updates the two constants, run `tests/gate.sh iteration`.

**Frozen binaries and layout control.**

| Arm | SHA-256 | .text bytes |
|---|---|---:|
| build/persistfix/PRE | 23c79fa38ec9b87ff052d2cb472384aabf34873174bb4cf1c8162b308cd251d9 | 7,554,449 |
| build/persistfix/POST | 50cb24fc0b27259eab275124160b32f92ce6a80d4c2251783c1cbf75999541e3 | 7,574,929 |
| build/persistfix/PAD-A | dcf685509ded91217db0ede085ddfed5516884d0c6897ea149a4031f7165a731 | 7,574,929 |

**PAD kind A, behaviour twin**, scoped to PS1: PRE completion publication with POST's exact text and heap layouts. The shutdown fix remains active. Six helper entries (three in each namespace) return false/zero/no-op; all other ELF bytes, symbol positions and section geometry match POST. It retains candidate call envelopes, so it is not an assertion that PAD instructions/op equal PRE. It deliberately restores the unsafe acknowledgement mechanism; use only disposable mainline measurement data. No kind-B inverse control is claimed. POST grows .text by 20,480 bytes, so layout effects cannot be ignored.

```sh
taskset -c 112-127 python3 -B tools/persistfix_artifacts.py \
  build/persistfix/PRE build/persistfix/POST build/persistfix
```

This only reads binaries/debug info and emits the PAD copy and policy wrappers. `build/persistfix/artifacts.json` records patch spans, layouts, binary digests and each wrapper's digest/appended arguments. Policy wrappers verify their frozen ELF digest before exec (also binding the wrapper's own digest to that ELF), preserve the instrument's geometry and data directory, override appendonly/appendfsync after the instrument's arguments, disable auto rewrite equally, and unset the debug hook.

**Measurement request — mainline's quiet box only.**

Use GET/SET at p1/p32, both thread modes, rl=ov=ro=0: h01,h02,h17,h18,h33,h34,h49,h50. Compare PRE/POST, PRE/PAD-A and PAD-A/POST in the gate's ABBA instrument, with identical offered load and calibration within each policy (off, no, always). Keep raw per-arm cycles/op, instructions/op, IPC, achieved rate, latency, selected load and spread. AOF-off and appendfsync-no should be null; 1s also needs a null review. Always-mode PRE contains a correctness hole, so its unsafe acknowledgement rate is not evidence for rejecting durability or claiming a speedup. Include same-binary controls before interpreting differences.

The checked-in geometry ledger currently provides **only 32-core ABBA (16 io + 16 ex)**; requesting eight-core ABBA fails before measurement. The live correctness commands above use the required eight-core/16-shard/6:2 geometry. Do not invent an eight-core ABBA calibration. The following exact commands use the existing reviewed instrument geometry (split shards 128, fused shards 256); wrappers preserve it:

```sh
cells=h01,h02,h17,h18,h33,h34,h49,h50
for policy in off no always; do
  python3 tests/abbagate.py --subset full --only "$cells" \
    --candidate-binary "build/persistfix/POST-$policy" --collect-null 1 \
    --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
    --output "build/persistfix/null-$policy"
  for pair in PRE:POST PRE:PAD-A PAD-A:POST; do
    ref=${pair%%:*}; cand=${pair#*:}
    python3 tests/abbagate.py --subset full --only "$cells" \
      --reference-binary "build/persistfix/$ref-$policy" \
      --candidate-binary "build/persistfix/$cand-$policy" \
      --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
      --output "build/persistfix/abba-$policy-$ref-$cand"
  done
done
```

`--only` is a diagnostic selection; PARTIAL/exit 3 is not a full-tier pass. Retain the instrument's null/trust failures; no lane threshold waiver or gate-measurements edit is proposed. The decision is a supported null for unchanged/default behavior and 1s, with any AOF-always cost attributed using both IPC and instructions/op. No rate/cycles result exists yet. Append the actual results as MEASURE-RESULT in this worktree.

| Requested evidence | PRE | POST | PAD A | Verdict |
|---|---|---|---|---|
| AOF off, both modes, GET/SET p1/p32: rate / cycles/op / instr/op / IPC | pending | pending | pending | no claim |
| AOF no, same cells | pending | pending | pending | no claim |
| AOF always, same cells; 1s null review | pending | pending | pending | no claim |
| Live SIGKILL/SIGTERM and reload, both engines/modes | control pending | pending | not a correctness arm | no live claim |

**Diff from launch HEAD.**

```text
 MEASURE-REQUEST-persistfix.md | 183 +++++++++++++++++++++++++++
 Makefile                      |  31 +++++
 src/cmd/blocking.inc          |   7 ++
 src/cmd/scatter_engine.inc    |   7 +-
 src/core/ex_loop.h            |  29 ++++-
 src/core/genthread.cc         |   1 +
 src/core/io_loop.h            |   4 +-
 src/core/reorder.cc           |   5 +-
 src/core/rl2s.cc              |   1 +
 src/core/server.h             |   6 +-
 src/core/shutdown_report.h    |  33 ++++-
 src/exec/op.h                 |   1 +
 src/main.cc                   |   2 +
 src/persist/aof.cc            | 280 +++++++++++++++++++++++++++++++++++++++++-
 src/persist/aof.h             |  57 ++++++++-
 tests/gate.sh                 |  37 +++++-
 tests/persistfix.py           | 263 +++++++++++++++++++++++++++++++++++++++
 tests/persistfix_checks.py    |  53 ++++++++
 tests/persistfix_unit.cc      | 139 +++++++++++++++++++++
 tests/shutdown_report.py      |  26 ++++
 tools/persistfix_artifacts.py |  99 +++++++++++++++
 tools/persistfix_controls.py  |  52 ++++++++
 22 files changed, 1288 insertions(+), 28 deletions(-)
```
