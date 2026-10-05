# gt14fix2 — ASAN-safe directed RENAME hold

Base: `0849c451f` on `cx-gt14fix`; this worktree already contains the requested
`07023fd6e` merge. Implementation: `d040a8785`. No push.

## Mechanism and ceiling

`DEBUG ATOMIC-OFF-HOP-HOLD <milliseconds>` now arms a one-shot hold with the
caller's budget; `0` releases it. Positive arguments clamp to **30,000 ms** before
multiplication, including the largest uint64 argument. This DEBUG-only argument
replaces the old boolean grammar; it adds no configuration option. The existing
`ATOMIC-OFF-HOP-DELAY` microsecond grammar and ceiling are unchanged.

The test uses `min(30000, int(max(5.0, MECHANISM_TIMEOUT) * 1000))`. Its existing
mechanism timeout is 30 seconds on both release and sanitizer tiers, so both pass
30,000 ms. This follows the harness's existing liveness budget without guessing
sanitizer slowdown or maintaining build-specific multipliers.

The existing atomic word carries the tagged millisecond budget until a RENAME
claims it with a CAS, then carries the untagged absolute deadline/generation.
The destination's existing deferred task checks that generation. No structure
layout, arena pointer, allocation, reader retry, or per-operation seqlock is added.
An expired claimed deadline remains status 3 until explicit DEBUG release/rearm;
command completion and status polling do not reset it. Statuses remain 0=off,
1=armed/waiting, 2=source complete while destination held, 3=expired.

`rename_held` waits for status 2 until the same client-side ceiling, failing on
expiry, premature RENAME completion, error, or no witnessed window. The exact
OFF/ON images and the status-2 check after MGET remain mandatory. Its existing
notes now include `hold_s`, `witness_s`, and `ceiling_ms`. Times are client elapsed
from issuing the arm through the last observation before release, not a claim to
measure the server's internal claim timestamp. The ON hammer retains its own
independent nonempty-read assertion.

## Build and byte audit

Release: `taskset -c 112-127 make -j16`. ASAN uses the exact `job_asan` build in
`tests/gate.sh:1215`: `tests/parbuild.sh build/gate-cache/tomokv-asan
build/gate-cache/obj-asan`, flags `-std=c++20 -O1 -g -fsanitize=address
-march=native -pthread -I.`, link flags `-luring -pthread -lssl -lcrypto`, and its
unchanged source list. Both builds passed.

PRE/POST binaries and linked production objects are preserved in
`build/gt14fix2/`. Audit command:

```bash
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare \
  build/gt14fix2/pre build/gt14fix2/post docs/gt14fix2/hot-identity.json
```

**1,482/1,482 selected hot bodies are raw-byte and resolved-relocation identical**
across both database variants. This is the existing tool's selected object-body
claim, not identity of every function or linked address. Unit-test objects were
excluded from the final audit. PRE `.text` is 7,797,376 bytes; POST is 7,797,680
(+304). This is a correctness hook fix with no performance claim or PAD arm.
Hashes and section/function inventories are in `docs/gt14fix2/`.

## Validation status

ASAN target battery: **10/10 PASS** on fresh boots. OFF and ON each made their
required exact held observation on all ten runs; all OFF reads were torn. OFF
client hold time was 1.367–1.478 ms (median 1.403 ms); ON was 0.370–1.451 ms
(median 1.367 ms). Every ceiling was 30,000 ms. Full per-run logs, timings, and
shutdown outcomes are in `docs/gt14fix2/repeat/asan-summary.json` and adjacent
compressed logs. The ten complete standalone sequences each reported a
LeakSanitizer failure at shutdown (64 allocations); **0/10 clean shutdowns**.
These failures are retained and are not counted as clean ASAN job passes.

Release evidence is being collected; no pending repetition is counted as a pass.
The release request is 20 serial repetitions of the unchanged complete subset:

```bash
GATE_ONLY_JOBS='atomic_batteries debug-1' taskset -c 112-127 bash tests/gate.sh quick \
  --server-cores 112-119 --load-cores 120-127 --load-smt '' --ports 19900-19902 \
  --candidate-binary "$PWD/build/tomokv"
```

The ASAN `iteration` subset is refused before boot by the unchanged resource
planner: there is no reviewed ABBA ratio for eight server threads. The refusal is
retained in `docs/gt14fix2/asan-plan-refusal.log`. No gate or measurement fixture
was modified to bypass it. The standalone ASAN runner uses fresh boots at the
same 16-shard, 6-IO/2-executor geometry, server CPUs 112–119 and client CPUs
120–127; it runs the four unmodified `job_asan_batteries` Python commands in order,
including omission of `--release-build` and addition of `--no-rate-assertions`
only to `atomic_ryow.py`. Shutdown and sanitizer outcomes are retained separately
from target-test outcomes. This is diagnostic evidence, not a gate receipt.

Directed controls passed on split and fused boots: a 1.2-second observer pause
retained status 2 and the exact OFF/ON image, a 100 ms hold expired to status 3
and stayed expired after another RENAME, and explicit release reset it to 0.
Passing uint64-max as the ceiling expired after the hard 30-second cap (observed
at 30.103 seconds). A throwaway binary with both database variants' HOLD setters
replaced by `ret` made `rename_held` fail with status 0 and zero reads. Patch
offsets/hashes and control transcripts are retained.

No TSAN `atomic_torn.py` row or TSAN server target exists in this gate revision;
its TSAN jobs build and run separate units. Therefore the conditional TSAN request
has no corresponding row to run.

Gate delta **0 quick / 0 full**. No EXPECT, fixture, gate, xscript, or unrelated
atomic test helper changes. AST checks preserve existing row labels and every
helper except `rename_held`. Python compilation and `git diff --check` pass.

The requested repetitions exceed the 40-minute budget: existing complete release
subsets took roughly 110 seconds each (~37 minutes for twenty), before builds and
ASAN. The timing conflict was raised while work continued.
