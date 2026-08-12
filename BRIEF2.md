# ROUND 2: self-gate the batched completion word to LARGE batches only

Your batched CDB completion word (HEAD) measured io7ex1 p32 +15% GET/SET (3/3) — big win where
one worker publishes a concentrated completion stream — but io4ex4 p32 SET -0.6% and 40M GET
-0.7% (3/3): the extra drain-side summary-word read costs when per-CDB batches are SMALL (4
workers spread completions thin). Make it self-gating, no new knob:
- The worker already knows its pop-batch size N (sig_n / the loop count). Publish via the
  SUMMARY WORD only when N exceeds a threshold derived from existing state (e.g. N >=
  WORKER_POP_BATCH/2, or N >= 4 — justify from the pipeline/batch constants in a comment); for
  a SMALL batch, fall back to the ORIGINAL per-slot status-byte publish (bit-identical to
  pre-your-change), and the drain must detect which form was used (a per-batch/per-CDB flag or
  a sentinel in the summary word) and take the matching read path.
- Net effect: io7ex1 (large batches) keeps the summary-word win; io4ex4/40M (small batches) pay
  ZERO — they run the original path. Witness: add a per-worker counter of summary-word-publishes
  vs per-slot-publishes so the battery can prove the gate splits by regime.
Keep every completion-bus invariant and notifyguard honest. WRITE CODE ONLY; never build/test/
bench. Commit clean.
