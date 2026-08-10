OWNER ADDENDUM (2026-08-10): the IO-side cross-node prefetch must cover the REPLY PAYLOAD
BUFFERS, not only the CDB descriptor lines. On multi-CCD the drain loop's copy-to-socket is a
serial cross-die fetch of every reply line the worker wrote (the same bytes measured as the #1
worker-side stall bucket, now paid again on the IO side). Design constraints:
1. TWO-LEVEL PREFETCH, pipelined like exPrefetchBatch: while copying completion N, prefetch
   completion N+1..k's descriptor lines AND the payload lines they reference.
2. NO POINTER CHASE IN THE PREFETCH: the CDB descriptor must let the drain compute payload line
   addresses by arithmetic (base+offset+length already in the descriptor or added to it within
   its existing line budget — notifyguard's one-line-per-worker CDB invariant must hold). If the
   descriptor cannot name the payload address without a dependent load, prefetch the descriptor
   one step earlier so the dependent load is warm by the time it runs.
3. Same topology gate as the rest: in-node = byte-identical current path; only marked-remote
   workers' completions get the payload prefetch.
4. Witness: count payload-prefetch issues separately from descriptor-prefetch issues.
