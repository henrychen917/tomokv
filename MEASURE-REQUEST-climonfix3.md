Climonfix3 repairs the 1s proof arguments, makes ordinary gate launches persistence-silent,
and bounds shutdown snapshot coordination without authorizing a stop after a failed save.
The final serverless gate suite passes **63/63**. The extractor declares **498 full rows
= fetched mainline 490 + 8**, and **481 quick rows = 473 + 8**. The receipt chain is
**not green**: its protected fixture/count guard refuses those eight unsynchronized
rows. No EXPECT constant, fixture content, guard, or deadline was changed to hide that refusal.

Worktree/branch: `/home/user/Projects/cx-climonfix`, `cx-climonfix`.
Launch HEAD: `818f14eec49431bc611a4c2dcc0b7c2dfb42b35b`.
First merged `origin/cpp` at `cd02ecbab1502775f1c170e806971d1f7bbc3ee9`;
merge commit `b4bd6752302041006ce7b644ee61f374370769e7`.
Repair commits: `7ea4f8474`, `27a1ea955`.
The additive ring-unit conflict retains both climon and RL1. The protected EXPECT and
fixture conflicts take origin/cpp verbatim; `build/climonfix3-inventory.json` verifies
that both EXPECT lines and the complete fixture remain identical to that base.

**Diagnosis and change.**

- `tests/shutdown_persist.py:17` now constructs `--ratio 6:2` only for 2s. 1s omits
  that option. `ShutdownBootWiring` at `tests/gates_test.py:1788` checks the actual
  argv builder and preserves the default-save and explicit-empty-save cases.
- `tests/gate.sh:690` supplies `--save ''` before row arguments in the common
  `launch`, covering both `boot` and `boot_fused`. TLS, zero-copy, rejected-boot
  probes, and the two AOF rewrite scripts get the same default. Later explicit
  `--save` arguments retain precedence. The shell test executes the real launcher
  argument construction with process/port operations stubbed, including the override.
- The multidb drivers already used `--save ''` (`tests/mdbqsbr_live.py:104`). Their
  long-park controls could nevertheless wait indefinitely for the new signal request:
  `on_signal` returned without the sticky shutdown wake, waiting for an IO cron which
  the parked worker could not run. `Server::request_signal_shutdown`,
  `src/core/server.h:2048`, now returns to the immediate stop/wake path when saving
  is disabled. A configured save still leaves all owners alive until finalization.
- The old `save_cron_pass` returned before handling a pending signal whenever a
  snapshot was active. The request had no deadline. It now visits signal shutdown
  first (`server.h:2108`); Busy returns to the IO loop, which can advance its own
  BGSAVE. `Server::shutdown_from_cron` (`src/cmd/server_tail.cc:286`) bounds those
  retries instead of retrying forever. Completion of the older BGSAVE does not count
  as the requested final save: the signal then starts a fresh epoch.
- `SnapshotManager::start` previously had unbounded waits for a ring, Preparing,
  atomic apply drain, Freeze, Mark, Capture, and failure cancellation. For shutdown
  only, admission uses try-lock and those waits check a ten-second coordination
  deadline (`src/snapshot/snapshot.cc:191,237,303,325,330,342,360,373,400,416,428`).
  Expiry marks the epoch Failed and returns to the saving IO owner, allowing its
  ordinary loop to drain completions and cancellation acknowledgements. The epoch
  remains unavailable to a new snapshot until cleanup is complete. Partial broadcast
  accounting distinguishes unposted owners from an epoll message already queued before
  a failed eventfd wake (`snapshot.cc:310`). Cancelled IO completions are reaped without
  starting another write/fsync/rename (`snapshot.cc:720`). Existing `abort_file` releases
  the atomic barrier once cancellation has drained.

The preserved failure ledger confirms the 1s argument refusal, snapshot-cut replacement,
and shutdown timeouts. It contains no stack for the 30-second tailgen shutdown timeout;
this report does not claim to identify that particular blocked phase. The code-level
unbounded waits and no-save signal wake regression above are independently witnessed.
The FLIP-under-load EOF also remains a live rerun obligation; no profile or stack in the
provided evidence establishes its cause.

Configured SHUTDOWN/SIGTERM/SIGINT save, SAVE overrides an empty schedule, and NOSAVE
skips saving. A busy command returns the existing shutdown-error response promptly;
signals yield/retry through cron. A coordination timeout or save error refuses the stop
and leaves the process alive. The ten-second bound is on coordination polling, **not a
claim that kernel filesystem calls or arbitrary owner work can be asynchronously cancelled**.
No Redis knob or command grammar was added. The signal deadline uses appended cold
Server storage, with release/acquire publication through the existing request byte;
established member offsets stay intact. No per-operation hook was added.

The snapshot header, version, frames, serializers and loaders are unchanged. The unit
loads the actual files it writes. All eight layout locks compile: Op 336, Client 1984,
ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624.
No lane change touches `io_loop.h`, `wb.h`, or `reorder.cc`, so the conditional wbland
clause requirement does not apply. No server, benchmark, live battery or gate was run;
all builds used `taskset -c 112-127 make -j16`, and all executed checks stayed within
112–127. Nothing was pushed.

**Directed serverless proof.**

`tests/shutdown_unit.cc:93` calls real snapshot admission with an already-running epoch,
checks a pending signal yields, and advances a wrapped monotonic clock to prove the Busy
retry expires. At `:125`, the fixture drives the real snapshot manager and executor
snapshot state machines serially using their production progress hooks and epoll
mailboxes. It starts no worker loop or listener. Split uses 16 shards and 6 IO + 2 EX;
fused uses the permitted 16 CPUs. Each case creates a fresh private directory in build/.

Both modes exercise normal finalization, stalls at Preparing/Freeze/Mark/Capture,
cancellation, and a successful retry. The Capture stall must occur after a real frame
write (`:198`). The in-flight BGSAVE control asserts Capture actually opened, delivers
the signal on that saving owner, completes the old epoch without stopping, and requires
the final on-disk epoch to be 2. The original policy, failure, held-owner and stop-before-
release witnesses remain in the same unit and the same gate row.

```text
shutdown saving owner 2s phase=0 completion: PASS
shutdown saving owner 1s phase=0 completion: PASS
shutdown saving owner 2s phase=1 timeout/retry: PASS
shutdown saving owner 1s phase=1 timeout/retry: PASS
shutdown saving owner 2s phase=2 timeout/retry: PASS
shutdown saving owner 1s phase=2 timeout/retry: PASS
shutdown saving owner 2s phase=3 timeout/retry: PASS
shutdown saving owner 1s phase=3 timeout/retry: PASS
shutdown saving owner 2s phase=4 timeout/retry: PASS
shutdown saving owner 1s phase=4 timeout/retry: PASS
shutdown saving owner 2s phase=0 BGSAVE/signal: PASS
shutdown saving owner 1s phase=0 BGSAVE/signal: PASS
shutdown policy, signal handoff, failure and owner hold: PASS
```

The preceding stderr lines in `build/climonfix3-shutdown-unit.log` are the expected
injected save failure and expired-Busy refusal. All seven throwaway shutdown controls
exit 1 at the named assertion; `tests/climonfix_artifacts.py controls --build-root build`
checks the exit and message, and itself exits 0. Evidence is in
`build/climonfix3-controls-final.log`, `build/climonfix-controls.json`, and the individual
`build/climonfix-control-*/run.log` files. No corrupted server binary was executed.

| Reverted mechanism | Observed assertion |
| --- | --- |
| Configured-save policy | `default SHUTDOWN saves before stop` |
| Signal handoff | `signal leaves owners alive for final save` |
| Post-cut owner hold | `held owner prevents admission of another snapshot` |
| Stop at successful finalization | `successful finalization publishes stop before releasing epoch` |
| No-save immediate signal stop | `no-save signal stops without waiting for IO cron` |
| Busy retry deadline | `busy shutdown retry is bounded and preserves the running snapshot` |
| Snapshot coordination deadline | `shutdown snapshot yields on stalled saving owner` |

SV1 is unchanged in this repair. Its unit still passes tracking and MONITOR over all
64 logical owner pairs, in both disarm directions. Its old one-word control exits 1:
`FAIL climon mask: disarm retains the other owner at distance 64`.
The two argv/default negative controls also fail at their named assertions:
`shutdown proof must omit --ratio in 1s` and
`generic boot disables save before row overrides`. Their logs are
`build/climonfix3-negative-ratio.log` and `build/climonfix3-negative-default-save.log`.

Reproduce the positive unit and source checks:

```bash
taskset -c 112-127 make -j16 all build/shutdown-unit build/climon-mask-unit build/climon-mask-old-unit
taskset -c 112-127 ./build/shutdown-unit
taskset -c 112-127 ./build/climon-mask-unit
taskset -c 112-127 python3 tests/climonfix_artifacts.py controls --build-root build
taskset -c 112-127 python3 tests/gates_test.py ShutdownBootWiring
taskset -c 112-115 python3 tests/gates_test.py
taskset -c 112-127 bash -n tests/gate.sh tests/aof_rewrite_matrix.sh tests/aof_rewrite_trigger_matrix.sh
```

The complete `gates_test.py` invocation has no positional `serverless` selector.
Its final result is `Ran 63 tests in 288.880s / OK`, including TSANWiring and all
scheduler controls (`build/climonfix3-gates-serial.log`). Two earlier runs during
build contention failed nine scheduler cases at the unchanged 45-second fixture
deadline; their logs are retained as `climonfix3-gates.log` and
`climonfix3-gates-retry.log`. The final run restricts itself to 112–115, which makes
the existing affinity-derived scheduler fixture pool run one scenario at a time.
No assertion, scenario, synchronization window or timeout was removed or widened.

Every command in the receipt/self-test chain was run; the independent checks were
allowed to finish after the protected fixture refusal:

| Command (prefix `taskset -c 112-127 python3`) | Result |
| --- | --- |
| `tests/abbagate.py --self-test` | PASS, 100 + 10 + 9 + 16 tests |
| `tests/gate_quiet.py --self-test` | PASS, 8 |
| `tests/gate_measurements.py --self-test` | PASS, 11 |
| `tests/gate_receipt.py --self-test` | REFUSED by fixture guard before receipt controls |
| `tests/abba_instrument.py --self-test` | PASS, 7 |
| `tests/background_environment_test.py` | PASS, 11 |
| `tests/gate_history.py self-test` | PASS, 55 |
| `tests/gate_process_test.py` | PASS, 12 |
| `tests/tailgen_stall.py --self-test` | PASS, 3 |

Commands, return codes and individual logs are in `build/climonfix3-checks/`;
`build/climonfix3-receipt-chain.log` records the sequence. This is not a green receipt
claim. The exact refusal is:

```text
RECEIPT FIXTURE REFUSED: tests/fixtures/nullrefresh-ledger-labels.json: EXPECT_FULL=490, fixture=490, source declarations=498
Missing fixture labels: 'climon 128-owner delivery mask' (x1); 'shutdown persistence (1s, command)' (x1); 'shutdown persistence (1s, sigint)' (x1); 'shutdown persistence (1s, sigterm)' (x1); 'shutdown persistence (2s, command)' (x1); 'shutdown persistence (2s, sigint)' (x1); 'shutdown persistence (2s, sigterm)' (x1); 'shutdown policy + signal handoff serverless' (x1)
Extra fixture labels: none
```

The requested green receipt and the prohibition on updating either protected input
cannot both be satisfied on this merged tree. The guard remains intact. Mainline must
synchronize the eight reviewed labels and **EXPECT_QUICK 473 -> 481 / EXPECT_FULL
490 -> 498**, then rerun the receipt chain before accepting the landing.

**Row inventory and persistence posture.**

```bash
taskset -c 112-127 python3 -c "import sys; sys.path.insert(0,'tests'); import gate_ledger_fixture as g; print(len(g.source_labels(open('tests/gate.sh').read())))"
# 498
```

No new row is added by climonfix3. The existing +8 remain reachable: mask declaration
at `gate.sh:1245`, policy at `:1269`, and 2 modes x 3 stop cases at `:1277`.
`collect_job climonfix` is at `:2929`, before the quick exit at `:3072`; the ring-unit
collector is also before that exit. No row was placed inside core_units or waits.
Counter comparisons in `build/climonfix3-inventory.json` show all 490 mainline labels
retained and precisely the eight labels above added once in each tier.

After the launch-default change, these are the only intentional armed snapshot-schedule
boots in the gate's successful batteries:

- The six `shutdown persistence (1s|2s, command|sigterm|sigint)` rows. Command subcases
  `default`, `nosave`, `config-off`, and `save-failure` boot the default schedule;
  `config-off` then disables it. The default signal subcases boot armed. All restart
  boots and `*-off` signal controls boot with save disabled. `save-override`, `save-off`,
  and `config-on` also boot disabled, with `config-on` arming it through CONFIG SET.
- The four `servertail battery` rows (split/fused+armed x atomic 0/1) have private
  `scope_shutdown` and `scope_rewrite` child boots in `tests/servertail.py`. Those
  deliberately test shutdown and the default three save clauses through CONFIG REWRITE,
  and retain their armed schedule. Their parent feature-battery server boots disabled.

Snapshot SAVE/BGSAVE/cut/reload batteries still execute their explicit persistence
commands, but boot with the schedule disabled so SIGTERM cleanup cannot replace their
cut. AOF tests, including both rewrite matrices, boot with save disabled. Notify's
save-scheduler checks still arm/disarm at runtime and restore their boot value.
The common launcher, TLS, zero-copy, multidb, differential, feature/performance helpers
and xshard-dispatch launches are otherwise disabled. Explicit row save options remain
available and are tested for precedence.

**Mainline live commands, not executed here.**

After the protected fixture/count synchronization, run the full intended landing gate:

```bash
tests/gate.sh iteration --candidate-binary "$PWD/build/tomokv" \
  --reference-binary "$PWD/build/climonfix3-pre/tomokv"
```

This reruns the reported snapshot-cut, multidb long-park, FLIP-under-load, tailgen
shutdown and program-state failures as well as the six repaired shutdown rows.
For standalone recovery in both modes and network engines, with the gate's 16 shards
and 6:2 split geometry (the harness now correctly omits ratio in 1s):

```bash
SV2_RUN=$(mktemp -d "$PWD/build/climonfix3-live.XXXXXX")
for MODE in 1s 2s; do
  for NET in uring epoll; do
    taskset -c 112-127 python3 tests/shutdown_persist.py \
      --binary build/tomokv --cores 0-7 --ratio 6:2 --port 17991 \
      --mode "$MODE" --net-io "$NET" --case all \
      --output "$SV2_RUN/$MODE-$NET" || exit 1
  done
done
```

For the live SV1 witness with owners i and i+64 and default client balancing:

```bash
test -z "$(ss -H -ltn 'sport = :17992')" || exit 1
WIDE_RUN=$(mktemp -d "$PWD/build/climonfix3-wide.XXXXXX")
taskset -c 0-111 build/tomokv --bind 127.0.0.1 --port 17992 --thread-mode 1s \
  --shards 16 --save '' --dir "$WIDE_RUN" --enable-debug-command yes >"$WIDE_RUN/server.log" 2>&1 &
WIDE_PID=$!
trap 'kill -TERM "$WIDE_PID" 2>/dev/null; wait "$WIDE_PID" 2>/dev/null' EXIT
for TRY in $(seq 100); do
  kill -0 "$WIDE_PID" || exit 1
  redis-cli -h 127.0.0.1 -p 17992 PING 2>/dev/null | grep -qx PONG && break
  sleep .1
done
taskset -c 112-127 python3 tests/climon_128.py 127.0.0.1 17992
WIDE_RC=$?
kill -TERM "$WIDE_PID"; wait "$WIDE_PID"; trap - EXIT
test "$WIDE_RC" -eq 0
```

**Offline hot-path receipt and measurement arms.**

The final `climon_armed_gate` remains 211 bytes and identical after relocation
normalization in both database variants (`build/climonfix3-armed-fetched-base.json`, compared to fetched mainline). Its disabled
entry still uses the single armed-word load. No whole-path throughput null follows
from that small byte receipt; mainline must judge the 14 generic cells.

| Arm | Binary | SHA-256 | .text bytes |
| --- | --- | --- | ---: |
| PRE | `build/climonfix3-pre/tomokv` | `7a3c698fb07c237b0a526cee5171b48ca3b7f5bfe1f2523e96209044b04a3793` | 7,729,345 |
| POST | `build/tomokv` | `f6c538e4a7ca836b7e34b3007cce31c5ea88ccf9e8cd495d296d9157a4a70f36` | 7,734,497 |
| PAD A | `build/climonfix-pad/tomokv` | `d301c7a9a4a86e88e7c544e5c900a3fa03c78ab9003b77f0fe33a4e24be2cf13` | 7,734,497 |

PAD is **kind A, behaviour twin**: mainline's pre-SV1/SV2 mask and shutdown behaviour,
with the candidate's data layout and total .text size. Individual function addresses
can differ; the paired live null is still required. It is never a correctness candidate.
PRE is built from fetched `origin/cpp` in the private archived source directory
`build/climonfix3-pre-src`; POST is the repaired worktree build. Neither PRE, POST nor PAD was executed. The serverless units use separate binaries. Build logs are `build/climonfix3-pre/build.log`,
`build/climonfix3-final-rebuild.log`, and `build/climonfix3-pad.log`.

The 14 cells are `h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,
d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`. Measure PRE/PRE null, PRE/POST, and PRE/PAD A with
the gate instrument. Matched-load rate/latency is the verdict; report cycles/op,
instructions/op and IPC together. All rate/cycle/IPC entries are pending mainline.

```bash
MR_RUN=$(mktemp -d "$PWD/build/climonfix3-abba.XXXXXX")
COMMON=(--cells tests/wbhybrid2_cells.txt --subset full --build-reference 0 \
  --server-cores 0-7 --server-smt '' --load-cores 8-111 --load-smt '' --ports 17993-17998)
NULL_RC=0
python3 tests/abbagate.py "${COMMON[@]}" --collect-null 1 \
  --candidate-binary build/climonfix3-pre/tomokv --reference-binary build/climonfix3-pre/tomokv \
  --output "$MR_RUN/null" || NULL_RC=$?
test "$NULL_RC" -eq 3 || exit 1
python3 - "$MR_RUN/null/results.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
assert r['null_control']['verdict'] == 'PASS', r['null_control']
PY
for ARM in post pad; do
  CANDIDATE=build/tomokv
  test "$ARM" != pad || CANDIDATE=build/climonfix-pad/tomokv
  python3 tests/abbagate.py "${COMMON[@]}" --candidate-binary "$CANDIDATE" \
    --reference-binary build/climonfix3-pre/tomokv --null-result "$MR_RUN/null/results.json" \
    --output "$MR_RUN/$ARM" || exit $?
done
```

`git diff 818f14eec49431bc611a4c2dcc0b7c2dfb42b35b --stat` below includes the required
merge, its RL1 artifacts, and this report. The repair alone before this report is
12 files, 329 insertions and 34 deletions versus merge commit `b4bd67523`.

```text
 MEASURE-REQUEST-climonfix3.md                      |  440 +++
 MEASURE-REQUEST-rlfence.md                         |  283 ++
 MEASURE-REQUEST-rlfence2.md                        |  315 ++
 MEASURE-REQUEST-rlfence3.md                        |  285 ++
 Makefile                                           |   12 +-
 docs/rlfence2/SHA256SUMS                           |    5 +
 docs/rlfence2/alt-h05-proof.json                   |  101 +
 docs/rlfence2/alt-io-audit.json.gz                 |  Bin 0 -> 469198 bytes
 docs/rlfence2/alt-io-changes.json                  |   97 +
 docs/rlfence2/alt-pad/POST-functions.tsv.gz        |  Bin 0 -> 148632 bytes
 docs/rlfence2/alt-pad/POST-sections.tsv.gz         |  Bin 0 -> 736 bytes
 docs/rlfence2/alt-pad/closure-proof.json           |   50 +
 docs/rlfence2/alt-pad/negative-controls.json       |   17 +
 docs/rlfence2/alt-pad/planned-retargets.json       |  198 ++
 docs/rlfence2/alt-pad/proof.json                   |   38 +
 docs/rlfence2/alt-source-receipt.json              |   11 +
 docs/rlfence2/alt-unit-pad/POST-functions.tsv.gz   |  Bin 0 -> 552 bytes
 docs/rlfence2/alt-unit-pad/POST-sections.tsv.gz    |  Bin 0 -> 626 bytes
 docs/rlfence2/alt-unit-pad/negative-controls.json  |   17 +
 docs/rlfence2/alt-unit-pad/pipeline.log            |    2 +
 docs/rlfence2/alt-unit-pad/planned-retargets.json  |  241 ++
 docs/rlfence2/alt-unit-pad/proof.json              |   38 +
 docs/rlfence2/alt-unit-pad/symmetry.log            |    1 +
 docs/rlfence2/alt-unit.log                         |    4 +
 docs/rlfence2/alt-write-ring.log                   |   21 +
 docs/rlfence2/alt.patch                            |   70 +
 docs/rlfence2/generic-merit-cells.txt              |   14 +
 docs/rlfence2/harness-controls.json                |   17 +
 docs/rlfence2/harness-positive.log                 |    4 +
 docs/rlfence2/headline-pre-identity.json           |   69 +
 docs/rlfence2/io-audit.json.gz                     |  Bin 0 -> 486835 bytes
 docs/rlfence2/io-changes.json                      |  179 ++
 docs/rlfence2/io-diffs/015.diff.gz                 |  Bin 0 -> 52076 bytes
 docs/rlfence2/io-diffs/025.diff.gz                 |  Bin 0 -> 47996 bytes
 docs/rlfence2/io-diffs/059.diff.gz                 |  Bin 0 -> 31351 bytes
 docs/rlfence2/io-diffs/061.diff.gz                 |  Bin 0 -> 38616 bytes
 docs/rlfence2/io-diffs/151.diff.gz                 |  Bin 0 -> 4564 bytes
 docs/rlfence2/io-diffs/217.diff.gz                 |  Bin 0 -> 8049 bytes
 docs/rlfence2/io-diffs/265.diff.gz                 |  Bin 0 -> 3361 bytes
 docs/rlfence2/io-diffs/275.diff.gz                 |  Bin 0 -> 3298 bytes
 docs/rlfence2/io-diffs/322.diff.gz                 |  Bin 0 -> 2891 bytes
 docs/rlfence2/pad-a/POST-functions.tsv.gz          |  Bin 0 -> 148664 bytes
 docs/rlfence2/pad-a/POST-sections.tsv.gz           |  Bin 0 -> 722 bytes
 docs/rlfence2/pad-a/closure-proof.json             |   50 +
 docs/rlfence2/pad-a/negative-controls.json         |   17 +
 docs/rlfence2/pad-a/planned-retargets.json         |  154 +
 docs/rlfence2/pad-a/proof.json                     |   38 +
 docs/rlfence2/post-unit.log                        |    4 +
 docs/rlfence2/post-write-ring.log                  |   21 +
 docs/rlfence2/production/SHA256SUMS                |    6 +
 .../alt-identity/CANDIDATE-functions.tsv.gz        |  Bin 0 -> 150939 bytes
 .../alt-identity/CANDIDATE-sections.tsv.gz         |  Bin 0 -> 738 bytes
 .../alt-identity/REFERENCE-functions.tsv.gz        |  Bin 0 -> 148632 bytes
 .../alt-identity/REFERENCE-sections.tsv.gz         |  Bin 0 -> 736 bytes
 .../alt-identity/differing-functions.json.gz       |  Bin 0 -> 1004664 bytes
 .../alt-identity/differing-functions.tsv.gz        |  Bin 0 -> 206115 bytes
 .../rlfence2/production/alt-identity/identity.json | 2929 ++++++++++++++++++
 docs/rlfence2/production/alt-io-audit.json.gz      |  Bin 0 -> 546530 bytes
 docs/rlfence2/production/alt-io-changes.json       | 3229 ++++++++++++++++++++
 docs/rlfence2/production/alt-io-diffs.txt.gz       |  Bin 0 -> 2838203 bytes
 docs/rlfence2/production/closure.json              |   50 +
 docs/rlfence2/production/default-build.log.gz      |  Bin 0 -> 1409 bytes
 docs/rlfence2/production/delayed-drain.log         |   10 +
 .../production/frozen-alt-identity-limit.json      |    5 +
 docs/rlfence2/production/frozen-h05-proof.json     |  101 +
 docs/rlfence2/production/harness-and-gate.json     |   79 +
 .../headline-identity/CANDIDATE-functions.tsv.gz   |  Bin 0 -> 150939 bytes
 .../headline-identity/CANDIDATE-sections.tsv.gz    |  Bin 0 -> 738 bytes
 .../headline-identity/REFERENCE-functions.tsv.gz   |  Bin 0 -> 150914 bytes
 .../headline-identity/REFERENCE-sections.tsv.gz    |  Bin 0 -> 725 bytes
 .../headline-identity/differing-functions.json.gz  |  Bin 0 -> 554836 bytes
 .../headline-identity/differing-functions.tsv.gz   |  Bin 0 -> 116944 bytes
 .../production/headline-identity/identity.json     | 2900 ++++++++++++++++++
 docs/rlfence2/production/headline-io-audit.json.gz |  Bin 0 -> 566183 bytes
 docs/rlfence2/production/headline-io-changes.json  |  236 ++
 docs/rlfence2/production/headline-io-diffs.txt.gz  |  Bin 0 -> 51304 bytes
 docs/rlfence2/production/identity-controls.json    |   13 +
 docs/rlfence2/production/mainline-verdict.txt      |   13 +
 docs/rlfence2/production/mget-fence-old.log        |   11 +
 docs/rlfence2/production/mget-fence-stale.log      |   11 +
 docs/rlfence2/production/mget-fence-unarmed.log    |   11 +
 docs/rlfence2/production/mget-fence.log            |    4 +
 docs/rlfence2/production/negative-pipeline.log     |    2 +
 docs/rlfence2/production/negative-unit.log         |    1 +
 docs/rlfence2/production/portable-unit.log         |    4 +
 .../server-control/PAD-A-functions.tsv.gz          |  Bin 0 -> 150939 bytes
 .../server-control/PAD-A-sections.tsv.gz           |  Bin 0 -> 738 bytes
 .../server-control/POST-functions.tsv.gz           |  Bin 0 -> 150939 bytes
 .../production/server-control/POST-sections.tsv.gz |  Bin 0 -> 738 bytes
 .../server-control/negative-controls.json          |   17 +
 .../server-control/planned-retargets.json          |  198 ++
 docs/rlfence2/production/server-control/proof.json |   38 +
 docs/rlfence2/production/source-receipt.json       |    9 +
 docs/rlfence2/production/transient.log             |   10 +
 docs/rlfence2/production/unit-build.log            |    2 +
 .../production/unit-control/PAD-A-functions.tsv.gz |  Bin 0 -> 552 bytes
 .../production/unit-control/PAD-A-sections.tsv.gz  |  Bin 0 -> 628 bytes
 .../production/unit-control/POST-functions.tsv.gz  |  Bin 0 -> 552 bytes
 .../production/unit-control/POST-sections.tsv.gz   |  Bin 0 -> 628 bytes
 .../production/unit-control/negative-controls.json |   17 +
 .../production/unit-control/planned-retargets.json |  241 ++
 docs/rlfence2/production/unit-control/proof.json   |   38 +
 .../production/unit-negative-controls.json         |   12 +
 docs/rlfence2/production/unit.log                  |    4 +
 docs/rlfence2/production/write-ring.log            |   21 +
 src/cmd/server_tail.cc                             |   12 +-
 src/core/server.h                                  |   14 +-
 src/net/rob.h                                      |   42 +-
 src/snapshot/snapshot.cc                           |   53 +-
 src/snapshot/snapshot.h                            |    2 +-
 tests/aof_rewrite_matrix.sh                        |    2 +-
 tests/aof_rewrite_trigger_matrix.sh                |    2 +-
 tests/climonfix_artifacts.py                       |   38 +-
 tests/fixtures/nullrefresh-ledger-labels.json      |   26 +-
 tests/gate.sh                                      |   39 +-
 tests/gate_measurements.json                       |    8 +-
 tests/gates_test.py                                |   48 +
 tests/read_local_lane.py                           |  236 +-
 tests/rlfence_unit.cc                              |  145 +
 tests/shutdown_persist.py                          |   17 +-
 tests/shutdown_unit.cc                             |  164 +-
 tools/rlfence_artifacts.py                         |  490 +++
 122 files changed, 14310 insertions(+), 63 deletions(-)
```
