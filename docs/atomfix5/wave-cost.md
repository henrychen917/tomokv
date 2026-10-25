# AT4.7 — measure first; performance work reserved for the maintainer

No Task-array optimization is implemented. The source still constructs
Task posts[256] in publish_phase2, publish_pop_retry, publish_sort_deref and
script_post_phase. Task's default member initializers initialize every element,
although only the published prefix is used. This is a static observation, not
an instructions-per-wave or rate measurement.

The lane's runtime authorization explicitly excludes performance benchmarks
and measurement load generators. Consequently the requested per-wave counts at
1, 8 and 64 tasks are NOT RUN here. No measurement result has been supplied in
MEASURE-RESULT. Proceeding with the optimization would violate 'measure first'.

Maintainer request: measure each of the four publishers at exactly 1/8/64
published tasks with a serverless owner-turn fixture using real production
Task queues and counters, or an equivalent supported gate instrument. Publish
one valid wave, consume all its posted tasks, and separate fixed admission and
retirement setup from the sampled region. Count successful waves and actual
published tasks; reject partial/full-queue attempts in this cost experiment.
For each size report instructions/wave, cycles/wave and IPC, with a matched
empty-loop/setup control, repeatable PRE/PRE null, and arm order. A 64-task wave
needs at least 64 shard groups: do not substitute 64 keys on one shard or claim
SMOVE/RENAME themselves can publish 64 second-hop tasks.

If fixed whole-array initialization is material, implement prefix-only object
construction with valid Task lifetimes and no change to pending-reference or
queue ordering. Re-run the identical 12 wave cells, correctness batteries and
generic/multi-key merit cells. Reject an instruction-only 'win' that loses at
matched offered load. PRE/POST/PAD columns remain PENDING for this candidate;
the current WATCH-only POST and PAD do not implement a Task-array alternative.

No source change or gate row for this pending cost experiment: DQ=0, DF=0.
