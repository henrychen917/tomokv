Measured stall map (dev @2f80ef045, get_p32 2M saturated, perf DRAM-fill attribution):
REPLY PATH is the largest memory-stall bucket: _addReplyToBufferOrList 21.5% + addReplyBulk 7.7%
+ .part 3.1% of DRAM-fill samples, plus the bulk of 2.08B cross-core (local_ccx) fills — the
worker's reply-byte writes land in lines that ping-pong with the IO drain. ull2string/ll2string
add 16% (formatting into the same cold buffers). flatFindForWrite (the data probe) is 28% and is
already addressed by storage prefetch. Frontend stalls are 21.4% of cycles.
