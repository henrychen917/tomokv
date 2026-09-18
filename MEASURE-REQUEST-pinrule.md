pinrule — mainline measurement request

Worktree: `/home/user/Projects/cx-pinrule`, branched from `cx-final` at
`115da1721`. Implementation: `533115fc0`; serverless controls: `a5151886e`.
No server, load generator, benchmark, or gate was run by this lane. The production
ledger is unchanged. Mainline must run the commands below during its bench phase.

`--pin` now runs the existing one-arm rate-saturation search, then qualifies its
floor with byte-identical A/B/B/A nulls and calls the existing ledger writer.
The rate-saturation rule, productive-role occupancy checks, connection totals,
and normal comparison thresholds are unchanged. Variance can only raise the
rate floor. Legacy `--calibrate` and imports remain rate-only workflows; their
entries do not claim variance qualification. Use `--pin` for this repin.

The noise limits are measured independently for each cell. After the rate floor
is found, collect exactly two pilot ABBA blocks at the highest allowed ladder
rung (16 with the command below). For rates A1, B1, B2, A2, compute:

```
d  = 100 * ((B1 - A1) + (B2 - A2)) / (A1 + A2)
sA = 200 * abs(A2 - A1) / (A1 + A2)
sB = 200 * abs(B2 - B1) / (B1 + B2)
D  = min(MAX_SPREAD, max(abs(d) across both pilots))
S  = max(sA, sB across both pilots)
```

`MAX_SPREAD` is the existing 2% instrument validity boundary, consistent with the
reported GET/SET nulls of roughly 1–2%. It caps the between-arm allowance; it is
not a new default noise floor. Below that cap, D comes entirely from this cell's
two pilots. S also comes entirely from this cell's pilots: a 4–5% within-arm span
and a ~1% paired error are different observations, as the MGET findings show.
These empirical spans are not confidence intervals or promises about future runs.

Freeze D and S, then test each rung beginning at the rate floor, in order through
`1,2,4,8,12,16`. Each rung gets exactly two fresh ABBA blocks. Both must satisfy
`abs(d) <= D`, `sA <= S`, and `sB <= S`, while retaining the normal null's live
quiet/workload/occupancy checks. No failed rung is retried; all observations stay
in the report. The pilot blocks cannot qualify the ceiling itself. An exhausted
ladder, invalid measurement, or failed later cell writes no entries. There is
no special case selecting 8 and no guarantee that 8 will pass on the next run.

This costs at most 14 ABBA blocks per cell (two pilots plus two blocks at each of
six rungs), or 1,120 seconds of central null windows, plus the original rate
search, population, warmup, and quiet screening. A floor of 1 raised to 8 takes
10 blocks per cell. The pilot overhead is deliberate independent calibration,
not another attempt at a failed rung.

The new `variance_pin` ledger field retains the saturation lower bound and its
confirmation, allowed ladder, binary digest, raw ABBA rates, busy/occupancy
samples, source-report digests, derived limits, every trial, and selected rung.
Import replays the full embedded rate and null reports; schema loading replays
the compact decision. An edited instance count, limits, unknown note field,
removed variance evidence, or changed selected observations is rejected. This
is consistency validation of measured evidence, not a cryptographic signature
against someone rewriting the complete evidence and provenance.

Run from the frozen instrument revision; do not edit harness code during or
after collection and expect the same instrument digest. The pinned server below
already exists and matches the ledger's reference binary:
`f8e53f984d7f46d96e7a388e71b260a6144f9c475f5100faf1be572a49f0708f`.
There is no C++ change, PRE/POST executable difference, or PAD arm in this lane.

Repin both cells together, using the harness's writer:

```bash
cd /home/user/Projects/cx-pinrule
python3 tests/abbagate.py --pin --subset full --only m03,m51 \
  --candidate-binary /home/user/Projects/bench-bins/tomokv-headline-84846e904 \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --ports 8700-8700 --max-instances 16 \
  --output build/pinrule-m03-m51
pinrule_rc=$?
if [ "$pinrule_rc" -ne 3 ]; then exit 1; fi
git diff -- tests/gate_measurements.json
```

Exit 3 here means both qualified entries were written and the report says PIN;
it deliberately cannot count as a code-comparison PASS. Exit 1 leaves the ledger
unchanged. The output directory must be new. Inspect a failed report before
planning another campaign; do not repeat a failed campaign until it turns green.
There is no separate import step and no hand-edit of `instances` or instrument
digests. Preserve `build/pinrule-m03-m51/` with its frozen binaries and raw reports.

Run the iteration gate after the repin:

```bash
tests/gate.sh iteration \
  --server-cores 0-87 --server-smt '' --load-cores 88-111 --load-smt '' \
  --ports 8700-8747 \
  --candidate-binary /home/user/Projects/bench-bins/tomokv-headline-84846e904 \
  --reference-binary /home/user/Projects/bench-bins/tomokv-headline-84846e904
```

The resource plan was checked without executing the gate: 11 correctness slots,
then ABBA server `0-31`, load `32-111`, no SMT, split `16:16`, matching the pins.
Correctness retains each battery's own eight-core/16-shard geometry. The harness
code change invalidates old instrument digests on other stored floors; those
cells may search again. Do not rewrite their digests to reuse old evidence.
Also, m03 and m51 are not in the iteration smoke subset, so the pin campaign
above is their direct qualification; the iteration gate checks integration.
The gate's ABBA tier is reporting-only in this base revision: correctness green
alone is not a measurement verdict.

For an independent check after selection, collect exactly two additional nulls
at the newly written pins, without `--escalate`:

```bash
for pinrule_repeat in 1 2; do
  python3 tests/abbagate.py --collect-null 1 --subset full --only m03,m51 \
    --candidate-binary /home/user/Projects/bench-bins/tomokv-headline-84846e904 \
    --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
    --ports 8700-8700 --max-instances 16 \
    --output "build/pinrule-validation-$pinrule_repeat"
  pinrule_rc=$?
  if [ "$pinrule_rc" -ne 3 ]; then exit 1; fi
done
```

Record their actual paired delta and both arm spreads, comparing them with the
frozen D/S limits; `null_control: PASS` by itself only certifies a valid null
measurement. A holdout outside the limits is contrary evidence, not permission
to widen D/S or hide a run. These holdouts do not write or change the pins.

Append `MEASURE-RESULT` with the selected instances, rate lower bound and
confirmation, pilot D/S, both nulls' delta/spreads at every tested rung, the
independent holdouts, gate result, and the ledger diff. Use this PRE/POST table:

| Cell | PRE ledger pin | PRE finding supplied by mainline | POST pin / nulls |
| --- | --- | --- | --- |
| m03, 1s MGET p32 | 1 | +0.4%, -7.6% paired at the old load; B span 4.8% | Pending mainline |
| m51, 2s MGET p32 | 1 | Prior 8-instance nulls -0.5%, +0.5% paired | Pending mainline |

The decision is the first rung at or above the measured saturation floor where
both fresh nulls pass the independently frozen paired-error and arm-span limits.
Report exhaustion as unresolved; do not manufacture a pin at the ceiling.

Serverless verification completed: `python3 tests/abbagate.py --self-test`
(95 ABBA + 10 saturation + 7 calibration controls) and
`python3 tests/gate_measurements.py --self-test` (11 controls), all passing.
New controls include actual mocked `--pin` dispatch through the atomic writer,
byte equality of both frozen arms, flat-rate noisy escalation, quiet retention,
bounded exhaustion, pilot/trial independence, frozen limits, and forged ledger
or source-report rejection without changing the prior ledger.

No gate row was added or removed. Both suites run inside the existing ABBA
negative-control row at gate.sh lines 2317–2327, before the quick-tier exit at
line 2764. Count delta: quick +0, full +0; EXPECT_QUICK remains 419 and
EXPECT_FULL remains 435. Neither constant nor tests/gate.sh was edited.
