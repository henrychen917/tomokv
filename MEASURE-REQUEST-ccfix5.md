# ccfix5 — armed differential diagnosis

Work in progress. A is diagnosed and fixed in the harness; B and the final
matrix repetitions are still in progress. This is not a landing receipt.

## Frozen source and binaries

Started at ccfix4 `99545f868`; merged local `origin/cpp`
`dbd01dd99269d10225f7f3d17d300cb3f653b654` in `1ebeceac0` before building.
PRE is a fresh archive/build of that upstream commit. POST is the merged
ccfix production source. ccfix5 currently changes no production source,
compiler budget, layout or runtime knob. Both builds use the repository
Makefile, GCC 13, and CPUs 112–127; each build used eight parallel jobs.

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/ccfix5/PRE/tomokv` | `7a309dc43071aab9cfe59155515b268dd2cf08b089105cd8a5007224d142e92b` |
| POST | `build/ccfix5/POST/tomokv` | `96f949e0dcc4264e094cdff010f4099f2cc033c6c31ea8a3787803b79033ae1c` |
| Review | `build/tomokv` | `96f949e0dcc4264e094cdff010f4099f2cc033c6c31ea8a3787803b79033ae1c` |

[Checksums](docs/ccfix5/SHA256SUMS), [production blobs](docs/ccfix5/source-manifest.json),
[merged PRE→POST patch](docs/ccfix5/production.diff), and
[ccfix5 production delta](docs/ccfix5/ccfix5-production.diff) are retained.
The original landing executable is preserved as `build/ccfix5/landing-tomokv`.
There is no PAD arm: this lane changes only tests and diagnostic/reporting tools.
No throughput benchmark or push is performed.

## A: RESETSTAT erased the witness

The original row sampled INFO only once, after all suites. That value is not a
lifetime count. `command_config_resetstat()` snapshots `ReadLocalStats` through
`collect_stat_totals()`, and `cmd_info()` subtracts `baseline.read_local.hits`
(and the other read-local counters). CC18 explicitly exercises RESETSTAT three
times, including at the end of its suite. The following psfix suite performs
configuration/persistence operations and contributes no ordinary GET hits in
atomic=0. Thus the terminal zero says nothing about earlier lane execution.

The full replay on POST, eight fused threads on 112–119, load on 120–127,
16 shards, `--read-local 1 --atomic 0 --databases 16`, gives seed 7:

| Observation | hits | fallbacks | arms | effective read_local |
|---|---:|---:|---:|---:|
| ccfix entry | 964 | 268 | 3 | 1 |
| before its first RESETSTAT | 964 | 270 | 4 | 1 |
| after that RESETSTAT | 0 | 0 | 0 | 1 |

The later RESETSTATs also return zero. An `arms=0` counter after resetting
statistics is not a disarmed lane. The traces are printed by the real ccfix leg.

`tools/ccfix5_probe.sh` imports the actual `tests/differ_gate.sh` boot/ownership
helpers and `GATE_DIFFER_GEOMETRY=armed-fused`. Three fresh boots **per atomic mode
per arm** all serve exactly 1,024 clean reads, report zero after RESETSTAT, then
serve another 1,024 clean reads with zero fallbacks. Every boot still reports
`thread_mode=1s read_local=1`. Each atomic=1 boot additionally opens 12/12 held
MSET windows: 36/36 PRE and 36/36 POST, with two pending entries and no writer
reply while held. This first probe isolates arming/reset behavior; it does not
replace the matrix's pending-source reader proof. Full INFO and DEBUG LBSIGNALS
dumps are in [PRE](docs/ccfix5/probe-PRE) and [POST](docs/ccfix5/probe-POST), with a
[summary](docs/ccfix5/fresh-probes.json).

There is no differing eligibility condition in this reproduction. The ordinary
parse/GET/drain selection is 272/272 canonical bodies equal to merged PRE
([inventory](docs/ccfix5/read-path-audit.json)). The notification mask is copied
to `set_read_local_keymiss_notify()` by `IoLoop::refresh_notify_config()`; the
keymiss bit intentionally routes notification-sensitive reads through the owner.
Neither that code nor `Shard`'s flat sink binding differs from merged PRE.
CC11's classifier runs only after the notification observer admits a keymiss.
The classifier was not reverted: executing the unchanged POST already disproves
the assertion that it never serves a local read.

Fix: `differ_gate.sh` samples the real counters after every suite and retains
their peak observation, including a per-leg TSV. The final row explicitly
reports both the peak and final values; the peak is not labelled a lifetime
total. No synthetic reads are added. A reset cannot erase an observed hit;
zero throughout, missing/malformed counters, or a failed observation still fail.
The real shell loop is exercised by `differ_fanout_test.py`: a 0→7→0 trace passes,
all-zero and missing-counter controls fail, and no invalid completion artifact
is accepted. All 19 serverless harness tests pass
([log](docs/ccfix5/fanout-test.log)).

The mainline idle-box comparison used different workloads. The headline tree
does not register ccfix, so it executes neither the extra counter resets nor
the pending-source test. Its terminal 914 hits therefore cannot be compared to
ccfix's post-reset zero as a binary execution-rate difference. The landing and
idle logs remain valid observations; the inferred lifetime interpretation was
incorrect. No contention explanation is needed for A.

The actual fourteen-cell null uses `/tmp/claude-1000/generic_merit_cells.txt`,
not ccfix4's proposed headline-cell list. Its four l1 cells are d32g_l1,
d8s_l1, d32s_l1 and x9_32_l1: **32 fused threads on 0–31, 256 shards, atomic=1,
read-local=1, overlap=1, reorder=0**, 512 connections, with load on 32–111.
Their recorded boot INFO confirms the lane is armed. They do not execute CC18's
RESETSTATs or the held pending-source construction. The original argv and boot
INFO are retained in [null geometry](docs/ccfix5/null-l1-geometry.json).

## B: pending-source construction

Investigation in progress. The fresh PRE and POST probes both open every MSET
window; the full-matrix replay retains pre/held INFO, key ownership before/after,
writer readiness and DEBUG LBSIGNALS if the window fails to open. No timeout
tolerance, skip or production change has been introduced.

## Audits and remaining proofs

The fresh merged audit reports 16,929/17,013 identical body occurrences,
1,207/1,213 handlers, and 1,495/1,496 selected hot bodies. The six handler
differences are CONFIG/INFO. The one selected ordinary difference is still
ccfix4's db0 `WbEngine::serve_impl<false,true,false,true,false,false>` lambda,
824→537 bytes. The strict audit exits 1; it is not described as a byte-equality
pass. All 84 changed occurrences are listed in the
[complete inventory with reasons](docs/ccfix5/changed-bodies-with-reasons.json).
The upstream cd13b composition changes some non-selected xshard helper bodies;
these are retained rather than suppressed.

Final armed matrix repetitions, split matrix, and the five instruction witnesses
are pending. No new claim overrides ccfix4's remaining hot-body/instruction
acceptance limitations.

Rows remain **+0 quick / +0 full**. `tests/gate.sh` is unmodified; EXPECT values
stay 500/517. Differential collections are at lines 3392 and 3403, both after
the quick-tier exit at line 3364. No row was added or retired and no count change
is requested.
