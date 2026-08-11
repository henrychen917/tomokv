# ROUND 4: two exact fixes — batch clock for FAST, and the second prefetch stage

Round-3 measured vs the current dev stack (pendiet+clockdiet+pgo-harness):
io7ex1 p32 GET **-13.5% (3/3)** (was +3.6% before clockdiet merged), qc44 SET -0.7% (3/3),
40M SET improved -7.3% -> **-3.6% (3/3)** but not healed. Two causes, both identified:

1. **FAST entries fight the merged clock diet.** exExecFast pays TWO raw clock reads per
   command (tomoCmdClockEnter + getMonotonicRaw at exit — see the "recorded follow-up" comment
   at its entry). The ordinary path (exExecFake) amortizes via the pop loop's batch-boundary
   raw (tomoCmdClockEnterAt(entry_raw), exit_clock chaining). Thread the SAME batch raw through
   exExecFast: pass entry_raw (or the loop's chained exit_clock) into it, use
   tomoCmdClockEnterAt, and let its exit stamp chain to the next entry exactly as exExecFake's
   does. At io7ex1's 4M+ cmds/s/worker this is the entire -13.5%.
2. **The 40M heal is half-done.** Your slot-line prefetch landed, but the ordinary path's
   PFS_KVOBJ second stage (kvobj line after the tag gate) has no FAST analogue — at 40M each
   FAST op still eats the kvobj miss serially. Add the second stage: after the slot line
   arrives (next batch iteration, AMAC-style like exPrefetchBatch), tag-gate and prefetch the
   kvobj pointer's line. Same L3 footprint gate, same counters.

Everything else stays byte-identical. WRITE CODE ONLY; never run make/compile/servers/
benchmarks. Commit clean; I battery vs the dev stack with acceptance: io7ex1/qc44 return to
their pre-clockdiet relative wins (+3.6%/+0.5% class), 40M SET/GET at parity-or-better.
