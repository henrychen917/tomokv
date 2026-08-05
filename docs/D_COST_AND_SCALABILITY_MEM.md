# The reorder −4 % cost, and what the scalability change actually saved

Two measurements, 2026-08-06, both correcting an earlier imprecise claim.

## 1. Where the −4.3 % came from — and it is NOT the aging

Earlier I attributed the reorder cost to chunked aging ("plain SJF −0.8 %, aging −4 %"). Wrong.
Same-session interleaved A/B (no drift — plain-SJF binary a11585f8f vs current, back to back,
reorder 0 vs 2, p32 GET, 3 reps):

    plain SJF     L0 7118k → L2 6837k   = −3.95%
    chunked aging L0 7135k → L2 6874k   = −3.66%

They are the same. Aging adds nothing measurable. The ~4 % is the **reorder's inherent cost** —
staging into the scratch, the O(r×4) emit, the dependency-guard scan — on a box where the reorder
has no benefit to offset it. The earlier "−0.8 %" was a lucky fast-day interleaved run; ~4 % is the
honest number.

**Is it "fixed"?** There is nothing to fix in the code. The trace regression I worried about was
never real: the trace is now a zero-cost armed dry-run, and removing it did not move the number
because it was never the cause. The 4 % is the price of running the reorder single-CCD, and the
reorder is **default-OFF**, so shipped throughput is unaffected. Multi-CCD is where the stall-hiding
benefit is supposed to exceed this 4 %.

## 2. Scalability memory: struct/virtual, NOT resident — the payoff is cap-enablement

Measured `sizeof(exThread)` (heap-lanes build) and computed the inline equivalent:

    lane size (exQueue 16512 + freebackRing 8320)      = 24 832 B  (~24 KB)
    sizeof(exThread) INLINE  (queues[33] + freeback[33]) ≈ 802 KB
    sizeof(exThread) HEAP    (two pointers + nlanes)      = 1 728 B  (~1.7 KB)

So the struct shrank ~800 KB → 1.7 KB per worker; the lanes moved to a heap block sized to the
runtime count (io+ex+1 = 9 lanes at io4ex4, vs 33 inline).

**Resident memory (RSS): unchanged (~0 saved).** Measured io4ex4 and io8ex8: inline vs heap RSS
within noise. The inline lane arrays are `zcalloc`'d anonymous zero-pages — the kernel never faults
in a page until it is written, and only the active lanes (io_threads+1) are ever written. So the
unused inline lanes were never resident, and both builds touch the same active set. My earlier
"saves 2.4 MB" was **virtual** address space, not resident, and even that (~2.3 MB at io4) is
noise-level in VmData against jemalloc's arena reservations.

**The real value is CAP ENABLEMENT, and it is not visible at cap 32.** With inline lanes, raising
`TOMO_IO_THREADS_MAX` to 128 would make `sizeof(exThread)` = 129 × 24 KB ≈ 3.1 MB **per worker**,
and `zcalloc(3.1 MB × num_workers)` — the compile cap MULTIPLIES the struct for every worker, even
a 4-thread boot. Heap-sizing to the runtime count means cap 128 costs the same as cap 32 at a given
thread count. That is the win the change bought; it is realized when the cap rises (blocked on the
two remaining >64 walls — ex_dirty_mask and the QSBR io_snap mask, task #66), not now.

## 3. q_summary communication gain: unmeasurable at current caps

The two-level summary (q_top + q_summary[QS_WORDS]) preserves the O(non-empty) dispatch property —
idle pass = one exchange, exactly as before. But `TOMO_QS_WORDS == 1` at cap 32/64, so it
**compiles to the original single-word path**: there is no communication change to measure until
the cap exceeds 64. The fix it also carried (lanes ≥ 64 could never be advertised — a silent 64×
dispatch-delay cliff) is likewise a >64 property. Both are correct and ready; both are cap-gated.

## Honest summary

The scalability work was **enabling, not a current-config win**: it removed the
memory-multiplication and the dispatch cliff that made raising the thread cap prohibitive. At
today's 32/64 caps and single-digit thread counts, the resident memory is unchanged and the
communication path is byte-identical. The payoff lands when the caps rise — same regime (many
cores) where D's reorder and the flip controller's finer granularity also start to matter.
