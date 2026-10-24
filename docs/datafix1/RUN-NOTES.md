# datafix1 proof history

The final server SHA is b05021db6b4f7369b0cad5b7009b8a1918332860f92b03f029394c23e4d61dec.
Final directed proof uses {pre,post}-linear-directed; final POST production proof
uses post-linear-units. Earlier final/post-serial prefixes refer to earlier stages.

- PRE io_uring feature-split-1 tracking.py failed once with flags `[on]` instead of
  `[on, broken_redirect]`, redirect 807. Exact receipt: pre-existing-uring-proof.tar.gz,
  jobs/feature-split-1/gate-tracking-1.txt; extracted observation in
  pre-tracking-observation.json. This differs from the supplied DIFF-TRK-1
  duplicate-invalidation mark. All corresponding later POST legacy rows passed.
- Two early gates_test.py runs overlapped other work and exceeded a 45-second
  scheduler-fixture timeout in different fixtures. The serial run passed all 67.
  Neither assertions nor deadlines were changed; original logs remain.
- Early concurrent differential coordinators hit a 900-second row deadline or
  were stopped to remove contention. Their archives explicitly say LANE INTERRUPTED.
  They are not complete matrix passes.
- The first engine wrappers placed --net-io before a config filename, breaking
  servertail's config-file boot. Wrappers now preserve argv[1] and respect explicit
  engine arguments. post-serial-epoll records the two failures; later reruns pass.
- The PRE SPOP battery executed all six legs and recorded real assertion failures,
  then its JSON summary writer rejected bytes inside tuple failure details. The
  writer now applies the existing RESP serializer to unsupported JSON values.
  Both final directed arms have complete summaries and no driver exceptions.
- A preliminary PAD coordinator started before its wait-PID file existed. The
  gate's port guard refused it before any server boot. The refusal and helper
  error are retained in pad-coordinator-refused-* and tail-coordinator-refused.log.
- A final cost audit found integer_at's hidden offset searches in counted SPOP.
  It now decodes entries already visited. The intermediate epoll differential
  coordinator was stopped and archived as post-epoll-differ-before-linear; its
  successful prefixes are not final-binary proof. All final differential arms
  restart from the same recorded standard seed state (7,19,20,23 plus 25), including
  the interrupted intermediate run's seed 25. The older concurrent attempts used
  rotating seeds 21,22,24; those incomplete runs remain archived. All final arms
  use the gate's complete standard suite and the same frozen seed manifest; no
  assertion or deadline was relaxed.

All proof archives contain gate-owned logs, plans and reply/coverage evidence.
Large native snapshots, binaries and object files are excluded from those archives.
PRE production fixtures were pruned only after passing and recording freshness;
production objects and the PRE/PAD binaries remain available. Full iteration and
performance instruments are intentionally not run in this correctness lane.

The existing differential console label says "all 32 execution/knob combinations".
The frozen mode-equivalence stream and completion artifact declare 16 cells
(2 modes x 2 read-local x 2 reorder x 2 atomic), each with separate replay and
witness boots, for 32 owned server lifetimes. This report counts 16 cells.

Final proof completed: all four standard differential arms pass their exact 938-leg
inventories, 16 mode-equivalence cells and both strict folds. DIFF-TRK-1 was not
observed. The PRE globcase follow-up completes matched io_uring legacy coverage;
the sole matched PRE legacy failure remains the broken_redirect observation above.
The final quiet gates_test.py rerun passed 67/67.

PAD-A completes all 60 directed legs and all 29,328 checks, failing assertions in
every leg without exceptions. A few atomic-0 fused LMOVE/RPOPLPUSH encoding
mismatch counts vary from PRE; see pad-list-variance.json for exact differences
and the source-based randomized-routing explanation. Unchanged PRE object hashes
remain the primary behavior-control provenance.
