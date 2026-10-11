# Acceptance blocker: D10 and writer marks form a cycle

The requested design has a wait cycle. This is a deterministic owner-turn
reproduction using the real claim and writer predicates, with no worker,
listener, clock race, benchmark or gate. It is an acceptance blocker, not a
passing transaction test.

Use two shards, with a on shard 0 and b/c on shard 1. U is older than V.

1. U places its claim on a; it will also need c.
2. A temporary executing unit H holds c. Plain local MSET(b,c) W is blocked
   by H and leaves a writer mark on c. H then decides and retires its claim.
3. V places and validates WATCH b on shard 1; it also needs a on shard 0.
4. W polls again, is now blocked by V's validation of b, and retains c's mark
   until W passes (design §2.6). It adds a mark on b.
5. V waits on older U's a. U waits on W's mark on c. W waits on V's validation
   of b. None is runnable and there is no conflicting U/V claim on shard 1
   where U could wound V.

The cycle persists through 64 explicit owner turns. `blocked-only-result.json`
reproduces it with a per-blocked-key implementation of the design. `result.json`
records the earlier, shorter reproduction when all touched keys were marked;
that broader marking has since been removed from production to match §2.6.
The final production reproduction is recorded separately as `final-result.json`.

`proposed-rank.patch` is a **proposal, not applied to production**. It stamps a
writer mark once using an existing otherwise-unused field, and lets a unit
whose retained version predates that mark complete placement. Newer units keep
waiting. The companion `ranked-result.json` demonstrates the cycle breaking
and a newer arrival staying behind the writer. Validation still blocks writers
from validation, so D10 is preserved. This needs an explicit amendment to
§2.4's unconditional writer-mark wait rule, a new full wait-graph review,
starvation proof and final-tree rebuild/cost/runtime proof. The fixture alone
is not acceptance evidence for the proposal.

The owner was asked to choose the ranking amendment or retain the design with
this blocker recorded. No answer has been assumed.
