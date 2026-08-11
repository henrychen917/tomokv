REORDER AGING BOUND (#87, small): the Shinjuku-style reorder stage
(tomokv-reorder > 0) bounds how far a queued command can be DISPLACED by a
count cap; under extreme sustained load a long command can be displaced
repeatedly and starve far beyond any latency target. Convert the starvation
bound from displacement COUNT to TIME:
1. Find the displacement-cap site (search tomo_rord / reorder displacement /
   the D-design in docs/ABCD_D_DESIGN.md if present). Replace/augment the
   count cap with an age bound: once a queued entry's age exceeds a bound
   derived from the class service-time EWMAs the stage already tracks (e.g.
   K x the slowest class EWMA, or the SLO window the design names — derive,
   do not invent a constant), it becomes non-displaceable.
2. Cost discipline: the reorder path already reads a timestamp per entry
   (the per-cmd rdtsc lesson: reuse the EXISTING stamp, never add a clock
   read); zero cost when tomokv-reorder=0.
3. No new config knob; the bound self-derives. Keep the count cap only if
   removing it changes behavior the tests pin; otherwise the time bound
   replaces it (hardcode-or-delete).
4. Witness: a counter (INFO tomokv_reorder_age_pins or similar) counting
   entries pinned by the age bound.
HARD RULES: WRITE CODE ONLY — never run make/compile, never boot a server,
never benchmark. ./notifyguard.sh invariants — revert none. Minimal diff,
match style. git add -A + commit with WHAT/mechanism/observable.
