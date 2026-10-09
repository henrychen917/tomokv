# mkprobe3 — measured null contract

Branch `cx-mkprobe`; code commits `dd3be703c`, `f72c0ea06` and `6e3862b52eb02bc3b993ce18a762fa36704bdc3e`. Gate rows **+0/+0**. No performance claim and no new measurement.

Initial and final synchronizations ran `git fetch origin` followed by `git merge origin/cpp`. The first fast-forwarded to `dab7409642bf0a6d125fb5f479e6d190c7636083`; the final merge was already up to date and preceded every final proof below. The only executable source changed is `tools/mkprobe_probe.py`, including its self-test. `src/`, `tests/`, `Makefile`, `tomokv.conf`, gate recipes and both expected gate counts have zero diff against merged mainline. No row was added or removed on either side of the quick-tier exit. No flags were added. No server, benchmark, load generator or gate was run; no build or PRE/POST/PAD binaries are needed for this analysis-only change. Nothing was pushed.

## Existing null: PASS without recollection

The command below exited 0 after the final merge. Inputs were read in place; output was written only in this worktree. All **168 rows are COMPLETE**, no sample is FAILED, every arm has n=6, and all **14 cells / 28 cell-metric comparisons PASS**. There are zero UNSTABLE cells. M1–M5 remain UNRESOLVED in this null-only report because their campaign observations have not been supplied, rather than because the null failed.

```sh
taskset -c 112-127 python3 tools/mkprobe_probe.py --mode report --inputs /home/user/Projects/cx-final/build/mkprobe-mainline/null --output build/mkprobe3-proof/null-report
```

| Same 168 observations | PRE | POST |
|---|---|---|
| Median agreement | Fixed ±0.15% | Per cell/metric, absolute delta <= 3 x measured SE |
| Same-arm spread | Fixed 2% pass/fail threshold | Recorded as that cell/metric's measured resolution |
| Null outcome | FAIL; 11 of 14 cells failed | PASS; 14 of 14 cells pass |
| Instability | Conflated with disagreement | Distinct UNSTABLE status; full table retained |

## Estimator declared in code and reports

`NULL_K = 3`. Let `sA` and `sB` be within-arm sample standard deviations (ddof=1), with observed counts `nA`, `nB`:

```text
pooled_sd^2 = ((nA-1)*sA^2 + (nB-1)*sB^2) / (nA+nB-2)
SE = sqrt(pi/2) * pooled_sd * sqrt(1/nA + 1/nB) / median(B)
delta = median(A)/median(B) - 1
median agreement iff abs(delta) <= 3*SE
measured_null_band = max(max(A)/min(A)-1, max(B)/min(B)-1)
```

This is the normal-reference approximation for the difference of two independent sample medians, expressed relative to median(B). `sqrt(pi/2) = 1.253314...`; both arms contribute sampling error. The within-arm pool excludes between-arm drift. It is an asymptotic SE estimate at the observed n, not an exact small-sample confidence guarantee. No spread clipping, fixed floor, outlier removal, retry, or sample filtering was introduced. The later effect intervals retain the existing deterministic 2,000-resample percentile bootstrap.

The prior observations are rejudged retrospectively as requested; the formula is now declared before further collection. Null agreement and resolution are separate quantities: passing the median test never turns a 16% observed repeat spread into sub-percent resolution.

### Sanity-cap provenance

The owner-specified caps are 6% for quiet cells and 20% for noisy/multi-key cells. They classify instability only; they never substitute for or clamp a measured acceptance band. A cell exceeding either metric's cap is UNSTABLE, its other measurements stay visible, the aggregate is UNSTABLE rather than FAIL, and dependent collection still requires aggregate PASS.

The cited source is `/home/user/Projects/calib/refnull-spread.py`, SHA256 `99450cc65daf60e7bb5ed0e2613d14d28aea597a7bba921b39941005507de07c`, reading `/home/user/Projects/endgame.log`. At this replay it contained **30** observations per generic cell, rather than the prompt's earlier 27. Captured output:

```text
same-binary null rows: 30
cell         n   mean%    sd% max|d|%  band beyond band
d1g_l0      30   +0.06   0.35    0.63   2.5 0
d1s_l0      30   -0.07   0.34    0.99   2.5 0
h05         30   -0.10   1.74    4.32   2.5 5
h06         30   +0.23   1.96    5.30   2.5 6
p8g         30   +0.04   0.95    2.02   2.5 0
p8s         30   -0.09   0.74    1.41   2.5 0
v1g_l0      30   -0.11   1.00    2.12   2.5 0
d128g_l0    30   +0.49   2.62    8.84   5.0 2
d32g_l1     30   -0.33   1.94    4.52   5.0 0
d32s_l1     30   -0.03   1.26    3.37   5.0 0
d8s_l1      30   -0.21   0.74    2.02   5.0 0
m8g_l0      30   +0.09   2.63    6.16   5.0 2
x9_32_l0    30   +0.32   2.16    5.54   5.0 1
x9_32_l1    30   +0.36   2.08    4.84   5.0 0
```

The script's quiet-class observed maximum is 5.30%; the noisy-class maximum is 8.84%. Those are single-block B/A deltas, not same-arm max/min ranges. The campaign's own multi-key range reaches 16.64%, below the owner's outward 20% guard. This distinction is why the generic table supplies sanity evidence only: the resolution used to judge each campaign cell comes from that cell's own observations. All twelve multi-key null cells use the noisy/multi-key cap; h05/h06 use the script's quiet class and its 6% cap. The table's old 2.5/5.0 bands are printed as source context and are not adopted by this tool.

## Recomputed per-cell table

| Cell | Metric | n A/B | A/B delta | SE median | k x SE (k=3) | Same-arm spread / measured band | Sanity cap | Verdict |
|---|---|---|---|---|---|---|---|---|
| m02 | rate | 6/6 | -0.836% | 2.194% | 6.583% | 8.748% | 20% | PASS |
| m02 | cyc_per_op | 6/6 | +0.879% | 2.246% | 6.739% | 8.740% | 20% | PASS |
| m03 | rate | 6/6 | -3.098% | 2.980% | 8.941% | 16.640% | 20% | PASS |
| m03 | cyc_per_op | 6/6 | +3.193% | 3.203% | 9.610% | 16.629% | 20% | PASS |
| m05 | rate | 6/6 | -0.239% | 0.611% | 1.834% | 2.866% | 20% | PASS |
| m05 | cyc_per_op | 6/6 | +0.239% | 0.618% | 1.855% | 2.869% | 20% | PASS |
| m06 | rate | 6/6 | +0.047% | 0.929% | 2.786% | 4.113% | 20% | PASS |
| m06 | cyc_per_op | 6/6 | -0.051% | 0.934% | 2.803% | 4.111% | 20% | PASS |
| m26 | rate | 6/6 | +0.291% | 0.502% | 1.506% | 1.851% | 20% | PASS |
| m26 | cyc_per_op | 6/6 | -0.288% | 0.500% | 1.501% | 1.850% | 20% | PASS |
| m27 | rate | 6/6 | -0.122% | 0.298% | 0.894% | 1.174% | 20% | PASS |
| m27 | cyc_per_op | 6/6 | +0.121% | 0.299% | 0.898% | 1.174% | 20% | PASS |
| m50 | rate | 6/6 | +0.227% | 1.264% | 3.793% | 5.598% | 20% | PASS |
| m50 | cyc_per_op | 6/6 | -0.231% | 1.219% | 3.657% | 5.592% | 20% | PASS |
| m51 | rate | 6/6 | -0.133% | 2.261% | 6.784% | 12.427% | 20% | PASS |
| m51 | cyc_per_op | 6/6 | +0.127% | 2.524% | 7.573% | 12.413% | 20% | PASS |
| m53 | rate | 6/6 | -0.020% | 0.147% | 0.442% | 0.699% | 20% | PASS |
| m53 | cyc_per_op | 6/6 | +0.086% | 0.255% | 0.766% | 1.028% | 20% | PASS |
| m54 | rate | 6/6 | -0.122% | 0.159% | 0.476% | 0.653% | 20% | PASS |
| m54 | cyc_per_op | 6/6 | +0.144% | 0.325% | 0.976% | 1.464% | 20% | PASS |
| m74 | rate | 6/6 | +0.157% | 0.421% | 1.264% | 1.914% | 20% | PASS |
| m74 | cyc_per_op | 6/6 | -0.152% | 0.419% | 1.256% | 1.916% | 20% | PASS |
| m75 | rate | 6/6 | -0.366% | 0.550% | 1.650% | 2.484% | 20% | PASS |
| m75 | cyc_per_op | 6/6 | +0.371% | 0.546% | 1.638% | 2.465% | 20% | PASS |
| h05 | rate | 6/6 | +1.126% | 1.097% | 3.292% | 5.200% | 6% | PASS |
| h05 | cyc_per_op | 6/6 | -1.115% | 1.101% | 3.302% | 5.199% | 6% | PASS |
| h06 | rate | 6/6 | -0.341% | 0.954% | 2.863% | 3.297% | 6% | PASS |
| h06 | cyc_per_op | 6/6 | +0.343% | 0.972% | 2.916% | 3.298% | 6% | PASS |

## Required n for 3% resolution

The multi-key p32 cells have a same-arm spread of 12-17% at n=6 on this box (rl0 MGET m03/m51); any multi-key claim below that needs more samples. m03: 16.64% rate spread, n=54 for rate / 62 for cycles/op; m51: 12.43% rate spread, n=32 for rate / 40 for cycles/op. These are equal per-arm n estimates for a 3% median-difference resolution (3 x SE <= 3%), rounded up for ABBA: n = 2 * ceil(max(6, 2*(3*sqrt(pi/2)*pooled_sd/(median(B)*0.03))^2)/2). This assumes independent stationary samples, not a power guarantee. Raw max/min spreads do not shrink as 1/sqrt(n); more samples must re-establish resolution and do not automatically waive the recorded band.

Thus planning for both reported metrics needs at least **62 samples per arm for m03** and **40 per arm for m51** under that model. These are total per-arm sample counts, not additional rows and not a guarantee that a 3% effect will pass a future verdict. Increasing the number of raw observations does not reduce a raw range; the recorded range remains the later verdict floor. A finer claim needs further evidence that establishes finer resolution, not a silently divided old band.

## Later verdict rules and their asymmetry

Directional effects confirm only when the whole bootstrap interval exceeds the measured band; an opposite effect beyond the band refutes; effects inside/overlapping the band are UNRESOLVED. Equivalence is asymmetric: an interval contained within the band confirms a null prediction, an interval entirely outside refutes, and boundary overlap is UNRESOLVED. M3 adds endpoint uncertainties after dividing cycles/op by key count and adds both depths' step bands. M5 importance is a separate minimum-effect prediction: its p32 share interval must exceed twice the measured cycles/op band (in percentage points); a whole interval below that threshold refutes resolvable importance, not nonzero cost; overlap is UNRESOLVED. Depth growth uses directional bands. Unrepresented p8/p128 controls use their own repeated unchanged baseline's spread, with source and n recorded; no cell borrows another cell's band. The retired/send [0.9,1.1] prediction describes batching semantics, not instrument resolution.

| Check | Measured band and rule |
|---|---|
| M1 multi-key wb0/wb1 equivalence | Separate rate and cycles/op null bands for that exact cell. Each complete bootstrap interval must fit inside its corresponding symmetric band to confirm equivalence; lying wholly outside refutes; crossing a boundary is UNRESOLVED. |
| M1 GET/SET policy loss | Rate loss and cycle cost each need their whole interval beyond their metric's band. The opposite direction beyond the band refutes. A flat or small in-band effect is UNRESOLVED. |
| M3 key-boundary steps | If `f` is that cell's measured cycles/op null fraction, the endpoint uncertainty at key count k is `f * median(cycles/op at k) / k`. Add the two absolute endpoint bands for each cycles/key step. The relative step band is that sum divided by the starting cycles/key median. |
| M3 p32 minus p8 growth | Add both depths' absolute step bands before comparing the difference of the steps. A directional effect must clear this sum. |
| M3 no extra positive 9→16 step | Upper interval <= propagated band confirms this bounded prediction; lower interval > band refutes; overlap is UNRESOLVED. |
| M5 importance | Shares are percentages of total cycles; p32's resolution threshold is `2 * 100 * measured cycles/op band` percentage points. Below/above/overlapping this minimum-effect criterion means REFUTED/eligible for confirmation/UNRESOLVED. Refuting resolvable importance does not assert zero cost. |
| M5 depth growth | Each adjacent share difference must clear `100 * (left cycle band + right cycle band)` percentage points. A resolved reversal refutes; in-band growth is UNRESOLVED. Unobserved p32 symbols remain unavailable, never evidence of zero cost. |

The frozen 14-cell null does not contain p8g/p8s or mk128g and contains no symbol pass. The predeclared fallback for these unrepresented controls is their own unchanged baseline repeats: WB1/B for p8g/p8s, and the core cycles/op observations in the base symbol runs for mk128g. These bands are derived during that baseline collection, not claimed to be pre-existing 14-cell null measurements; their source and n are printed. The policy intervention arm never sets its own tolerance, and no cell borrows another cell's band. Missing baseline samples or an unstable baseline leaves the mechanism UNRESOLVED. The 14-cell null must still pass before any dependent collection.

The [0.9,1.1] retired/send condition is retained as the original semantic prediction of approximately one reply per submission; it is not used as an instrument-noise allowance. M2/M4 remain attribution-limited and UNRESOLVED.

## Old-null provenance and dependent modes

Every `--null` dependency re-reads the receipt-bound rows and invokes the new `null_verdict`; it does not trust the old cached FAIL in `report.json`. The existing data's original canonical receipt SHA256 remains `135de5f2e43c6f4c1e63aa28dc11a902adc426b5aaacd2314fbccc707eaa5266`.

Changing an analysis-only function also changes the old whole-file instrument digest. Simply dropping the digest check would weaken provenance. The compatibility check instead verifies full source-map bindings, requires every other instrument source to match exactly, and compares the collection AST with the actual landed mkprobe2 source at `2c78708f8`. It excludes explicitly named analysis/report/self-test definitions and normalizes only the instrument-identity assertion itself. All acquisition code, constants, imports, parser options, commands and the rest of `run()` must remain identical. Unknown tool revisions and changes to any other source are refused; full original receipt/source hashes remain intact. Reports use the same check when reconciling old-null and new-campaign receipts.

The check against the actual existing null is **PASS**. The sole source difference is `tools/mkprobe_probe.py`. Both collection ASTs hash to `09b992d478db7d0dc6d7b8be3ae1ecc753c010b3d1c6dd65a382286227d7f32e`. The self-test independently rejects a changed collection window, changed workload source and unbound instrument digest. Binary, geometry, PMU, environment, placement, resume, chronology, quiet, saturation and sample-count requirements remain in force.

## Final self-test

After the final merge, exit 0:

```sh
taskset -c 112-127 python3 tools/mkprobe_probe.py --self-test
```

```json
{
  "status": "PASS",
  "checks": [
    "canonical recipes and 14-cell null",
    "all headline/mkprobe complete argv byte-identity plus 14 override round trips",
    "invalid key counts fail",
    "PMU partial, multiplexed, missing, duplicate and unavailable negative controls",
    "cycles/op, instructions/op, IPC and cycles/key independent arithmetic",
    "shutdown accounting and duplicate report negatives",
    "armed INFO flip_auto=1: advancing positive samples pass; zero/stale counts and zero values fail",
    "disarmed INFO flip_auto=0: NA with reason; missing/invalid/changing state fails",
    "1s unavailable and missing-counter negatives",
    "weighted symbol shares and lost-sample negative",
    "all eight collection-mode matrices and ABBA per-arm n=6",
    "measured null: identical medians with known spread PASS; >3 x SE rate/cycle shifts FAIL; quiet/multi-key UNSTABLE; n=5/empty UNRESOLVED",
    "M1/M3/M5 CONFIRMED/REFUTED from fixture-owned spread; flat directional effects UNRESOLVED; key-division propagation; missing variants/attribution",
    "mkprobe2 null reuse proves identical collection AST; changed windows/workloads and unbound digests rejected",
    "resume serialization identity and changed-geometry negative control",
    "Markdown/JSON report includes per-metric null table, M1/M3/M5 bands and baseline provenance",
    "owned child process-group stop and reap (CPU112, no listener)",
    "quiet refusal retained without starting a server",
    "disarmed 2s fixture: COMPLETE row and Markdown/JSON reports retain NA reason (no server)"
  ],
  "server_started": false
}
```

The fixtures use six repeats with factors `[0.998, 0.999, 1, 1, 1.001, 1.002]`: identical medians but nonzero known spread. They test rate-only and cycles-only shifts at **3.01 x SE**, and the exact **3 x SE** inclusive boundary separately: exact equality must pass under the requested `<=` rule, while just beyond it fails. They also test quiet and multi-key UNSTABLE cases, n=5, zero-spread/no-floor behavior, scale invariance, key-division propagation, incomplete attribution, and unequal key-sweep depth counts (which must not silently discard samples). Increasing only the calibration spread changes otherwise identical M1/M3/M5 outcomes, demonstrating that the verdicts actually read measured bands. Negative directional fixtures reverse effects beyond the band; flat effects now remain UNRESOLVED.

The child-lifecycle fixture starts and immediately reaps a sleeping Python process with no listener. All server/load collection in row/report fixtures is mocked; no server or benchmark is started.

## Frozen headline argv and scope

The final proof re-ran `argv_proof(arguments(["--mode", "report"]))` after the final merge, in addition to the copy inside `--self-test`. It compared **1656 complete execve vectors**, covering 181 frozen headline cells and all 19 probe cells, with UTF-8 arguments separated and terminated by NUL. All fourteen MGET/MSET override round trips pass and restore the unset environment.

```text
frozen revision:       65a9d0a22
headline SHA256:       d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350
frozen workload SHA:   0060d75451b97c4274600eefcd8c950e0683359b31df910233d5e60765e15ce9
byte-identical argv:   e90f50fe6363bf7d44a3b7eb168641736ad3e6c6f9f0e6fe9c3d63b3b4c5facc
final tool SHA256:     0ff75f47dd5cf382a3c0c74dde1e64361ef472816ae7371b954ce8ff90323d9f
old instrument SHA:    349fbe5ce79eda3178941963f4ac85b65221a88efbf63473d09da610ede537a1
new instrument SHA:    767131d3d29af3782e6a592b78fd1faa40046ff080182f1b27011abdd9be1b5e
```

`git diff origin/cpp -- src tests Makefile tomokv.conf` is empty; `git diff --check` passes. The source and self-test are in one feature file. The only additional tracked file for this lane is this requested report. Gate counts stay unchanged: **+0 quick / +0 full**.

## Text audit and receipts

Used `grep`, never `rg`, across `tests/` and `tools/`. The audit covers underscore/space/hyphen names; decimal and exponent encodings of the former fractional tolerances; ±/percent prose; same-arm range/spread; frozen box/repeatability language; the old 0.3% importance criterion; SE names; and propagated/importance bands. The initial audit retained 31 matching lines; the expanded final audit retained 106. Other matches concern unrelated gate instruments, quiet CPU budgets, scheduling intervals or historical fixtures; those are unchanged. `BOX_BAND` and `REPEAT_BAND` survive solely as strings identifying the old definitions for the AST compatibility comparison, with no executable definitions or verdict uses. The old fixed-band report and fixture prose are gone from this tool.

All complete local receipts are under `build/mkprobe3-proof/`; this report embeds the full per-cell table, calibration source table and self-test output so the review does not depend on ignored build artifacts.

| Local receipt | SHA256 |
|---|---|
| `self-test.json` | `524772d258d239cb64273e5242d41829a4de572e155dc0bd8690f42d368f8a32` |
| `default-argv.json` | `a75197fd18507f12457e98d7cfc1101ab784d24d45a378dbdf2478bcd829e46a` |
| `scope-proof.json` | `65f5d53f77beb746619d76a5b8329a8a92c023265a1a6522fc0fd65e1e45a1e6` |
| `null-report/report.json` | `4c874269d653e90e4a120cc59d6408450d3bd115fa81140beefc5f14fa795207` |
| `null-report/report.md` | `3050395692a1f62d1c71c074f70f28979f6d9e8ac285fc4e56ec611b5973d766` |
| `refnull-spread.txt` | `2224147602d52559010f6f4a5b1018a4eced7f412efadf7d7405140126e48933` |
| `text-encodings-before.log` | `3b7635c98fb82a4c0d5a90589f0ad9ae2c5df11d0478495e55d0d82f00c7cd1e` |
| `text-encodings-final.log` | `51dd8485b1fca605779ebbac673a67002d56fd70d777c08bc58a102f1cbd7e3f` |
