# Readiness change within IoDrain

Review of the first POST found a cold-control race. A full socket on a surviving
IO can pass `flip_io_drained()` as stationary even with an outstanding send and
borrow. If its peer reads before `flip_output_hold()` polls again, the second
poll is writable. The old hold helper could abort on the kernel send pointer,
or pin a borrow-bearing client as movable and prevent its drain.

The new core fixture fills a nonblocking socketpair to EAGAIN, proves that the
full socket passes initial drain with a real borrow and an in-flight-send marker,
drains every socket byte at the peer, proves the classifier changes to writable,
and then invokes the production hold helper. The old helper aborts (SIGABRT,
see readiness-negative.json and its backtrace). The initial fixture checked the
candidate role instead of the final role for a survivor and failed before this
window; that first result is retained separately and is not a negative witness.

The fix preserves the already-accepted stationary decision from unchanged
IO-owned send/output state. Only socket readiness may change between those calls.
There is no new socket pin, old-ring send, per-command hook, timeout or mask change.
The fixture requires unchanged serve ownership, a counted output skip, deferred
borrow routing, exact one-time borrow release, and rollback without a synthetic
serve. It runs for both database configurations in the existing sanitizer row.

The interrupted broader regression campaign is superseded; its AOF cancellation
failures are retained and are not independent server failures. Final validation
must use the rebuilt candidate.
