| Variant | resets/trials | EOF/trials | other monitor failures | incomplete trials |
|---|---:|---:|---:|---:|
| 2s-both-default | 0/10 | 0/10 | 0 | 0 |
| 2s-close-default | 0/10 | 0/10 | 0 | 0 |
| 2s-storm-default | 0/10 | 0/10 | 0 | 0 |
| 2s-both-client-off | 0/10 | 0/10 | 0 | 0 |
| 2s-close-client-off | 0/10 | 0/10 | 0 | 0 |
| 2s-storm-client-off | 0/10 | 0/10 | 0 | 0 |
| 2s-both-key-off | 0/10 | 0/10 | 0 | 0 |
| 2s-close-key-off | 0/10 | 0/10 | 0 | 0 |
| 2s-storm-key-off | 0/10 | 0/10 | 0 | 0 |
| 2s-both-both-off | 0/10 | 0/10 | 0 | 0 |
| 2s-close-both-off | 0/10 | 0/10 | 0 | 0 |
| 2s-storm-both-off | 0/10 | 0/10 | 0 | 0 |
| 2s-both-storm1000 | 0/10 | 0/10 | 0 | 0 |
| 2s-close-storm1000 | 0/10 | 0/10 | 0 | 0 |
| 2s-storm-storm1000 | 0/10 | 0/10 | 0 | 0 |
| 1s-both-default | 0/10 | 0/10 | 0 | 0 |
| 1s-close-default | 0/10 | 0/10 | 0 | 0 |
| 1s-storm-default | 0/10 | 0/10 | 0 | 0 |
| 1s-both-client-off | 0/10 | 0/10 | 0 | 0 |
| 1s-close-client-off | 0/10 | 0/10 | 0 | 0 |
| 1s-storm-client-off | 0/10 | 0/10 | 0 | 0 |
| 1s-both-key-off | 0/10 | 0/10 | 0 | 0 |
| 1s-close-key-off | 0/10 | 0/10 | 0 | 0 |
| 1s-storm-key-off | 0/10 | 0/10 | 0 | 0 |
| 1s-both-both-off | 0/10 | 0/10 | 0 | 0 |
| 1s-close-both-off | 0/10 | 0/10 | 0 | 0 |
| 1s-storm-both-off | 0/10 | 0/10 | 0 | 0 |
| 1s-both-storm1000 | 0/10 | 0/10 | 0 | 0 |
| 1s-close-storm1000 | 0/10 | 0/10 | 0 | 0 |
| 1s-storm-storm1000 | 0/10 | 0/10 | 0 | 0 |

PRE completed all 30 variants x 10 fresh boots: **0/300 monitor ECONNRESET,
0/300 monitor EOF, zero other monitor failures, and zero incomplete trials**.
Both 2s (150 trials) and 1s (150 trials) passed the read-only geometry/window audit.
Maximum measured spacing between monitor samples was 119.273 ms (target 100 ms).
These are correctness observations on CPUs 112–127, not performance measurements.
POST and TRACE each also completed 10 simultaneous-close/storm trials per mode (20 each),
with zero resets, EOFs, other monitor failures, or incomplete trials. All saved results pass
the final validator. PRE's campaign began with reproducer commit 0ef1b80f6; later geometry
and window assertions also accept every saved PRE trial without excluding or rerolling any.

| Arm / simultaneous close + storm | 2s resets / EOF | 1s resets / EOF |
|---|---|---|
| POST, default profile | 0/10 / 0/10 | 0/10 / 0/10 |
| TRACE, default profile | 0/10 / 0/10 | 0/10 / 0/10 |

The complete per-trial JSON is committed as `docs/connreset/{pre,post,trace}-results.jsonl.gz`;
`docs/connreset/repro-summary.json` binds it to manifests and SHA256 receipts. Detailed monitor
streams and server logs remain under `build/connreset/{matrix-pre,post-check,trace-check}`.
The ordinary PRE/POST binaries were checked separately from TRACE; TRACE is diagnostic only.

The reported mainline resets are explained by an exceptional-cleanup defect in
`tools/lb_episodes.py`, not by evidence of a spontaneous accept/close failure. All seven
saved reset episodes rejected their balanced baseline (one or two client moves), then
unwound `boot()` while `Sampler` was still polling. `Children.close()` terminated the
server; the later `Sampler.close()` exception replaced the original baseline error.
Every affected record has exactly two baseline commands, no `stimulus_t`, and no
hot/cold files. Server IO shutdown began 6.68–6.91 ms after baseline end.

Moreover, each saved server's accepts equal the sum of the two baseline selectors'
`attempts` plus exactly two connections (admin and sampler). The selector chooses one
specific `wanted` owner for each connection, including when all owners are listed;
it does not accept the first socket belonging to any allowed owner.
`docs/connreset/harness-evidence.json` records the original paths, SHA256 receipts,
underlying baseline errors, accept arithmetic, and monotonic timestamps.

The fix enters the sampler as an inner context, so its thread stops and joins before
server teardown on success or failure. A secondary observer failure is recorded without
replacing an existing episode failure. Invalid baselines still FAIL; real monitor errors
still FAIL. No baseline thresholds or measurement verdicts were relaxed.

The new serverless witness in `tests/connreset_harness_test.py` passes four cases. Its
throwaway negative control restores the old cleanup edges and fails with the original
`sampler failed: [Errno 104] Connection reset by peer` masking symptom. The existing
29 LB episode self-tests pass. `bash -n tests/gate.sh`, Python compilation, and R7 generated
envelope synchronization pass. The full gate and benchmarks were not run. All three builds emitted zero compiler diagnostics.

`tests/gate.sh` adds one serverless row in `job_lbplanner_units`, collected before the
quick-tier exit. Maintainer change required: EXPECT_QUICK 490 -> 491; EXPECT_FULL 507 -> 508.
The constants are untouched.

Reproducer geometry: taskset CPUs 112–127, two 8-core L3 domains, io_uring, jemalloc,
`--flip-auto 0 --enable-debug-command yes --save '' --appendonly no`.
2s has 8 IO + 8 EX and 64 default shards; 1s has 16 fused threads and 128 default shards.
All generated load and sampler work also stays on CPUs 112–127. Every trial uses a fresh
server, one retained monitor polling INFO + DEBUG LBSIGNALS at 100 ms, a 3-second armed
baseline, pipeline 128 alternating SET/GET with 64-byte values, and two seconds after
transition. The monitor is never reconnected; post-failure telemetry uses a separately
identified recovery connection. Storm workers close each socket after one DEBUG IO-THREAD
reply. Both closes the persistent cohort immediately and launches the storm in the same
asyncio turn; close and storm isolate the two actions. Default/client-off/key-off/both-off
use 128 persistent clients and 500 storm sockets, with client/key LB (1,1)/(0,1)/(1,0)/(0,0).
Storm1000 uses (1,1), 64 persistent clients, and 1,000 storm sockets. Each cell repeats ten times.

The inspected server candidates included monotonic client IDs, raw io_uring file descriptors
(no fixed-file slot table in this path), teardown's ROB/kernel/EX lifetime fences,
source-ring receive completion before IO migration, and per-owner SO_REUSEPORT listeners.
No server-side root cause was established, so no speculative lifetime/ownership fix was made.

Every trial retains INFO CLIENTS/ALL, before/after connected_clients, rejects, output-buffer
disconnects, send errors/peer aborts, process affinity, server logs and monitor samples.
All 340 trials had zero rejected connections, output-buffer-limit disconnects, and send errors.
INFO has no evicted_clients field on this server. Peer aborts rose when the load cohorts were
intentionally closed; their measured totals and maxima are retained in the summary.
`--validate-results` refuses incomplete matrices, missing pipeline/storm witnesses,
wrong geometry, client-count mismatches, and a missing post-transition monitor sample.
Four recorded negative audit controls each fail: zero completed pipelines, an incomplete
storm, no post-transition sample, and a 6:8 split presented as 8:8.

PRE is merged origin/cpp ea177342dd9ce181488f0954fe436d5f25d78fe5, built locally. PRE and POST
artifacts are `build/connreset/tomokv-PRE` and `build/connreset/tomokv-POST`.
Their complete 7,796,224-byte ELF .text sections are identical:
735516f12be5ae478d15a34383615160e59da019c1ce9e9c2edc62b731b6fffe.
This includes every command and IO hot path. No locked structure changes. No PAD arm is
needed because the production text size/layout and behavior are identical.
`docs/connreset/artifacts.json` binds the binaries and text receipts.

`make connreset-trace` builds `build/connreset/trace/tomokv` with TOMO_CONNRESET_TRACE.
DEBUG CLOSE-STATS exposes counts by close call site; stderr also records first-close and
fd-release client IDs/fds/owners plus EOF/receive errno events. All instrumentation is on
failure/teardown paths, has no per-command probes, and compiles out entirely in production.
This is a diagnostic binary, not a PAD arm or a performance comparison.
Across all 20 TRACE trials, DEBUG CLOSE-STATS returned the counters; no logged owner mismatch
occurred; every retained monitor's recorded receive-close event was EOF from its intentional
end-of-test close. `docs/connreset/trace-evidence.json` records the counts and monitor events.

To repeat the exact churn matrix:

```sh
python3 tests/connreset_repro.py --binary build/connreset/tomokv-PRE --output build/connreset/repeat-pre
python3 tests/connreset_repro.py --validate-results build/connreset/repeat-pre --expect-clean
```

The synthetic workload differs from the original live harness: short baseline versus
93 seconds; 128 small private keys and mixed SET/GET versus 500,000 keys and SET-only
memtier; Python connect timing versus the LD_PRELOAD selector; unselected storm sockets
versus surviving stimulus clients pinned to chosen owners; immediate transport closes
versus memtier's process exit; and loader CPU sharing versus dedicated remote cores.
If a fresh failure survives the cleanup fix, the next witness should retain the original
selector and 64 clients targeted to two owners, its 93-second baseline and seed, and record
natural memtier exit separately from an explicit SIGTERM arm. Those are follow-up differences,
not evidence that the seven archived runs reached the stimulus.
