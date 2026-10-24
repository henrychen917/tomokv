# Wave 6 landing

## wave6 integration

Integration branch `cx-wave6`, headline `ef5204b2e`; no push. Work is in progress.
All builds and correctness work are restricted to CPUs 64–95, ports 26800–26899.
No performance generator or full iteration is authorized or run by this lane.

The six reports were read before their branches were merged, in the requested order,
with `--no-ff`: execfair, notifycompat, serverfix, dispatchfix, datafix1, prefetch.
Final branch states, including maintainer commits, are retained.
The writers-first information switch and executable POST-ALT plumbing are deleted;
historical receipts remain attributable. The supplied prefetch DELETE patch applies
without modification. Full-file equality to its isolated source conflicts with
retaining execfair/serverfix changes in the same files; prefetch-only equality is
being checked while preserving the integration (clarification pending).

### Row accounting

Headline 739/756 plus execfair 1, notifycompat 8, serverfix 8, dispatchfix 5,
datafix1 7, prefetch 0 gives **DQ=+29, DF=+29; required counts 768/785**.
`EXPECT_QUICK` and `EXPECT_FULL` remain 739/756, untouched. The fixture has all
785 declared full labels with their multiplicities; dispatchfix's five missing
fixture entries were added explicitly. Final collection line numbers and the
quick-tier exit will be recorded after the integration changes.

### Merge decisions and interaction audit

- OBJECT: retain notifycompat's non-touching/non-notifying lookup for all children;
  it also preserves dispatchfix's missing-key-before-policy precedence.
- XGROUP: dispatchfix moves option validation before lookup; its moved parser already
  contains wave 5's canonical ENTRIESREAD parser and exact negative-value error.
  The duplicate old parser was removed; wave 5's other stream fixes remain.
- CONFIG: retain serverfix's whole-parameter-list validation and enum parser;
  add datafix1's locale validation and publication. `Config::locale_collate` consumes
  eight additional reserved bytes after wave 5's hz fields; existing fields stay put.
- First merged build caught datafix1's static BITFIELD bound referring to the
  configuration range widened by wave 5/netfix. The assertion now uses the actual
  representable storage limit. The CD4.10 row additionally configures LONG_MAX and
  checks both sides of that limit without allocating a giant value; all legs pass.
- Slowlog: recorder creation already follows the threshold. Serverfix additionally
  moved a max-length atomic load onto every exact recording attempt; moving that
  load after the threshold is the targeted fix. Recorder lookup/creation and identity
  capture still precede Done. SV4.14 passes every leg, including a new armed but
  below-threshold GET/SET/INCR allocation snapshot and the existing enable/disable
  and negative-control legs. The recording helper's fast trace is 75 instructions
  in the headline, 78 in the initial merge, and 75 after the fix.

### Semantic pair review

- EXEC scheduling / scatter notifications: promotion changes which owner-local
  unit is retried, not when its fragment executes or decides. Pinned blockers
  retain their epoch/abort/reference lifetime; clearing them accompanies final
  reservation release. Scatter and MULTI notification batches remain attached to
  their operation, and publication/retirement follows the existing decision.
  `job_execfair` now runs `wave6_exec.py` in all eight mode/atomic/engine legs.
- EXEC / encoding transitions: list repacking and SPOP's set transition remain
  in the owner command handlers under the existing atomic replacement scopes.
  The new check runs LTRIM and SPOP across two actual owners inside EXEC, checks
  both encodings and exact remaining data, and rejects duplicate popped members.
- EXEC / container ACL: queued child validation and the execution-time ACL
  recheck remain before the child handler. The directed check covers missing
  XINFO precedence, an allowed OBJECT child, a denied child, and EXECABORT.
- Lazy logs / wave 5 / teardown: below-threshold recording never reaches the
  lazy recorder or directory fallback. The client catalog registers on its IO
  thread and protects cold snapshots/mutations with the existing catalog mutex.
  Published recorder/ACL stores survive CONFIG disable/reset and are reclaimed
  only at static teardown, after worker joins. The existing completion unit
  checks cover identity capture before Done; broader shutdown jobs remain due.
- Uniform buckets / persistence / balancing / read-local: the router and shard
  range construction share the floor-map/inverse-ceiling boundary. Balancers
  move those ranges rather than reconstructing the old quotient mapping;
  read-local and DEBUG SHARDS use the router. Non-divisor persistence uses a
  versioned map, and v1 recovery filters overlapping old sections into the new
  owner ranges. The router job passes its legacy snapshot/AOF recovery legs.
- Notifications / tracking / blocking: key-miss records are excluded from
  invalidation; real mutations retain the batch tracking stamp. Redirect failure
  acknowledgments carry their tracking configuration generation and cannot
  disarm a replacement configuration. Expired-store completion retains its
  publication-chain lifetime. The new EXEC check requires exactly two ordered
  changed-bit notifications and no no-op SETBIT event, then wakes an observed
  BLPOP waiter exactly once. All eight legs pass.
- Prefetch / execfair: DELETE removes only the unused fallback walk and its two
  calls. The fused owner walk and stale-task ownership check remain. Fast-unit
  service and pinned-blocker lifetimes do not depend on the removed hint walk.

These reviews found one source-level integration defect (the BITFIELD assertion)
and compiler propagation into ordinary integer replies. Moving WAIT's reply out
of the parser removed main.o's rvalue integer-reply template, selecting xshard.o's
smaller weak definition and adding 11 instructions to INCR. An explicit template
instantiation restores the headline definition without changing the formatter.

The first combined row run was **29 pass / 1 fail**, counting its release
prerequisite: all lane assertions passed, but one EXEC split/epoll pre-teardown
dump observed a locally closed connection whose EOF had not yet been handled.
The integration check now half-closes and requires server EOF before returning;
the unchanged shutdown assertion then passes in the complete eight-leg EXEC job.
No sleep, relaxed bound, skipped witness, or EXPECT edit was used. All 29 newly
added rows have a passing complete-job execution on the current candidate.

### Validation status

Still in progress: broad touched-job correctness, final instruction/provenance
matrix, PAD-A, and final freshness. The initial compile failure is retained in
`build/wave6/build-initial.log`; it is not a validation pass.
