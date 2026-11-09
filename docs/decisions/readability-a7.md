# Controller decisions preserved during readability-a7

Entries are dated by this documentation pass (2026-11-08). Quoted passages are inherited source comments from `7595a6705a`, not new measurements or independently verified results. Original dates, when present, remain in the quotes. The production comments state the current behavior; these entries retain the rationale and history removed from them.

## 2026-11-08 — 1. FlipFingerprintWriter::finish_parse_pass / FlipController::tick

Source: `src/core/flipctl.h`, `FlipFingerprintWriter::finish_parse_pass / FlipController::tick`. Preserved source rationale:

> flipctl.h -- allocation-free IO fingerprints and the single-owner FLIP controller.
>
> The writer is embedded in ThreadCtx, but only that physical thread mutates it while playing the
> IO role.  The monitor/controller reads completed cumulative windows; no per-operation atomic or
> shared-line write is introduced.  FlipController itself is written only by the main monitor
> thread.  INFO/DEBUG take its cold mutex and DEBUG's forced trigger is a single cold atomic flag.

## 2026-11-08 — 2. flip_fingerprint_window

Source: `src/core/flipctl.h`, `flip_fingerprint_window`. Preserved source rationale:

> Preserve the measured sampler: one whole parse pass in 100 on average. At a matched 512k ops/s,
> a GET-only -> SET-only swap triggered the fingerprint detector once with both exhaustive and
> 1-in-100 sampling; the sampled writer still detected the shift with the rate held fixed.
> Arming derives solely from the controller latch. No runtime sampling knob or adaptive
> per-operation work is needed; the detector already derives its bands from actual samples.

## 2026-11-08 — 3. FlipFingerprintWriter

Source: `src/core/flipctl.h`, `FlipFingerprintWriter`. Preserved source rationale:

> SAMPLED BY PARSE PASS. A per-op countdown would restore the store this sampler removes: no
> existing io-side command counter covers both the point paths and all io-local commands.
> The io loop asks pass_sampled() once per dispatched frame -- one load of this writer's own word,
> on the line the old enabled() test already read, and one predicted-false branch; no store.
> Inside a sampled pass the full fingerprint body runs
> for every frame and note_command accumulates exactly what the exhaustive writer accumulated for
> that pass; at the pass end finish_parse_pass() publishes it and the caller draws the gap to the
> next sampled pass. `work_window_` is the mean commands per fingerprint
> sample: one pass in W is sampled, so one frame in W is fingerprinted at every pipeline depth (a
> sampled pass contributes all of its d frames and costs the body d times, once per W passes).
> Gaps are uniform over [1, 2W-1] passes (mean W). A stride of exactly W would alias with any
> workload whose classes alternate with a period dividing W (memtier's 1:1 ratio is period 2);
> a uniform gap has 1 in its support, so the renewal process equidistributes over every period and
> each class is sampled in proportion. The draw is the io loop's own xorshift, taken only when a
> sampled pass ends, so the writer holds no generator state and the ThreadCtx footprint is
> unchanged (pass_frames_ became pass_countdown_; partial_.commands is the sampled pass's depth).
> W = 1 samples every pass: the exhaustive writer, byte for byte, and the unit test's oracle.
> Dark writer (work_window_ == 0: --flip-auto 0, every 1s boot): pass_countdown_ is 1 and nothing
> ever writes it, so the gate word reads false from a clean line and no other code runs.

## 2026-11-08 — 4. flip_signature_distance

Source: `src/core/flipctl.h`, `flip_signature_distance`. Preserved source rationale:

> The workload-mix distance. It deliberately EXCLUDES pass_depth: parse-pass occupancy is an
> arrival-batching observation the controller's own actuator moves (a measured io 5->7 step moved
> it by 0.048 while the mix families moved by 4e-7), and the sweep-abandon law says a signal the
> actuator moves cannot police the actuator. pass_depth stays measured, published and dumped for
> diagnosis; it is simply not trigger evidence.

## 2026-11-08 — 5. FlipctlReport

Source: `src/core/flipctl.h`, `FlipctlReport`. Preserved source rationale:

> Redesign 2026-09-06: the decision the model last took, its calibration and outcome record,
> and the measured transfer cost the gate charges.

## 2026-11-08 — 6. FlipController::begin_refinement

Source: `src/core/flipctl.h`, `FlipController::begin_refinement`. Preserved source rationale:

> REFINEMENT. A projection from the origin's demand reading is only as good as the assumption
> that per-command io and ex costs are the same at the target as at the origin; they are not
> (the io side batches better with fewer threads), so a one-shot argmax from an io-heavy origin
> lands short -- measured on the owner's box: 18:14 -> 13:19 settled 8% below 11:21. After a
> DELIVERED move the maneuver therefore re-measures the local demand at the landing and takes
> one more outcome-judged step while the local argmax differs from the live split and pays
> (measured transfer cost now), stopping at the fixed point where the landing IS its own
> argmax, or at a split already visited this maneuver. The departure split of the current
> hypothesis is seek_origin_io_ (a miss returns there); maneuver_origin_io_ stays the split the
> maneuver started from (the null-maneuver rule).

## 2026-11-08 — 7. FlipController::baseline_band

Source: `src/core/flipctl.h`, `FlipController::baseline_band`. Preserved source rationale:

> The ORIGIN's stabilized readings while the model was deciding (Measuring never moves the
> split): their mean is R0, their relative stdev is the noise the verification window is sized
> from, and their bracket (min/max) floors every band of the maneuver -- a gain smaller than
> the baseline's own movement is the baseline moving, which is how the gate's ramping driver
> once anchored a boot maneuver on a rail.

## 2026-11-08 — 8. Sequential demand window — flip_choose_split

Source: `src/core/flip_policy.h`, `flip_choose_split`. Preserved source rationale:

> flip_policy.h -- the FLIP controller's placement POLICY: when a role move is worth making.
>
> Pure arithmetic, no Server, so tests/flipctl_unit.cc can run it against scripted numbers. The
> controller (flipctl.cc) feeds it one demand observation per stabilized throughput reading and
> asks one question: is there a split whose PROJECTED gain over the live split clears the
> evidence bar? Three rules, one invariant -- a move must be able to pay for itself:
>
>
> 1. WINDOW + VARIANCE. One demand draw is not an estimate. Observations accumulate (Welford)
> and every projection is evaluated across the window's own confidence interval; the
> decision is SEQUENTIAL: move as soon as the pessimistic end of the interval clears the bar,
> hold as soon as the optimistic end cannot, keep sampling in between. Accuracy comes from
> the window, never from a denser sample (user-lb-never-inhibits-hot-path). The server keeps
> serving at its current split for as long as that takes; sampling costs no throughput.
>

## 2026-11-08 — 9. Projected split cost — flip_choose_split

Source: `src/core/flip_policy.h`, `flip_choose_split / flip_projected_rate`. Preserved source rationale:

> 2. COST GATE, in throughput space. The old jump rounded N * io_frac to a thread count and
> overshot it. Measured on 8-key MGET/MSET at 5:3 (8 threads) with the estimator then in
> use (io 82%): round(8 * 0.82) = 7, overshoot to 8 clamped 7 -- a split this very model
> rates at 0.69x the origin (ex, 1 of 8 threads, carries 18% of the work and saturates
> first). The gate evaluates every split under work conservation,
> R(s) ~ min(s / f, (N - s) / (1 - f)),   f = io share of busy time,
> picks the argmax, and moves only if its gain over the live split -- at the PESSIMISTIC end
> of the window's interval -- exceeds the required gain. The required gain is the
> controller's own throughput noise band (a gain the seek could not verify cannot pay for
> the flip it costs) scaled by the outcome margin below. No machine constants: N is the live
> pool, f and its interval are measured, the band is learned.
>

## 2026-11-08 — 10. Outcome margin — FlipController::seek_after_reading

Source: `src/core/flip_policy.h`, `FlipController::seek_after_reading / flip_judge`. Preserved source rationale:

> 3. OUTCOME LOOP. After the jump the controller measures the target against the origin's
> stabilized rate; not better by the band => straight back to the origin, and the margin the
> model must clear next time doubles (a projection that did not deliver was wrong about
> the WORKLOAD, and more samples of a biased estimator only make it more confidently wrong
> -- the bar has to rise, not the window). A move that delivered halves the margin back
> toward one band. The margin is capped where required gain would exceed 100%: past that
> the model could never fire again on any workload, which is a silent `--flip-auto 0`.
>

## 2026-11-08 — 11. Wall-minus-idle demand — flip_role_work

Source: `src/core/flip_policy.h`, `flip_role_work / FlipController::sample_role_demand`. Preserved source rationale:

> REVISION 2026-09-06 (the actuator redesign). The three rules above were the placement policy's
> first cut; this revision gives each of them the quantity it was missing, in units:
>
>
> SIGNAL. Role demand is measured as WORK = wall - idle per thread (flip_role_work), not as the
> loops' busy_ns. In that 2026-09-06 measurement the io loop closed its busy span
> before ring_.submit_and_reap(), so the
> io_uring_enter syscall -- the kernel moving the bytes, which is io work -- was booked as
> neither busy nor idle: 23.5 s of a 40 s window on one single-key io thread. The busy share
> read io = 0.32 on a workload whose work share is 0.51, and the model moved 2:2 -> 1:3
> (measured -52%) and came back. IO tenure accounting now includes that gap; the model remains wall-minus-idle.
> The inherited measurement above is not a result of the accounting cleanup.
>

## 2026-11-08 — 12. Stationary-horizon cost — flip_cost_gate

Source: `src/core/flip_policy.h`, `flip_cost_gate`. Preserved source rationale:

> COST GATE, in commands over the horizon the workload has demonstrated (flip_cost_gate). A move
> must pay for itself: kappa g_low R0 (T_stat - T_black) > margin [C_xfer (1 + P_miss) +
> P_miss kappa g_mean R0 T_black]. T_stat is how long the workload has held still, T_black
> how long the controller is blind after the flip (flip + settle + planned readings), C_xfer
> = measured commands lost per transferred client x predicted transfers, P_miss the model's
> own miss rate (Laplace). First flip: the transfer cost is unknown and stays zero -- that
> flip is the measurement.
>

## 2026-11-08 — 13. Variance-sized verification — flip_verify_window

Source: `src/core/flip_policy.h`, `flip_verify_window / flip_verify_threshold`. Preserved source rationale:

> WINDOW FROM VARIANCE (flip_verify_window / flip_verify_threshold). The post-move window is as
> long as the origin's own noise says it has to be to resolve the predicted gain at two
> standard errors, and no longer; verification is sequential (accept early, reject early).
>

## 2026-11-08 — 14. Magnitude calibration — FlipCostModel::record_outcome

Source: `src/core/flip_policy.h`, `FlipCostModel::record_outcome / FlipCostModel::kappa`. Preserved source rationale:

> OUTCOME LOOP (FlipCostModel::record_outcome). Every move is a hypothesis with a predicted
> delta. A miss reverts and doubles the margin (sign); kappa = (sum delivered + gbar) /
> (sum predicted + gbar) learns the model's MAGNITUDE bias with the credence of one delivered
> move of average size as its only prior, and never exceeds one.

## 2026-11-08 — 15. flip_role_work

Source: `src/core/flip_policy.h`, `flip_role_work`. Preserved source rationale:

> ---- REVISION 2026-09-06: signal, cost gate, verification window, outcome ---------------------

## 2026-11-08 — 16. FlipEwVariance

Source: `src/core/flip_policy.h`, `FlipEwVariance`. Preserved source rationale:

> The load's own variability over the LONGEST window the controller has, DETRENDED: an
> exponentially weighted variance of the SECOND relative difference of every per-tick rate sample,
> rel2 = (r_t - 2 r_{t-1} + r_{t-2}) / r_{t-1}.
> Every other band in the controller is learned from stabilized PAIRS -- readings the controller
> selected because two adjacent sub-windows agreed -- and that selection is biased quiet: two
> readings taken inside one phase of a driver's six-second rate triangle read sigma = 0.05% on a
> load that swings +-20%, the target's +24% (the swing, not the flip) cleared every band, and the
> boot maneuver anchored on a rail; a settle window that happened to be still learned an anchor
> band of 0.02% and then fired four maneuvers on a stationary load. This estimator sees every tick,
> quiet or not. It is the SECOND difference because the first attempt -- deviation from an EW mean --
> blew up on the boot ramp (a near-idle first sample followed by the full rate read +12400% and the
> 1/30 decay kept it alive for 130 ticks: sigma 16.9, every band dead): a linear ramp has zero second
> difference, a level shift leaves two blips that decay, a periodic swing keeps its full amplitude.
> Samples at or below the idle floor are not evidence and break the chain; a second difference
> beyond 100% is a level change, not noise, and resets the estimator. The time constant is the boot
> deferral bound in ticks -- the one wall-clock allowance the controller already grants -- with a
> plain running average over the warm-up so one early blip is diluted, not remembered. The
> controller also resets it when a flip it issued completes: the level moved by design.

## 2026-11-08 — 17. FlipEwVariance::sigma

Source: `src/core/flip_policy.h`, `FlipEwVariance::sigma`. Preserved source rationale:

> The rms second difference, reported AS the per-reading noise scale. For white noise that
> overstates sigma by sqrt(6) -- conservative; for a swing of a few ticks' period it is right
> (the six-second triangle: 0.15 both ways), and that swing is what the pair bands were blind
> to. Dividing by sqrt(6) would be exact for white noise and read the triangle at 0.06.

## 2026-11-08 — 18. FlipEwBound

Source: `src/core/flip_policy.h`, `FlipEwBound`. Preserved source rationale:

> A one-sided noise bound for a NON-NEGATIVE observation (a distance): exponentially weighted mean
> and variance, reported as mean + 2 sd. Used for the fingerprint's adjacent-window movement, where
> the rate's second-difference estimator does not apply -- a distance has no trend to remove, it is
> already a difference, and it cannot go below zero.

## 2026-11-08 — 19. FlipEwBound::bound

Source: `src/core/flip_policy.h`, `FlipEwBound::bound`. Preserved source rationale:

> A DECAYING MAXIMUM, not a quantile. The observation this bounds (a signature's distance from
> its anchor) is AUTOCORRELATED -- the smoothed signature random-walks around the anchor -- so
> its excursions CLUSTER, and a mean + 2 sd quantile is exceeded on consecutive windows far more
> often than independence would predict: measured on a simulated 1-in-100 sampled stream, a
> mean+2sd bound still produced three two-consecutive exceedances in 600 stationary windows,
> which is a spurious maneuver. The band must cover the SUSTAINED excursion, so it retains the
> largest value seen and decays toward the mean -- the same "quiet jitter is a band, not a trend
> estimate" convention the signature's own jitter_ already uses. It settles just above the true
> running maximum and falls back if the signal genuinely quietens.

## 2026-11-08 — 20. flip_corrected_gain

Source: `src/core/flip_policy.h`, `flip_corrected_gain`. Preserved source rationale:

> A target's delivered gain re-expressed against the origin as it reads AFTER the return flip,
> when the baseline itself moved by `baseline_shift` during the excursion. A miss is voided
> (invalidated, not refuted) only when this corrected gain would have cleared the threshold: the
> question is not whether the baseline wobbled but whether the wobble would have changed the
> verdict. Measured: a closed-loop driver came back 2.2% faster after a round trip whose target
> had delivered -48%; (1 - 0.48) / 1.022 - 1 is still -49%, and that miss stands.

## 2026-11-08 — 21. flip_refine_bar

Source: `src/core/flip_policy.h`, `flip_refine_bar`. Preserved source rationale:

> The bar a REFINEMENT step must clear beyond the noise bar: the model's error just demonstrated on
> this workload, predicted minus delivered of the step that landed here (zero when it delivered at
> least what it promised). Work conservation is a V with its point at the optimum and the real
> curve is rounded there (owner box, 64-shard multi-key: 13:19 -> 11:21 is +2.5%, the model says
> +10%; past it 10:22 is -6.6%), so a projection smaller than the error the model has just shown
> is not evidence of a gain, and a chain that respected only the noise bar would round-trip in the
> flat region or cross the peak. Stopping short costs 2.5%; crossing costs 6.6% and up. No
> constant: the bar is the outcome record.

## 2026-11-08 — 22. ctlfix_correctness

Source: `src/core/flipctl.cc`, `ctlfix_correctness`. Preserved source rationale:

> Offline PAD-A patch point. Production always takes the corrected controller;
> the behaviour twin changes this return byte only, retaining POST text/layout.
> No configuration or command can select the legacy branch.

## 2026-11-08 — 23. flip_signature_distance

Source: `src/core/flipctl.cc`, `flip_signature_distance`. Preserved source rationale:

> pass_depth is NOT here. Measured on the multi-key regime this defect was found in: one
> controller step from io=5 to io=7 moved the pass-depth distance by 0.0476 -- eight to forty
> times its own learned trigger band -- while the three mix families moved by 4.2e-7, 0 and
> 5.4e-7 across the same seconds. Parse-pass occupancy describes how the io threads happened
> to batch arrivals, which is exactly what the actuator changes when it moves connections
> between owners. Judging placement with it is the sweep-abandon livelock: the controller
> re-fires on its own last move. Pipeline-depth changes that matter still reach the controller
> through the rate detector, which owns volume.

## 2026-11-08 — 24. FlipShiftDetector::update_band

Source: `src/core/flipctl.cc`, `FlipShiftDetector::update_band`. Preserved source rationale:

> SAMPLING SCALE, not counting resolution. Every family in the distance is a proportion or a
> per-command mean estimated from the N commands this window observed, so two windows drawn
> from one stationary workload differ by the ESTIMATOR'S OWN NOISE, which falls as 1/sqrt(N)
> -- never as 1/N. A Bernoulli proportion's standard error is at most 0.5/sqrt(N) and the
> difference of two independent estimates at most sqrt(2) of that, so 1/sqrt(N) bounds the
> per-family noise with room for the few terms an L1 sums. The old 1/N quantum understated it
> by sqrt(N) -- twentyfold at 13.5k commands a window -- which is how a window that merely
> drew 60 MSETs where the last one drew 50 could read as a workload change. A window that
> observed no commands supplies no evidence: saturate at one command (quantum 1.0) instead of
> collapsing to zero, or an anchor cut from an idle window freezes a zero band and judges the
> first busy wobble as a mix shift. Rate triggers, not fingerprints, own idle->busy.
>
> N IS WHAT THE SIGNATURE WAS ESTIMATED FROM, so when the writer samples the request stream the
> quantum grows with the sampling: at one command in a hundred a 100-command window resolves
> the mix to about 0.1, not to the 0.009 the underlying 10k commands would give.

## 2026-11-08 — 25. FlipShiftDetector::update_band

Source: `src/core/flipctl.cc`, `FlipShiftDetector::update_band`. Preserved source rationale:

> A TYPED BAND IS A FLOOR, NOT A CEILING, AND IT CANNOT BUY RESOLUTION THE SIGNAL HAS NOT GOT.
> The internal detector's explicit-band unit-test control sets the mix change worth a maneuver;
> it says nothing about how
> still the signature holds, and it used to return here consulting neither the estimator's
> resolution nor the signal's measured movement. Measured by the gate-hygiene lane on a driver
> whose rate held to 0.07% across 34 samples: a fingerprint distance of 0.2518 against a flat
> 0.0200 band -- 12.6x -- fired a maneuver on a stationary load. Simulated here on a 1-in-100
> sampled stream, a typed 2% band produced three two-consecutive exceedances in 600 stationary
> windows (a spurious maneuver each); with the quantum applied it produces none, and a real mix
> change still clears the band by 3.3x. So both branches take the same two floors.

## 2026-11-08 — 26. FlipShiftDetector::update_band

Source: `src/core/flipctl.cc`, `FlipShiftDetector::update_band`. Preserved source rationale:

> ... and the learned band adds the frozen learning-window jitter, floored the same way: that
> jitter is the largest adjacent step seen in the few windows before the anchor, so a learning
> window that happened to be still freezes a band the hold then trips over.

## 2026-11-08 — 27. FlipShiftDetector::observe

Source: `src/core/flipctl.cc`, `FlipShiftDetector::observe`. Preserved source rationale:

> LEARN THE STATISTIC THAT IS ACTUALLY TESTED. The trigger compares the distance from the
> ANCHOR; the adjacent-window distance is a different quantity -- smoothed and correlated,
> so systematically smaller -- and flooring an anchor-distance test with it underestimates.
> Measured on a simulated 1-in-100 sampled stream: adjacent-learned bound 0.054 against a
> quiet-state anchor distance reaching 0.101, which fired 15 times in 60 stationary windows.
> So the noise estimate is the anchored distance's own null distribution.
>
> JUDGE FIRST, FOLD ONLY IN-BAND WINDOWS. An excursion must never widen the threshold that
> judges it -- that is why this branch froze the band originally, and it stands. Folding
> every window instead cost exactly that: with the decaying maximum below, the FIRST window
> of a real mix change lifted the band to the excursion's own size, so the second window was
> judged against a band that had already absorbed it and the change never cleared its band
> (tests/flip_multikey_hold.py positive phase, reached 0.80x). A window that came back IN
> band is quiet-state evidence and is safe to learn from; one that did not is the thing
> under test. The estimate cannot get stuck too small, because the quantum below floors the
> band at the estimator's own resolution without needing any observation at all.

## 2026-11-08 — 28. FlipController::stabilize_rate

Source: `src/core/flipctl.cc`, `FlipController::stabilize_rate`. Preserved source rationale:

> A pair is "stable" relative to how the load itself moves tick to tick, never to a band a
> lucky settle window learned below that (0.02% measured: no pair ever fit and Measuring stuck).

## 2026-11-08 — 29. FlipController::issue_flip

Source: `src/core/flipctl.cc`, `FlipController::issue_flip`. Preserved source rationale:

> A flip onto the live split is a no-op that flip_begin nevertheless counts as completed, and
> issue_flip would then report failure because the stage never left Idle -- an ownership
> transaction in the counters that the controller does not believe it made. The seek arithmetic
> does not produce one today (every wall case reverses direction first), so this is a guard,
> not the cause of the multi-key thrash; but the controller must be structurally incapable of
> spending a FLIP on the split it is already running.

## 2026-11-08 — 30. FlipController::sample_role_demand

Source: `src/core/flipctl.cc`, `FlipController::sample_role_demand`. Preserved source rationale:

> One windowed observation of how the two roles split the server's real work, plus each role's
> HEADROOM: the idle share of its busiest thread. Returns false while the window carries no
> evidence; the caller keeps measuring rather than inventing a prior.
>
> WORK IS WALL MINUS IDLE. Historical evidence (2026-09-06): the io loop closed
> its busy span before ring_.submit_and_reap(), so the io_uring_enter syscall -- the kernel
> moving the bytes, which is io work -- was booked as neither busy nor idle. Measured on the
> guard's own snapshots (single-key 1:1, 40 s): one io thread booked 16.4 s busy + 0.2 s idle of
> 39.9 s on-CPU, 23.5 s unbooked; the busy share read io = 0.32 on a workload whose work share is
> 0.51, and the model moved 2:2 -> 1:3 (measured -52%) and came back. idle_ns is the quantity both
> loops book faithfully: the io loop's blocked wait after an empty sweep, the ex loop's empty
> passes and blocked wait (ex_loop.h). The wall is the controller's own tick clock, the same for
> every thread of the window, so nothing new is read on the hot path. IO tenure accounting
> now includes submit/reap; this model deliberately remains wall-minus-idle. The historical
> numbers were not reproduced by that cleanup. IO idle still includes epoll callbacks and
> park publication/resumption, not merely the blocking syscall.

## 2026-11-08 — 31. FlipController::sample_role_demand

Source: `src/core/flipctl.cc`, `FlipController::sample_role_demand`. Preserved source rationale:

> WORK CONSERVATION, WITH BOTH OPERANDS THE SAME QUANTITY. The throughput-optimal split gives
> each role the thread fraction its PER-COMMAND service cost demands,
> n_io* / N = c_io / (c_io + c_ex),   c_role = (work ns that role spent) / (commands run),
> and the command count is the same divisor on both sides, so it cancels: the estimator is the
> work-time share, and it never has to name what an "op" is. (It used to divide each role's
> busy time by that role's OWN op counter; the ex loop counts one op per SHARD TASK, 7.576 per
> MGET8 command, so ex looked cheap and the model wanted io = 82% -- the 5:3 -> 7:1 -> 5:3
> round trip the operator saw as three flips and 993 moved connections.)

## 2026-11-08 — 32. FlipController::decide_placement

Source: `src/core/flipctl.cc`, `FlipController::decide_placement`. Preserved source rationale:

> The Measuring phase (flip_policy.h): one demand draw per stabilized reading into the policy
> window, then decide or keep measuring. The server serves at its live split throughout, so time
> spent here costs nothing but the maneuver's own sampling arm -- which is why every "not yet" below
> is a return to sampling, not a hold: the interval tightens, the origin's noise estimate firms up,
> and the stationarity horizon the cost gate credits grows, all for free.

## 2026-11-08 — 33. FlipController::decide_placement

Source: `src/core/flipctl.cc`, `FlipController::decide_placement`. Preserved source rationale:

> SATURATION GATE. The capacity model above is a statement about CPU-bound roles: throughput
> ~ min(io capacity, ex capacity) holds only while one role's busiest thread has no headroom.
> When BOTH roles idle more than the noise band, the rate is set by something the split does
> not touch -- a paced driver, the network, or the closed loop's own wake-up latency (measured
> here: memtier at 27% of its cores, io 86% / ex 93% busy, and neither side waiting on the
> other's capacity) -- and a flip can only cost. Read from the idle_ns the loops already
> account, once per reading, off the hot path. A forced seek is exempt: it is a directed test.

## 2026-11-08 — 34. FlipController::decide_placement

Source: `src/core/flipctl.cc`, `FlipController::decide_placement`. Preserved source rationale:

> A BAR LARGER THAN ANY AVAILABLE GAIN IS A MEASUREMENT VERDICT, NOT A PLACEMENT ONE. When the
> model has picked a target and the only thing refusing it is the throughput bar, anchoring here
> records "this split is fine" on the strength of noise. Measured: a 3:1 boot whose executors
> were pinned (headroom_ex 0.0004, headroom_io 0.699) and whose demand interval was tight
> (0.395-0.424) projected the +100% move that 3:1 -> 2:2 is, and was refused because a
> neighbouring lane swung the box 2.8x per second, lifting the verification band past 1.0 --
> where min(1.0, band x margin) caps it exactly on the gain. Sampling costs nothing and the box
> may quieten, so keep measuring until the reading cap and let the cap deliver the honest
> "too noisy to decide" hold. The live split is the optimum is a different verdict and still
> decides immediately.

## 2026-11-08 — 35. FlipController::seek_after_reading

Source: `src/core/flipctl.cc`, `FlipController::seek_after_reading`. Preserved source rationale:

> The Seeking phase: stabilized readings at the model's target, judged SEQUENTIALLY against the
> origin's window. The hypothesis planned n_t readings from the origin's noise; after each one the
> target's mean is compared at two standard errors of the difference (never below the origin's
> own bracket or the learned band). Better => anchor here, early if the evidence is already in.
> Clearly worse => straight back at once: no sitting at a split the model already lost on. At the
> planned count, not better => back to the origin, where anchor() books the miss and raises the
> bar. No walk, no overshoot: every extra visit is a flip plus a window at a split the model rated
> lower, and that walk is what cost 19.5% on multi-key with the target unchanged.

## 2026-11-08 — 36. FlipController::anchor

Source: `src/core/flipctl.cc`, `FlipController::anchor`. Preserved source rationale:

> THE NULL-MANEUVER RULE, CLOSED ON THE OUTCOME. A maneuver that ends on the split it started
> from moved ownership, paid every quiesce and changed nothing -- thrash by this project's own
> definition. The trigger that started it was therefore not wrong about the workload, it was
> wrong that the workload's move was worth a maneuver, so what has to grow is the EVIDENCE the
> next such excursion must present, not the size it must reach. Double the confirming control
> passes the responsible detector needs; halve back toward the floor whenever a maneuver
> actually moves the split, so a workload that really is drifting stays cheap to follow.
>
> The rejected alternative was widening that detector's band by twice the excursion it just
> proved uninformative. Measured: a paced 8-key -> single-key change scores distance 0.630 on
> a metric whose maximum is 1.0, so one null result set a floor of 1.26 and the fingerprint
> detector could never fire again at any workload -- an accidentally disabled trigger.
> A threshold learned from an excursion can exceed every excursion; a window cannot.

## 2026-11-08 — 37. FlipController::anchor

Source: `src/core/flipctl.cc`, `FlipController::anchor`. Preserved source rationale:

> Was the test valid? Re-judge the hypothesis against the origin as it reads AFTER the
> return: if the target's delivered gain, corrected for how far the baseline itself moved
> during the excursion, would have cleared the threshold, the baseline moved out from
> under the test -- voided, not refuted -- and the model's record must not carry a miss it
> did not earn. A baseline wobble smaller than the miss changes nothing: measured here, a
> closed-loop driver came back 2.2% faster after a round trip whose target had delivered
> -48%, and that miss stands.

## 2026-11-08 — 38. FlipController::tick

Source: `src/core/flipctl.cc`, `FlipController::tick`. Preserved source rationale:

> Mid-maneuver, ONLY a forced trigger may interrupt. The maneuver's own split changes move
> the pass-depth signature, so honoring `shifted` here lets the actuator re-trigger itself
> forever (the sweep-abandon law: a signal the actuator moves cannot police it). The
> detector re-baselines at anchor; a real workload change re-fires from the anchored state.

## 2026-11-08 — 39. FlipController::tick

Source: `src/core/flipctl.cc`, `FlipController::tick`. Preserved source rationale:

> Turning maneuver-only age sampling off changes the producer dispatch cost. Learn the
> anchored fingerprint only after every owner has observed the dormant rate, otherwise
> the controller detects its own disarm edge as a workload shift.

## 2026-11-08 — 40. FlipController::tick

Source: `src/core/flipctl.cc`, `FlipController::tick`. Preserved source rationale:

> Pass-depth is rate-sensitive: a genuine volume step can cross both detectors on its
> first tick. Preserve that first rate observation until the required second one instead
> of letting the fingerprint preempt it and re-anchor at the new rate. A pure mix shift,
> with no pending rate evidence, still starts immediately.

## 2026-11-08 — 41. ClientHz::parse / ClientHz::effective

Source: `src/core/client_hz.h`, `ClientHz::parse / ClientHz::effective`. Preserved source rationale:

> Redis 7.4 config.c updateHZ and server.c serverCron/clientsCron.

## 2026-11-08 — 42. ClimonIoMask::set / ClimonIoMask::load

Source: `src/core/climon_mask.h`, `ClimonIoMask::set / ClimonIoMask::load`. Preserved source rationale:

> MONITOR/tracking destinations, including the forwarding history carried by an event.

## 2026-11-08 — 43. connreset::note

Source: `src/core/connreset.h`, `connreset::note`. Preserved source rationale:

> Optional connection-teardown diagnostics. No code/storage in ordinary builds.
> Build with -DTOMO_CONNRESET_TRACE and query DEBUG CLOSE-STATS. All writes are
> on failure/teardown paths; no Client/ThreadCtx/Op fields or request-path probes.

## 2026-11-08 — 44. IoLoop::receive_eof_pass

Source: `src/core/eof.cc`, `IoLoop::receive_eof_pass`. Preserved source rationale:

> End-of-stream admission and retirement. Ordinary receives never enter here.

## 2026-11-08 — 45. IoLoop::receive_fin

Source: `src/core/eof.cc`, `IoLoop::receive_fin`. Preserved source rationale:

> From its drain acknowledgement this IO's FLIP pin holds every close, and a close
> before the ownership commit refuses the FLIP at once (flipfix6). A FIN is that close
> for a draining connection, but its EOF timer cannot finish behind the FLIP: the
> pinned output's serve stays pending and complete input waits for admission, while a
> planned connection with a pending EOF is never transferable. Refuse the same way now
> rather than at the five-second deadline; the drain completes after rollback. After
> the commit this notes nothing and the timer resumes at Idle as before.

## 2026-11-08 — 46. Server::lb_drain_pass_expired

Source: `src/core/lbstall.h`, `Server::lb_drain_pass_expired`. Preserved source rationale:

> Cold LB drain accounting. Nothing here is visited by a stable placement's request path.

## 2026-11-08 — 47. Server::lb_refuse_stalled

Source: `src/core/lbstall.cc`, `Server::lb_refuse_stalled`. Preserved source rationale:

> LB may decline a move; it may never turn a readiness fence into a traffic timeout.

## 2026-11-08 — 48. Server::lb_refuse_stalled

Source: `src/core/lbstall.cc`, `Server::lb_refuse_stalled`. Preserved source rationale:

> A separate body also supplies an exact-size negative control: the measurement helper can
> replace this function by `return false` in a COPY of the binary, retaining every text address.

## 2026-11-08 — 49. Server::lb_refuse_stalled

Source: `src/core/lbstall.cc`, `Server::lb_refuse_stalled`. Preserved source rationale:

> Diagnostic negative control, never a runtime knob: keep the old timeout policy while
> reporting the predicate and its pending duration. Used only in the maintainer's debug PRE.

## 2026-11-08 — 50. ModeScheduleStats::note_reorder

Source: `src/core/orthog.h`, `ModeScheduleStats::note_reorder`. Preserved source rationale:

> Orthogonal schedule witnesses. Optional storage, no request-level hooks when disabled.

## 2026-11-08 — 51. lbsignals_capture / lbsignals_format

Source: `src/core/lbsignals.h`, `lbsignals_capture / lbsignals_format`. Preserved source rationale:

> lbsignals.h — the READ side of the signal system: capture, derive, export.
>
> signal.h makes every loop report LoopSignals in the same units (ops, nanoseconds, entries)
> and every shard report locality (foreign_ops). This interface captures those signals and
> derives the quantities exported by INFO's # LB section and DEBUG LBSIGNALS. Placement and
> role controllers also consume the underlying signals.
>
> COST: zero on the hot path. Everything here runs on the cold command path (DEBUG/INFO) or in a
> controller beat. Writers keep their plain single-owner stores; capture reads each counter with
> a relaxed __atomic_load_n (same MOV on x86). That is still a C++ data race, not a defined
> publication (TSan; flipfix CT4.3). Counters are MONOTONIC — rates are the reader's job;
> the server keeps no window state, so any number of readers can watch at their own cadence
> without stepping on each other. That statelessness is itself a signal-quality feature: the
> fork's sampled-cputime hack had one global window that every consumer fought over.
>
> Role ns_per_op is diagnostic only: executor ops count shard tasks while IO ops count
> commands. Their ratio is not a thread-split estimator on multi-key workloads. The role
> controller uses wall-minus-idle demand instead (flip_policy.h).
> Queue delay and oldest-age may TRIGGER a controller investigation, but they do not judge a
> placement: only measured throughput after the move can do that. Latency signals show pressure,
> not whether a different owner split will process more work.

## 2026-11-08 — 52. IoTenure::pass / IoTenure::finish

Source: `src/core/signalacct.h`, `IoTenure::pass / IoTenure::finish`. Preserved source rationale:

> IO accounting owns [begin_ns,end_ns) of ONE invocation of the IO loop. Consecutive
> publication cuts include the prologue, submit/reap, sweep and every continue edge. The
> final cut precedes read-local teardown, close draining and persistence shutdown.
> EX tenures and those teardown operations are outside this interval.

## 2026-11-08 — 53. IoTenureHistory

Source: `src/core/signalacct.h`, `IoTenureHistory`. Preserved source rationale:

> Appended to Server's cold tail, never to an array of IO loops or ThreadCtxs.
> One owner writes each row at tenure exit; shutdown reads only after join. Keeping
> this here preserves every IO-loop object's size, stride and existing cache lines.

## 2026-11-08 — 54. IoTenure

Source: `src/core/signalacct.h`, `IoTenure`. Preserved source rationale:

> Owner-local stack state only. Keep the clock every pass: cron, queue-age stamps
> and the depth beat already consume it. Book the COMPLETE elapsed interval only
> once per 100us signal window, not once per pass. Uneven passes and parked time
> are never extrapolated from a sampled turn. finish() always flushes the remainder.
> This has the same cadence as ThreadCtx::sample_depth; the controller's window is
> much longer. There is no per-client state, allocation, runtime knob or layout change.
> WindowNs=0 is the eager test/control specialization; production uses the default.

## 2026-11-08 — 55. IoTenure::account

Source: `src/core/signalacct.h`, `IoTenure::account`. Preserved source rationale:

> Keep the conservation checks and shared-counter store out of ordinary
> passes. Inlining this block enlarged every IO specialization and kept its
> accounting state live across recv/dispatch/send even when nothing changed.

## 2026-11-08 — 56. signal_doorbell_consume_request

Source: `src/core/signal_doorbell.h`, `signal_doorbell_consume_request`. Preserved source rationale:

> Process-wide shutdown doorbell: a save request wake, then a sticky terminal wake.
>
> eventfd accepts only an eight-byte counter write.  A signal contributes one logical event by
> writing uint64_t{1}. Only the elected save owner consumes a nonterminal request before doing
> the save, including a publisher's late write after a failed request ended. A separate terminal
> latch restores any stop edge caught by that drain, so all workers still observe shutdown.

## 2026-11-08 — 57. ThreadCtx::arm_blocked / Channel::wake

Source: `src/core/signal.h`, `ThreadCtx::arm_blocked / Channel::wake`. Preserved source rationale:

> signal.h — cross-thread handoffs and LoopSignals in common units for the IO and EX roles.
>
> Channels pair queue publication with notification, so load measurements use the same units
> across directions. Ready-mask completion notifications share those wake and work counters.
>
> IO -> EX    MaskedChannelArray dispatch a parsed Task to the shard's owner
> EX -> IO    ready mask / Channel<Client*> notify the connection owner to retire and send
>
> UNITS, fixed here so nothing has to be converted at the point of comparison:
> work      operations (uint64 monotonic count)
> time      NANOSECONDS, and busy is TIME-WEIGHTED, not an event count. A balancer that counts
> events treats one expensive op the same as one cheap one; the fork's working pressure
> balancer is time-weighted for exactly this reason.
> pressure  queue depth in ENTRIES, accumulated with a sample count so a consumer can take a
> time-average rather than a spot reading. Spot depth is noisy enough to make a
> controller chase its own tail.
>
> THE 3% RULE. This machinery is always on, so it must cost under 3% or it does not ship. Hence:
> scheduling counters are owner-written. Socket totals also have cross-thread INFO readers;
> their single-writer atomic updates use relaxed load/store, never a shared atomic RMW.

## 2026-11-08 — 58. thread_cpu_ns

Source: `src/core/signal.h`, `thread_cpu_ns`. Preserved source rationale:

> Thread CPU time. Needed because DEFER_TASKRUN defers completion work to the point where the thread
> waits on the ring, so wall-clock "time spent in the work section" understates how busy the thread
> really is. A controller that reads only wall time under DEFER_TASKRUN is measuring the wrong thing
> — that already produced one wrong reading in the fork.

## 2026-11-08 — 59. ReadyMask

Source: `src/core/signal.h`, `ReadyMask`. Preserved source rationale:

> THE #19/#20 DESIGN, ported: workers signal reply-readiness by setting an IDEMPOTENT bit in the
> sender's mask instead of posting the Client* through a channel. Three properties fall out, and
> each one retires a bug class this tree has already paid for:
> - no claim protocol: a bit set twice is one bit, so the CAS-claim dance (and its StoreLoad
> fence discipline) is not needed on this path;
> - no pointers in flight: a channel entry can outlive the client (the teardown UAF); a bit
> cannot -- the sender maps slot -> client through a table IT owns and IT clears;
> - no stranding: the bit stays set until the sender takes it, and any completion after a take
> re-sets it, so "both sides walk away" is unrepresentable.
> Same take-then-serve ordering as NotifyMask; same read-first guard so a busy producer pays a
> shared-line read, not an RMW. set() returns true on the empty->flagged transition (that RMW is a
> full fence) -- the caller who gets true owes the park-wake, exactly like the channel protocol.

## 2026-11-08 — 60. NotifyMask::take

Source: `src/core/signal.h`, `NotifyMask::take`. Preserved source rationale:

> Load-first, for the same reason ReadyMask::take is: an exchange is a locked RMW that takes
> the line exclusive even when the word is zero, and every consumer pass takes every word of
> every mask it drains -- four locked RMWs per io pass and four per ex pass, ~100 cycles that
> at p1 are paid per OP because a pass is one op. A zero word is the common case and the
> relaxed read costs a shared-line load. A bit set between the load and the skipped exchange
> is not lost: it is still set, the next pass takes it, and the park path re-checks masks AND
> queue depths behind a seq_cst fence (ThreadCtx::arm_blocked) so no wake can be missed.

## 2026-11-08 — 61. Channel::push

Source: `src/core/signal.h`, `Channel::push`. Preserved source rationale:

> Returns false when full. A false MUST be handled — never dropped. Losing a queued item here
> loses a reply and wedges the connection waiting for it, which is precisely the bug that
> shipped in the fork.
> `peer_ring` is the CONSUMER's ring, passed in rather than bound at construction: a bound
> pointer would need every thread's ring to exist before any channel is wired, and getting that
> startup order wrong leaves the pointer null and NO WAKE IS EVER SENT — a consumer that blocks
> then sleeps forever on a non-empty queue. Passing it makes the dependency impossible to forget.
> SPLIT IN TWO ON PURPOSE. The consumer's decision to sleep is made by reading the notify mask,
> so the mask bit must be published BETWEEN the push and the wake decision. When this was one
> call that set the bit afterwards, the producer read blocked_ before the bit existed and the
> consumer read the bit before the producer wrote it -- both sides saw "nothing to do" and an
> isolated request hung forever. Pipelined traffic hid it, because the next request re-poked the
> consumer; only a lone command exposed it.

## 2026-11-08 — 62. MaskedChannelArray

Source: `src/core/signal.h`, `MaskedChannelArray`. Preserved source rationale:

> One wake endpoint around one consumer-owned masked slot array.  Queue frontiers remain per
> producer; only the blocked flag is shared, which is equivalent to the old code arming every task
> channel together and removes nproducer stores from the sleep-only path.

## 2026-11-08 — 63. wb_rule::defer

Source: `src/core/wb_rule.h`, `wb_rule::defer`. Preserved source rationale:

> One writeback policy in both modes: bounded small-pipe completion OR bytes OR half.

## 2026-11-08 — 64. wb_rule::kSmallPipe

Source: `src/core/wb_rule.h`, `wb_rule::kSmallPipe`. Preserved source rationale:

> MEASURED default S=16, not derived from a batch size or reply size. Constants ledger
> addendum 12, S=16 KEEP (2026-10-02); PLAN-SERIAL 2026-10-01 16:54 and
> 2026-10-02 06:54: p8 saturation, p8@512K attainment, floor-0.4 bursts.
> See MEASURE-REQUEST-wbhybrid.md: no honest derivation from existing sizings.

## 2026-11-08 — 65. wb_rule::kCompleteVisits

Source: `src/core/wb_rule.h`, `wb_rule::kCompleteVisits`. Preserved source rationale:

> MEASURED default D=3. Constants ledger addendum 12, D=3 DERIVE-BY-MEASUREMENT
> (2026-10-02); PLAN-SERIAL 06:54 D-curve row 3: p8 GET/SET/rl-SET
> +9.4/+10.4/+6.6%, with floor-0.4 p99/p999 inside the same-binary band.

## 2026-11-08 — 66. wb_rule::kIdleMultiplier

Source: `src/core/wb_rule.h`, `wb_rule::kIdleMultiplier`. Preserved source rationale:

> Measurement arms only; the maintainer keeps the smallest multiplier that
> passes merit and removes this override. No runtime knob or machine time bound.
> WB4.1 merit selected the two-completion grace window.

## 2026-11-08 — 67. wb_rule::IdleWindow::active

Source: `src/core/wb_rule.h`, `wb_rule::IdleWindow::active`. Preserved source rationale:

> Division preserves wave5b's boundary and avoids multiplication overflow.

## 2026-11-08 — 68. wb_rule::kPolicyFraction

Source: `src/core/wb_rule.h`, `wb_rule::kPolicyFraction`. Preserved source rationale:

> Dimensionless POLICY fraction, not a byte/count/time bound. Competition record
> section 39 (2026-09-23/24), w4-c12: parse 32 / EX 32 / composite 1/2.

## 2026-11-08 — 69. wb_rule::staged_bytes

Source: `src/core/wb_rule.h`, `wb_rule::staged_bytes`. Preserved source rationale:

> IO-owned sizes only; exclude submitted send/segment bytes from the next batch.
> buffered_output_bytes() already walks the existing segment queue, without a
> byte counter or allocation. Its send remainder equals send_buf().size()-wsent()
> at every valid writeback frontier, as in the measured arm's accessor.

## 2026-11-08 — 70. wb_rule::defer

Source: `src/core/wb_rule.h`, `wb_rule::defer`. Preserved source rationale:

> Separate measured candidate: assembly stays in ordinary WB, in ROB order.

## 2026-11-08 — 71. Client::flip_migration_protocol_idle / IoLoop::flip_session_drain_refused

Source: `src/cmd/flip_session.inc`, `Client::flip_migration_protocol_idle / IoLoop::flip_session_drain_refused`. Preserved source rationale:

> D18.1: only ClientPrepare (after IoDrain/ExDrain) uses this exception. The
> session, queued argv/error and watched aliases belong to the stable Client,
> not its IO. An unpublished attempt still owns admission on its source IO.

## 2026-11-08 — 72. IoLoop::flip_session_drain_refused

Source: `src/cmd/flip_session.inc`, `IoLoop::flip_session_drain_refused`. Preserved source rationale:

> D18.2 conservative policy: S2 owns unpublished IO admission/apply credits.
> Reject on ANY source before ExDrain; leave the state and original IO intact.
> The global dispatch pause prevents it publishing until rollback reaches Idle.

## 2026-11-08 — 73. IoLoop::closing_client_ready

Source: `src/cmd/flip_session.inc`, `IoLoop::closing_client_ready`. Preserved source rationale:

> The active close retry must revisit deferred WATCH cleanup before its unchanged
> zero-pin lifetime check. It runs only in the already-closing branch (both IO
> engines); live GET/SET/etc never call it. The original cleanup is idempotent.

## 2026-11-08 — 74. IoLoop::flip_client_drained / IoLoop::flip_output_hold

Source: `src/cmd/flip_liveness.inc`, `IoLoop::flip_client_drained / IoLoop::flip_output_hold`. Preserved source rationale:

> FLIP-only connection liveness. Included after MultiSession and BlockingState.
> Ordinary commands never call these helpers. Blocking continuations alone
> consult the existing FLIP acknowledgement before publishing new owner work.

## 2026-11-08 — 75. flip_liveness_enabled

Source: `src/cmd/flip_liveness.inc`, `flip_liveness_enabled`. Preserved source rationale:

> PAD-A patches only this immediate in each namespace. PRE behavior then runs
> with exactly the candidate's text/layout; this is not a runtime option.

## 2026-11-08 — 76. IoLoop::fliplisten_plan / cfgfix_rebind

Source: `src/core/fliplisten.cc`, `IoLoop::fliplisten_plan / cfgfix_rebind`. Preserved source rationale:

> Listener ownership is independent of an IO tenure. Everything in this file is
> reached through an existing cold accept branch or a live FLIP control tail.

## 2026-11-08 — 77. IoLoop::fliplisten_retry_accept

Source: `src/core/fliplisten.cc`, `IoLoop::fliplisten_retry_accept`. Preserved source rationale:

> The pre-existing per-pass accept_pending_ branch is the only caller.
> Keep arm_accept itself unchanged: even a cold call in its quiescing branch
> made GCC save another register on every ordinary native accept rearm.

## 2026-11-08 — 78. IoLoop::fliplisten_retry_accept

Source: `src/core/fliplisten.cc`, `IoLoop::fliplisten_retry_accept`. Preserved source rationale:

> Publish only after the walk; setting quiescing before a later native
> rearm used to suppress that rearm (or recurse through an arm hook).

## 2026-11-08 — 79. weighted_lb_partition

Source: `src/core/weighted_lb.h`, `weighted_lb_partition`. Preserved source rationale:

> weighted_lb.h -- the one placement policy shared by FLIP and the continuous controller.
>
> Demand is primary. An optional second load vector (bytes for buckets) is compared
> lexicographically, never blended into demand. Count remains a hard invariant: every target
> finishes with floor/ceil item count, including the all-zero boot window. Items are considered
> largest-first and placed on the least loaded eligible target; current ownership and target id
> only break exact ties. This is deterministic, allocation-only code and never runs on a request
> path.

## 2026-11-08 — 80. weighted_lb_partition

Source: `src/core/weighted_lb.h`, `weighted_lb_partition`. Preserved source rationale:

> Ties keep the incumbent -- globally, not just per greedy step. The greedy fill above cannot
> see that a zero-move assignment with the same spread exists (once an item's incumbent has
> absorbed earlier items it looks "fuller" and the item is shipped elsewhere), so a balanced
> no-op FLIP reshuffled a hundred buckets for nothing. If assigning every item to its current
> owner is feasible under the same count bounds and no worse in weight or secondary spread
> than the greedy plan, prefer it wholesale: locality is free when balance ties.

## 2026-11-08 — 81. Placement::build_even / Placement::set_runtime_role

Source: `src/core/placement.h`, `Placement::build_even / Placement::set_runtime_role`. Preserved source rationale:

> placement.h — per-thread role/cpu placement and the shard migration contract.
>
> A LOGICAL THREAD IS THE DEFAULT LOCALITY UNIT. When the allowed CPU set contains sibling pairs,
> Linux's reported pair is the scheduling unit: both dense thread ids have one role and FLIP moves them
> together. There is deliberately no node layer between a thread and its cpu/L3 facts.

## 2026-11-08 — 82. Placement::build_even

Source: `src/core/placement.h`, `Placement::build_even`. Preserved source rationale:

> EVEN GLOBAL PLACEMENT. Counts are whole-server, so shapes no per-node grammar can express
> (15:2) are first-class. IO and EX roles spread across the L3 domains as evenly as
> integer division allows, with the roles interleaved within each domain.
>
> This is also the flip-era invariant in batch form: a runtime controller changing one thread's
> role keeps these same quotas incrementally -- pick the convert candidate from the domain
> whose count for the shrinking role sits above quota and whose count for the growing role
> sits below it. Placement stays a pure function of (counts, topology); no node layer.

## 2026-11-08 — 83. Server::lb_controller_tick

Source: `src/core/lbplanner.cc`, `Server::lb_controller_tick`. Preserved source rationale:

> LB admission/gather/search has one writer: the main monitor thread.
> The existing stage word publishes a finished immutable slot to its IO coordinator.

## 2026-11-08 — 84. lbosc3_level

Source: `src/core/lbplanner.cc`, `lbosc3_level`. Preserved source rationale:

> One offline PAD-A patch point: returning zero restores PRE policy on this exact
> layout. Production returns the configured level; no ordinary operation calls it.

## 2026-11-08 — 85. LbAutotune::KeyDamping::update

Source: `src/core/lbplanner.cc`, `LbAutotune::KeyDamping::update`. Preserved source rationale:

> even at INT32_MAX. The 1.5 ceiling is the owner's allowed accuracy budget.

## 2026-11-08 — 86. lbosc3_best_incremental_move

Source: `src/core/lbplanner.cc`, `lbosc3_best_incremental_move`. Preserved source rationale:

> The key objective lives in the cold planner TU. The shared PRE search remains
> unchanged for clients, FLIP, and the behaviour twin.

## 2026-11-08 — 87. Server::lb_controller_tick_pad

Source: `src/core/lbplanner.cc`, `Server::lb_controller_tick_pad`. Preserved source rationale:

> These PRE bodies are comparison material, not a runtime mode. PAD-A retargets
> the existing tail/monitor calls and each private gate load in a COPY of POST.
> Keep the admission body and actuator body mechanically equal to cd02ecbab;
> the artifact verifier compares them before allowing a twin to be built.

## 2026-11-08 — 88. IoLoop::lb_pass_begin_pad

Source: `src/core/lbplanner.cc`, `IoLoop::lb_pass_begin_pad`. Preserved source rationale:

> PRE had no per-pass pause snapshot; its live per-connection gate is restored in PAD.
> In particular, do not overwrite the same eight bytes that PAD uses as its cron deadline.

## 2026-11-08 — 89. IoLoop::lb_control_pass_pad

Source: `src/core/lbplanner.cc`, `IoLoop::lb_control_pass_pad`. Preserved source rationale:

> The same eight bytes were the PRE per-IO cron deadline. PAD never writes
> a cached pause ID; its parser reads the live stage, as PRE did.

## 2026-11-08 — 90. FlipShiftDetector

Source: `src/core/flipctl.h`, `FlipShiftDetector`. Preserved source rationale:

> The shipped controller uses the learned band: twice pre-anchor jitter, floored by both
> continuously learned in-band noise and 2/sqrt(N) for N sampled commands. The fixed/disabled
> forms remain for byte stability; no production constructor selects either form.

## 2026-11-08 — 91. FlipController::model_margin_

Source: `src/core/flipctl.h`, `FlipController::model_margin_`. Preserved source rationale:

> OUTCOME MARGIN: how many throughput bands of projected gain the model must clear. Doubles
> when a maneuver moved and came back (the projection did not deliver -- a biased estimator
> does not get less biased with more samples, so the BAR rises), halves when a move delivered,
> and never grows past the point where the required gain would exceed 100%, which would
> retire the model for good. Derived at both ends: the band is learned, the cap is arithmetic.

## 2026-11-08 — 92. FlipController::start_maneuver

Source: `src/core/flipctl.cc`, `FlipController::start_maneuver`. Preserved source rationale:

> Where this maneuver started. If the search comes back here, the trigger that started it
> demanded a move and the measurements refused one: that excursion carries no placement
> information and anchor() turns it into a band floor.

## 2026-11-08 — 93. FlipController::measure_flip

Source: `src/core/flipctl.cc`, `FlipController::measure_flip`. Preserved source rationale:

> Books the flip that just returned to Idle into the cost model. Called at the first look that
> sees Idle, which wait_ms() makes a fraction of a tick after completion, so the served count is
> contaminated by at most that fraction of post-flip traffic at the new rate.

## 2026-11-08 — 94. flip_cost_gate

Source: `src/core/flip_policy.h`, `flip_cost_gate`. Preserved source rationale:

> THE COST GATE, and it is ASYMMETRIC BY CONSTRUCTION -- a move off a split that delivers a
> fraction of the achievable rate must not wait for the long stability window a marginal move
> needs. The benefit is the kappa-scaled gain credited over the horizon the workload has held
> still, less the blind time; it scales with the GAIN. The cost is the flip, the revert with
> probability P_miss, and the blackout: with probability P_miss the move is wrong and the T_black
> seconds blind risk the whole ORIGIN throughput (a wrong target could deliver nothing before the
> revert) -- NOT gain_mean x rate, which would scale the cost with the gain too and cancel the
> asymmetry. So benefit/cost ~ gain, and the stationarity a move needs to clear the gate falls as
> the gain rises: a +2400% move off a wrong-split boot pays at ~1.0 T_black, a +5% move needs the
> workload to hold for tens of blackouts. The wait derives from the distance, no constant added.

## 2026-11-08 — 95. NotifyMask::set

Source: `src/core/signal.h`, `NotifyMask::set`. Preserved source rationale:

> Producer side. One relaxed load in the common case; the RMW is paid only on the empty->flagged
> transition, which under load is rare.
>
> RETURNS TRUE only when THIS producer performed the transition, and that answer is what decides
> who owns the wake — see the Dekker note on Channel::wake(). A producer that finds the bit
> already set owes no wake: the bit is still set, so the consumer has not taken it yet, so the
> consumer is still going to take it and drain this channel, and our item is already in the queue
> by then. The seq_cst on the RMW is load-bearing, not decoration: it is the full fence that keeps
> the store of the bit from being reordered after the load of blocked_ in wake().
