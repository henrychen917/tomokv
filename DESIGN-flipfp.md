# DESIGN-flipfp -- the flip fingerprint leaves the per-op hot path

Lane t-flipfp, base e2ef7a155 (train 11). Lever I2 of CYCLEMAP.md: `flip_fingerprint_note` ran its
full body on every dispatched frame -- 63 (1T) to 86 (2T) instr/op and 8.6% of the write path's
store-queue-full stall -- for a detector whose only reader is off in the shipped config.

## 1. What the fingerprint computes and who reads it

**Writer** (`FlipFingerprintWriter`, flipctl.h; body `flip_fingerprint_note`, io_loop.h). At each of
the 15 dispatch sites in `parse_and_dispatch` (13 cold: pubsub, FLIP, DEBUG SLEEP, WAIT, io-local
commands, three scatter paths; 2 hot: the fused local-read lane and the ordinary point dispatch) the
body computes, per frame: `keys` (spec first/last/step against argc), `value_bytes` (an argv loop
summing the lengths of every non-key argument), and a class in {Read, Write, MultiRead, MultiWrite,
AtomicGrouped, Blocking, Other}; then `note_command` performs four to five read-modify-write stores
into `partial_` (class bucket, commands, value_bytes, multikey keys/ops) plus `pass_frames_++`.
`finish_parse_pass` (the two exits of `parse_and_dispatch`) buckets the pass depth (1 / <=4 / <=16 /
more) and, once `partial_.commands >= flip_work_window` (default 100), adds the window into the
cumulative `published_` and bumps `closed_windows` as the last store.

**Readers.** Exactly one: `FlipController::sample_fingerprint` (flipctl.cc:235), once per controller
tick (`--lb-tick-ms`, 1 s), which sums the deltas of every thread's `published_` since the previous
tick into ONE aggregate and feeds it to `FlipShiftDetector::observe`. The controller's decision unit
is therefore the tick aggregate, not the 100-command window; the window is only the publication
granularity. `flip_signature` is scale-free -- normalized class and depth fractions,
value_bytes/commands, multikey_keys/multikey_ops -- and the absolute `commands` count enters only
the band's quantum floor `4/K`. Two side uses: `boot_load_stable` will not start the boot maneuver
until at least one window has closed (`boot_work_observed_`), and Settling needs one tick with a
closed window before anchoring. INFO FLIPCTL exposes trigger counts and the learned bands, not the
counters; DEBUG FLIPCTL dumps controller state. **Nothing reads `published()` when `--flip-auto 0`
or in 1s mode (which refuses `--flip-auto`)** -- the config.h note "so DEBUG can inspect its detector"
describes a reader that does not exist.

## 2. Design

**(a) Gate -- the dark writer.** The writer is armed only when its reader exists: `ThreadCtx::init`
receives `flipctl_.enabled() ? cfg.flip_work_window : 0` (server.h), the same predicate that enables
the controller. The per-op gate is `FlipFingerprintWriter::pass_sampled()` = `pass_countdown_ == 0`:
one load of a thread-private word on the line today's `enabled()` test already read, one
predicted-false branch, no store. Dark writer: the word is initialised to 1 and never written, so the
line stays clean in L1. No new field, no new line, no knob; `flip_work_window` keeps its
grammar (0 = off) and its CONFIG GET value.

**(b) Sample -- whole parse passes, 1 in W.** When armed, the body runs for every frame of a
*sampled* pass and for no frame of any other pass. Passes are sampled with gaps drawn uniformly from
[1, 2W-1] passes (mean W, W = `flip_work_window`), the draw taken from the io loop's own xorshift
only at the end of a sampled pass (nothing evaluated eagerly). Why passes rather than ops: the hot
point paths count commands on the executor side, so no io-side per-op counter exists that all 15
sites already increment (`sig.ops` misses the eight io-local sites -- PING among them); a per-op
countdown would cost the very store this lane removes; and a pass-granular sample keeps the body
and its statistics byte-for-byte what they are today -- a sampled pass publishes exactly what the
old writer would have accumulated for that pass (classes, keys, bytes, and its depth bucket).
Why uniform gaps with 1 in the support: an every-Wth stride aliases with any workload whose
classes alternate with a period dividing W (memtier's 1:1 ratio is period 2); a renewal process
whose gap support has gcd 1 equidistributes over every period, so every class is sampled in
proportion.

**Arithmetic.** W = `flip_work_window` (100), d = frames per pass, C = commands/s over the io
threads, T = the tick (1 s), B = body cost (63-86 instr, 5 stores).

| | PRE | POST |
|---|---|---|
| per-op work | B + 5 stores, every frame | 1 load + 1 branch; body on 1/W of frames |
| amortised instr/op | 63-86 | B/W + ~2 = 2.6-2.9 |
| stores/op | 5 | 5/W = 0.05 |
| samples per decision (tick) | K = C·T | K = C·T / W |
| publications per tick | C·T / 100 | C·T / (W·d) |
| commands per fingerprinted command | 1 | W -- the knob's documented meaning, at any depth |
| signature expectation | s | s (scale-free: a 1/W sample of a stationary stream has the same signature; unit row) |
| sampling noise on a class fraction p | sqrt(p(1-p)/K) | sqrt(p(1-p)/K_eff), K_eff in [K/d, K] (heterogeneous .. homogeneous connections) |
| band | 2·max(jitter, 4/K) | 2·max(jitter, 4/K): learned from the sampled stream, so it already contains the sampling noise |

The window-length x sample-rate identity: a sampled pass contributes d frames once per W passes,
i.e. W·d commands elapse per publication and d of them are fingerprinted -- the same 1/W of the
work at every pipeline depth, and the same body per fingerprinted frame. Accuracy comes from the
window: at the box (C ~ 16-18M/s, p32) K = 170k samples per tick, sigma_distance = 0.25/sqrt(K_eff)
= 0.0006 (0.0034 in the fully heterogeneous worst case) against real mix shifts of >= 0.025 (10% of
one class family). In the gate row (BITCOUNT at ~18k/s, p1) the signature is deterministic (one
class, depth 1, no values), so sampling adds no variance and the BITCOUNT -> INCR shift is distance
> 0.25 against a 2% band. The one behavioural difference: publication is per sampled pass, so at
fewer than W passes per tick (a trickle at deep pipelines) the fingerprint is observed every ~W
passes instead of every W commands; the first pass after boot is always sampled (the boot gate sees
work within one pass), and the rate detector, which reads the unsampled `total_commands`, is
unchanged. W = 1 is exhaustive sampling -- today's behaviour exactly -- and is the equivalence oracle
in the unit test.

**(c) What the sample costs the band, stated exactly.** The band arithmetic above hides a term, so
here it is in full. `FlipShiftDetector::update_band` (flipctl.cc) is

    band = 2 * max(jitter, 4 / max(commands, 1))          // commands = the TICK aggregate's count

and `commands` is exactly the quantity this lane divides by W. Verified in the code, not assumed:
`FlipController::sample_fingerprint` (flipctl.cc:235) sums each thread's `published_` **delta since
the previous tick** into one aggregate, skips a thread whose `closed_windows` did not advance, and
calls `shift_detector_.observe(aggregate)` **once per tick**; `maneuver_signature_samples_` and
`anchor_signature_samples_` count those ticks. So the decision window is the tick T, never the
100-command publication window, and

    K = commands per decision = C * T   (PRE)   ->   C * T / W   (POST)
    quantum floor of the band = 8 / (C*T)  (PRE)  ->  8*W / (C*T)  (POST)

Two regimes follow, and they are the thing to measure rather than argue:

- **Jitter-dominated** (`jitter > 4/K`, the busy case). The band is the anchor's own quiet jitter,
  learned from whichever stream the detector saw. The sampled stream's jitter is the exhaustive
  stream's jitter plus the sampling noise sigma = 0.25/sqrt(K_eff), so the band widens by however
  much noise the sample actually adds and keeps rejecting exactly what it rejected before. This is
  self-correcting: the band is learned from, and applied to, the same sampled stream. On this box's
  accuracy cell (C ~ 350k/s, W = 100) the PRE band was 2.4e-3 against a PRE floor of 2.3e-5 -- 100x
  above the floor -- and the POST floor lands at 2.3e-3, i.e. right at the jitter the exhaustive
  stream already had. Whether the band actually moves is S2's measurement.
- **Quantum-dominated** (`jitter < 4/K`, the quiet/low-rate case). The floor rises by W outright.
  This is not a defect but the honest resolution of a 1/W sample: a sample of K/W commands cannot
  resolve a mix change finer than one sampled command in it, and a floor that claimed otherwise
  would trigger on its own sampling noise. It does cost sensitivity, and the loss is a factor of W
  in the smallest mix shift a *quiet* anchor can name.

**The fixed-band exposure.** `configured_band_ > 0` (`--flip-auto-band PERCENT`) returns the percent
directly and never consults the floor, so in that mode the sampling noise is not absorbed by a
wider band -- it must simply fit under the configured percent. That is the one place a 1/W sample
can turn into a false trigger, and it is precisely what the `tests/flipctl.py` gate row exercises:
band 2, a jittery stationary 6:2 load, and a 30 s hold that fails on any trigger. At that row's
rate the per-tick sample is small, so the row is the binding accuracy test of this lane and is run
three times per arm.

## 3. Footprint

`pass_frames_` (u32) becomes `pass_countdown_` (u32): the writer stays 264 bytes, ThreadCtx stays
1408, `partial_.commands` is the sampled pass's frame count (the pass publishes and resets). Op,
Client, Shard and Config are untouched.

## 4. Proof plan (results in the lane report)

Same-binary null; PRE/POST instr/op, cyc/op, IPC and store-queue-full cycles by the cyclemap slope
method (replay + perf stat, matched op stream) on armed 1s SET p32 (1T, 2T), 2s SET p32 and GET
(must be unchanged), all `--flip-auto 0`; always-on cost with `--flip-auto 1` PRE vs POST at
matched rate; accuracy: the flipctl.py gate row, the wrong-split boots 3:1 (4 threads) and the
28:4 analogue on this lane's cores with the flipguard reference (the fingerprint must still let
the controller move; `--flip-auto 0` must not), anchored `flipctl_signature_band` PRE vs POST and
false-trigger count on a heterogeneous-connection mix; unit rows for the gap arithmetic, the
aliasing case, the W = 1 equivalence and the quantum floor; batteries in both modes; differ; gate
quick.

## 5. Results (base ceb6b02f8, arms differ by this change only)

Arms: PRE = mainline ceb6b02f8 (`79651da57b14ac1b`), POST = this branch (`71b2854a7599ee8a`), both built with
`taskset -c 48-51,176-179 make -j8` in their own worktree. Method: cyclemap slope (replay, N1=300k /
N2=900k ops per connection, so every figure is marginal cost per op at matched rate, not an average
inflated by idle spin). Armed (`--atomic 1`), p32, ring 4096, 2 reps; spread is [min..max]/2.
`--flip-auto 0` throughout the perf table -- the shipped configuration, in which PRE runs the body on
every dispatched frame and POST does not run it at all.

### 5.1 The lever, against its own same-binary null

| cell | metric | PRE | POST | delta | NULL (PRE vs PRE) | verdict |
|---|---|---:|---:|---:|---:|---|
| 1s 1 thread, SET | instr/op | 3198 | 3096 | **-102** | +8 | 12x the null |
| 1s 1 thread, SET | cycles/op | 1084 | 1059 | -24 | -17 | within the null |
| 1s 2 threads, SET | instr/op | 3246 | 3153 | **-94** | +27 | 3.5x the null |
| 1s 1 thread, GET | instr/op | 2240 | 2146 | **-94** | -0 | null is zero |
| 1s 2 threads, GET | instr/op | 2276 | 2193 | **-83** | -1 | null is zero |
| 2s split, SET | instr/op | 3217 | 2989 | **-228** | -5 | 46x the null |
| 2s split, SET | cycles/op | 1451 | 1336 | **-115** | +23 | opposite sign to the null |
| 2s split, SET | store-queue-full cyc/op | 239 | 193 | **-45** | +8 | opposite sign to the null |
| 2s split, SET | driver ops/s | 4.50M | 4.87M | **+8.1%** | -1.8% | opposite sign to the null |
| 2s split, GET | instr/op | 3000 | 2808 | **-191** | -4 | 48x the null |
| 2s split, GET | cycles/op | 1398 | 1311 | **-86** | +8 | opposite sign to the null |
| 2s split, GET | store-queue-full cyc/op | 258 | 227 | **-30** | -1 | 30x the null |

The null is the instrument's own answer, and it is what makes the table readable: **instr/op is the
trustworthy metric** (null +8 / +27 / -0 / -1 / -5 / -4), while at 1 fused thread cycles/op and
store-queue-full move as much in the null as in the real comparison and are not claimable there.
Both are claimable in split, where they run opposite in sign to the null.

The measured drop exceeds CYCLEMAP's predicted 63-86 instr/op everywhere; that prediction was taken on
an older base and a different geometry. GET falls as much as SET, which is what the mechanism says
must happen -- the body ran per *dispatched frame*, not per write. The split saving (-228/-191) is
about 2.2x the fused saving (-102/-94); the fingerprint is charged per frame in both modes, so the
split multiplier is an open observation, not something this lane's change created.

**The gate-the-argument law (no new cold line).** Machine-wide demand fills per op are flat or lower
in every cell: 2s SET dmnd-L2 -1.98/op (-7.5%), DRAM -25%, same-CCX -0.07; 1s SET same-CCX -0.01,
DRAM -0.08. The only counter that rises is the *user-attributed* subset on one cell (1s SET,
+0.62/op) while its machine-wide twin is flat and total cycles/op fall -- an attribution shift, not a
new line. This is what the design predicts: `pass_countdown_` is at offset 4 of the same object whose
offset 0 (`work_window_`) the old `enabled()` test already loaded.

**Cost when armed.** With `--flip-auto 1` (anchored, band 0) on 2s: POST still leads PRE by -165
instr/op and -74 cyc/op on SET, -123 and -32 on GET. Turning the controller on is not a clean
"always-on cost" measurement in either arm, because `server.h` also disables `lb_age_sample_rate`
when `flip_auto` is set; the like-for-like arm comparison above is the meaningful one.

**One honest regression.** On the FUSED GET path store-queue-full rises +22 to +24 cyc/op (1 thread
and 2 threads alike; the null on that counter is -1 and +0, so it is real) while cycles/op is flat to
-9 and instr/op is -83 to -94. Removing the body redistributes the remaining stores rather than
adding work; net cycles do not regress. It does not appear in split, where the same counter falls.

### 5.2 Controller accuracy: unchanged

The perf win would be vacuous if the sampled fingerprint had simply stopped detecting -- a dead
detector is both cheap and silent, and "no false triggers" is exactly what a dead detector reports.
So the gate had to OPEN.

**Liveness.** `band_` is written only by `update_band()`, which runs only from `observe()`, which runs
only on a published window. Anchored on a stationary 3.64M/s 2:2 load, POST reports
`signature_band = 0.000206` -- nonzero, so the sampled writer published and the detector read it. Its
value is the predicted quantum floor: `8W/(C*T) = 8*100/3.64e6 = 2.20e-4` against 2.06e-4 measured.
(The accuracy cells' all-zero dumps were snapshots taken mid-maneuver, when `reset()` had just zeroed
the detector; both arms show that.)

**Detection, isolated from the rate detector.** A workload swap normally moves the command rate too,
and the rate detector's learned band here is ~0.3%, so it always wins the race -- which is why the
first probe attributed nothing. `scratch/flipfp/fpshift.sh` pins the rate with `--rate-limiting` and
changes only the CLASS: phase A GET-only, phase B SET-only, same connections, same pipeline, same
per-connection rate.

| | PRE | POST |
|---|---:|---:|
| phase A rate / phase B rate | 512003.70 / 512015.39 (+0.0%) | 512010.30 / 512016.83 (+0.0%) |
| anchored band (phase A) | 0.000655 | 0.005597 |
| **fingerprint triggers on the swap** | **1** | **1** |
| shift distance / shift band | 0.000617 / 0.000470 | 0.015517 / 0.013625 |

Both arms detect the mix change with exactly one fingerprint trigger at an identically pinned rate.
The band is regime-dependent exactly as section 2(c) predicts -- 8x TIGHTER than PRE at 3.6M/s
(quantum-floored) and 8.5x wider at 512k/s (jitter-dominated, the jitter inflated by sampling noise
sigma = 0.25/sqrt(K_eff), K_eff near the homogeneous end of its bracket) -- and detection survives
both because band and distance scale together: the band is learned from, and applied to, the same
sampled stream.

**Wrong-split boots** (MK8 1:1, atomic 1, 120 s; `--flip-auto 1`):

| cell | flips | time to first move | stabilized | final split |
|---|---:|---:|---:|---|
| 3:1 PRE | 8 | 12 s | **never** | 3:1 (back to the wrong split) |
| 3:1 POST | **1** | 16 s | 16 s | **2:2** |
| 3:1 POST, `--flip-auto 0` | 0 | never | - | 3:1 (dark, correct) |
| 5:1 PRE | 1 | 18 s | 18 s | 4:2 |
| 5:1 POST | 1 | 15 s | 15 s | 4:2 |

POST moves once and lands in both; on 3:1 it is PRE that thrashes (8 flips, never stabilizes, ends on
the split it booted with). 28:4 is not runnable on a four-physical-core allocation -- 5:1 on six
threads is the widest analogue this lane's cores hold, and it is reported as such.

`tests/flipctl.py --stable-seconds 30` (6:2, band 2, age 1024): **POST 3/3 pass, PRE 3/3 pass.**
That row is the binding fixed-band test (section 2(c)): `configured_band_ > 0` never consults the
quantum floor, so sampling noise there must simply fit under 2%.

### 5.3 Correctness

Batteries 1s 10/0 and 2s 12/0 (including `flip`, `flip_under_load`, `flip_ttl`); differ gate
168 pass / 0 fail; `flipctl_unit` ok (unit rows for the gap distribution over [0, 2W-2] with mean W,
the 1/W sample rate at depths 1 and 32, the period-2 aliasing case, W = 1 equivalence against the
embedded exhaustive writer over 20k mixed-depth passes, the dark writer's gate word, and the
band's quantum floor). Layout locks hold and are identical on both arms: Op 336, Client 1984,
ThreadCtx 1408, Shard 1440, Config 624 (FlipFingerprintWriter 264, unchanged).

`tests/gate.sh quick`: POST 326 ok / 1 FAIL. The failing row is `PROGRAM-STATE ledger (326/324
checks)`, and **PRE reproduces it byte-identically (326 ok / 1 FAIL, same row, same counts)**:
`EXPECT_QUICK=324` in tests/gate.sh was not bumped when trains 12 and 13 added two rows. Pre-existing
mainline bookkeeping drift, at exact parity, not this lane's.

**Random stream.** `arm()` draws from the io loop's xorshift, whose only other consumer is the
`RandomShard` command route. In the shipped dark configuration no draw is taken at all, so that
sequence is byte-identical to PRE; when armed, the two share a generator whose distribution neither
depends on.
