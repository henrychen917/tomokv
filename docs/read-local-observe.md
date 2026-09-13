Read-local observation — 2026-09-13 crash resume

The candidate adds INFO telemetry and ABBA recording. The first fresh reproduction attempt failed
the unchanged quiet-box precondition before any server boot: 4.76 CPU-seconds on the selected
cores exceeded the 3.36 budget per 20 seconds. No new rate or PMC sample exists. The dynamic
amortization verdict and final variance attribution remain pending; the static counts below do
not establish the 3% budget. MEASURE-REQUEST specifies the arms, cells, interventions and decisions.
No gate row or expected count changes are required.

Implementation

Lane-served reads stay outside SLOWLOG. Capturing argv, taking clocks and writing a log on every
hit would add work to the path being observed. The implementation lives in
src/core/read_local_observe.h, with hooks at the drain boundary, optional thread state and INFO.
Existing exact lifetime hits, command fallbacks, arms and admission deferrals are reused. INFO
adds physical-thread roles, active-lane flags, shard ownership, accepts and connection counts.
There is no per-client observation allocation or change to read eligibility, ownership or LB.

One reply preparation per physical thread per distinct cached millisecond is sampled. The sample
index varies within the first chunk. The ordinary drain is a separate template instantiation with
no per-command sampling branch, timer, new counter or pointer chase. The boundary test and the
sampled instantiation still have a cost, which must be measured rather than called zero.

Only locally committed samples contribute reply bytes and latency. A prepared reply after an
earlier fallback increments uncommitted_samples and contributes neither. The bucket upper bounds
are 128, 256, 512, 1024, 2048, 4096, 16384, 65536 ns, then infinity; buckets are noncumulative.
Latency covers prepare_local_read plus timer overhead. Pure GET chunks capture and prefetch before
that call; MGET and mixed chunks capture inside it. It excludes queue residence, chunk gathering,
completion and sending. These time-sampled buckets are not command-weighted or end-to-end
percentiles. sampled_reply_bytes is actual RESP bytes from sampled replies, never estimated total
traffic. More observation WINDOW increases evidence; no sample-rate or logging knob was added.

Sample counters have one writer and use relaxed atomic loads/stores, without locked RMWs, reader
retries or seqlocks. INFO loads each field independently: a concurrent sample may straddle fields.
Existing hit/fallback/arm/accept counters retain their existing plain cross-thread INFO convention;
this change does not make those old counters transactional or cure that existing C++ data-race
exposure. New sample publication occupies different cache lines from the owner's sampling test.

INFO read_local has a dedicated path that avoids the ordinary shard and command-stat scan. INFO
ALL/EVERYTHING also include the section. The RESP2 bulk / RESP3 verbatim grammar is preserved.
Lifetime counters survive RESETSTAT and role changes. Roles, active flags, shard counts and
connection counts are gauges; they are retained at both endpoints and are never subtracted.
Misses mean command fallbacks, not missing keys.

tests/abbagate.py records raw endpoints before/after the central rate/PMC interval, timestamps,
total and per-thread counter deltas, histogram deltas and placement endpoints. Each measurement
has read_local_hits, read_local_misses and read_local_histogram beside rate and busy. Observation
windows are slightly wider than the central rate interval, with the offsets retained. Old binaries
are UNAVAILABLE with null metrics; malformed or reset telemetry is INVALID. Neither supplies
invented zero evidence or changes rate, accounting, saturation, thresholds or verdicts.

Amortization and controls

| Quantity | PRE | POST | PAD |
|---|---:|---:|---:|
| Observation allocation, read-local=0 | 0 | 0 | 0 |
| Optional armed state sizeof per thread | 384 B | 576 B | 576 B |
| Optional armed allocation alignment | 8 B | 64 B | 64 B |
| Jemalloc size class per armed thread | 384 B | 640 B | 640 B |
| Armed allocation for 32 threads | 12 KiB | 20 KiB | 20 KiB |
| Ordinary drain static instructions, no owner yield | 574 | 574 | 574 |
| Ordinary drain static instructions, owner yield | 678 | 678 | 678 |
| Retired instructions/op, read-local=0 | unmeasured | unmeasured | unmeasured |
| Retired instructions/op, read-local=1 | unmeasured | unmeasured | unmeasured |
| IPC, cycles/op, matched-load rate, both modes | unmeasured | unmeasured | unmeasured |

The rebuilt PRE/POST/PAD have identical normalized ordinary-drain instruction streams, including
memory offsets; build/readlocal-obs/arms/inspection.json preserves the counts and layout results.
NOP padding is excluded; addresses and the Observe=false template argument in symbol names are
normalized. This does not count the caller's added boundary test or sampled work, or exclude a code
placement effect on IPC. The disabled guard precedes the observation access; no observation state
is allocated with read-local=0. Whole-server disabled instructions/op still requires measurement.
All eight required production layout assertions pass in the release builds and the layout check.

PAD is PRE plus zeroed padding in its optional sidecar: same size, alignment and original field
offsets as POST, with PRE execution and INFO. It is generated only under build/; no build selector
ships. PRE->PAD measures allocation/layout effects, PAD->POST adds observation/code effects, and
PRE->POST decides the total. A <=3% always-on budget needs measured rates and cycles/op with
identical-arm scatter small enough to resolve that cost. No performance approval is claimed.

The reproducible builder and diagnostic driver are tests/read_local_observe.py. All artifacts stay
in this worktree, and the driver terminates only subprocesses it created. Build commands, source
revisions and complete SHA-256 digests are in build/readlocal-obs/arms/manifest.json:

| Arm | SHA-256 prefix |
|---|---|
| PRE | 04d13456cad5582c |
| POST | 1c32edcabdd79f05 |
| PAD | 4f7f6f40a9acf783 |

docs/read-local-observe-build.json also commits those digests, the static inspection, test status
and failed quiet-screening summary so another build-directory cleanup does not erase the record.

Recreate the static checks with `python3 tests/read_local_observe.py inspect`. The diagnostic POST
GET runs require positive local hits, positive sampled hits and a nonempty histogram. A run that
never fires the sampler fails this directed check; no histogram-equals-hit assertion is imposed on
independent snapshots. PRE/PAD, disabled reads and pure writes do not claim a sampler witness.
This check is in the diagnostic driver, and has no authority over abbagate's scoring rules.

Archived variance evidence

docs/read-local-observe-evidence.json preserves the relevant inputs from the pre-crash extract,
including placement arrays, load geometry, boot configuration and counter deltas. The original
cx-final/build/gate-run.uWT7j5/abba/results.json directory was removed during disk cleanup. This
is analysis of that saved experiment, not a fresh reproduction or new per-thread hit measurement.
The start timestamp was 2026-09-11T21:27:51Z (September 12 in Taipei).

| Cell | Instances | Four rates, Mops/s | (max-min)/mean |
|---|---:|---|---:|
| h11 | 4 | 56.12356, 54.69019, 54.33305, 53.62961 | 4.560% |
| h15 | 4 | 55.92006, 52.41915, 54.03423, 52.77736 | 6.509% |
| h27 | 8 | 30.09787, 29.61689, 30.83274, 31.27335 | 5.439% |
| h31 | 8 | 30.54649, 29.84274, 29.16920, 29.63282 | 4.622% |
| m47 | 1 | 1.55837, 1.55868, 1.55748, 1.55737 | 0.084% |

| h11 boot | Arms before window | New arms | Hit delta | Fallback delta | Clients/thread | Connection CV |
|---|---:|---:|---:|---:|---|---:|
| A1 | 512 | 0 | 1,122,586,048 | 0 | 9–26 | 24.83% |
| B1 | 512 | 0 | 1,093,906,720 | 0 | 9–24 | 23.83% |
| B2 | 512 | 0 | 1,086,773,600 | 0 | 10–26 | 22.79% |
| A2 | 512 | 0 | 1,072,703,136 | 0 | 9–22 | 20.06% |

The first hypothesis, incomplete arming, does not explain these windows: h11/h15/h27/h31 each
showed 512 arms before the window, no new arms inside it and zero command fallbacks. h11's hit
deltas account for virtually all measured GETs; only hundreds of commands separate independently
sampled totals containing over a billion commands. Its admission deferrals were also zero.

Placement differed across boots, but h11's connection-count CV improved monotonically as rate
fell. Simple count imbalance therefore is insufficient to explain the decline. This does not
exclude which generator feeds each connection or which CPUs execute its workers. Mean generator
CPU per configured worker fell 80.75 -> 79.15 -> 77.73 -> 77.21%. That covariance cannot determine
causal direction in a closed-loop load: it does not prove either generator headroom or starvation.

h31 showed a different symptom: quota deferrals rose from 56,639 to 2,344,471 / 2,296,475 /
3,329,618, and capacity deferrals from 338 to 93,776 / 84,314 / 106,746, still with zero fallbacks.
This deserves comparison with thread placement and hit rates; it is not evidence of one common
cause with h11, where both kinds of deferral remained zero.

The warmup/decay hypothesis remains open. Four decreasing fresh-boot averages do not establish
decay within a boot. The reported stable 128/1 hand control changes both connection population and
generator count, so it cannot by itself rule out a server working-set effect at 512 connections.
Longer windows and settle-only interventions on the same 512/4 shape are needed. A measured
<=1% recipe must preserve meaningful load/occupancy, not just lower the rate until it is quiet.
The evidence does not yet justify changing either the server or the gate's cell definitions.

An exact replay also has two constraints absent from the shorthand task description. The archive
used four instances for h11/h15 and eight for h27/h31. It used server CPUs 0–31 and generator
physical CPUs 32–127 plus SMT 160–255. The current assignment permits 0–111. The supplied driver
therefore labels the requested 512/4 run with historical_geometry_match=false. Matching the
historical CPU axes and split instance counts requires a separately scheduled maintainer replay.

Validation and recovery

PRE, POST and PAD release builds passed on CPUs 104–111 with four compiler jobs. The observation
unit passed: bucket boundaries, discarded-prefix exclusion, byte/time accounting, sample-index
coverage, INFO totals/per-thread formatting, and an off-mode INFO path whose optional-state
accessors assert if called. The unit is included in make unit and starts no server.

The resumed ABBA serverless run passed 85/86 primary tests (including both observation tests and
the actual Runner.measure recording test), 10/10 saturation tests and 7/7 calibration tests.
The primary failure was an existing child-process cleanup race at tests/abbagate.py:3752:
ProcessLookupError while reading /proc/<exited-child>/stat inside the polling loop. Its final read
already handles that exception, but the polling read does not. This failure is retained in
build/readlocal-obs/resume-abbagate-selftest.log; the harness change remains limited to recording.
The gate was not run. Both-mode live correctness and the performance verdict remain maintainer work.
The diagnostic driver's two serverless controls also passed: missing/inactive sample evidence is
rejected, and an altered PRE layout cannot silently produce an invalid PAD twin. Python syntax
checks and git diff --check passed. Build logs contain no compiler warnings or errors.

The failed live-attempt record is build/readlocal-obs/reproduce-pre/results.json and its quiet
CPU evidence is in quiet.jsonl beside it. The guard failed before population or measurement, so
there is no four-boot reproduction to report. The failure and all binaries are retained; neither
the quiet threshold nor the gate cell definition was changed to obtain a result.
A later read-only process check found another binary-B server and eight load generators on
selected CPUs. Their PIDs and last CPUs are preserved in the build record. No foreign process was
signalled, and no further measurement was attempted over that workload.

The initial recovery appeared as c827a7c62, followed by the unit integration commit fbb3e3d00.
At 11:26 the shared Git store was lost and re-created, removing those objects and 87b88cc4e.
The maintainer re-attached the preserved working tree as a19996091 over a363c2c5e. The builder uses
that surviving parent: 87b88cc4e only changed a gate reference pointer, so its server sources and
a363c2c5e's server sources match. Further work is committed on cx-readlocal-obs. The inherited
gate reference update is part of that recovery, not a new measurement result from this lane.

Existing conflicts with the stated read-path laws, outside the observation change

prepare_captured_local_mget in src/core/ex_loop.h has kAttempts=2 and revalidates generation/cell
epochs around capture and copying. On churn it retries even in the default immutable build. That
conflicts with the stated no-reader-retry/no-per-operation-seqlock law. It has not been weakened
or changed to make the observation test pass.

The GET helper's source has a three-attempt loop, but the repeat edge requires the experimental
object-sequence overwrite selector. Default selector 0 always succeeds at that copy helper, so
the source loop alone is not evidence of default GET retries. Experimental selectors 1 and 3 in
src/store/read_local_settax.h allow in-place overwrite with sequence validation; they conflict
with the armed-lane laws but are not selected or enabled by this change.
