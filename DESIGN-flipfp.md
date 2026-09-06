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
