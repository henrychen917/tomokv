# FLUSH collapse bound and wave 10 integration

## flushfix3

Branch `cx-flushfix3`, starting at `a396a42e5`. No push; landing awaits
the owner's D12 design approval. Work in progress; no throughput claim.

### Idle completion

The actual empty-server defect is a lost wake at the phase-two handoff.
`flush_after_decision` publishes to the cold retry inbox, which is absent from
the IO park predicate. Its conditional wake can miss an IO between its final
retry drain and publishing its parked flag. A real wake event now accompanies
every FLUSH continuation, including fused self-publication. The next IO pass
refreshes completed read cuts before redispatch. Live older cuts still protect
their versions; the cutoff-before-floor eligibility test is unchanged.
No ordinary command or idle-loop path is changed by this fix.

The gate's `flushfix3` job runs FLUSHALL/FLUSHDB SYNC/ASYNC, 1,000 idle calls
per form, in all eight mode/engine/atomic legs, in both database images.
One call above 5 ms fails immediately; passing requires all 1,000 calls.
Original flushfix2 fails every fused leg and passes every split leg. The fix
passes all 64,000 calls. Binary hashes, per-form maxima, counts and compressed
raw observations are in `docs/flushfix3/idle-proof.json` and adjacent files.
An initial negative run was stopped after one complete fused leg demonstrated
438–466 deadline misses per 1,000 calls; its observations are retained. The
completed negative rerun uses the same fail-on-first-miss rule as the fix.

The two new rows are collected before the quick-tier exit: incremental
DQ=+2, DF=+2. Final collection line numbers and combined row counts will be
recorded after the wave 10 merge. EXPECT constants have not been edited.

All builds and correctness children use CPUs 0–15, server CPUs 0–7,
client CPUs 8–15, ports 20100–20199 and LC_ALL=C. Performance measurements
and the full iteration are NOT RUN: reserved for the maintainer.
