## aofblock

Base: `7595a6705`; release control: `/home/user/Projects/bins/readability-pre-5c363128/tomokv`.
S1 durability fix only. No push or throughput runs. Correctness CPUs 56–83,
ports 25800–25899, every boot `LC_ALL=C`.

### Completion ownership audit

* `Op::reset` (`src/exec/op.h:118`) initializes Free. Blocking dispatch publishes
  the ROB range without changing it. The old Issued comparison cannot claim it.
* Wake/timeout/error selection has a phase CAS: `blocking.inc:987` (timeout),
  `1023` (removed group), `1139` (wake), `1206` (probe), `1245–1277`
  (registration), `756` (registration OOM). Moves transfer to scatter instead.
* `blocking_publish_completion` publishes Completed and checks active_tasks;
  `blocking_task_done`'s final fetch_sub observes it. Either may offer completion.
  Free→AofWait now claims exactly one pending entry. Losers see AofWait/Done and
  do not notify or enqueue. `AofManager::finish_completions` detaches the batch
  before publishing Done and notifying (`aof.cc:3115–3122`).
* The one-liner is insufficient for cancellation: `blocking_task_done:524–529`
  can see cancel_requested after a mutation and choose cancellation instead.
  `blocking_finish_cancelled:512–518` previously tested AofWait then exchanged
  Done; another completion could claim between that load and exchange. Owner-side
  cancellation now uses the same Free→AofWait claim. The null-self IO cancellation
  is restricted to exclusively handed-over MoveRequested/RemapRequested
  (`blocking_cancel_client:1882–1890`), where no direct pop can execute concurrently.
* Disconnect only requests cancellation and dirties/wakes owners (`1863–1893`).
  Registry cleanup releases its alias reference (`1080–1087`), while the Op keeps
  its reference until `blocking_retire:1907–1945`; AofWait pins that ROB slot and
  Client. Registry cleanup of Completed is not a second completion.
* Empty/error completions do not need a new record. `finish_completions:3060–3104`
  publishes each producer's existing buffered generation and snapshots a finite
  dependency set once. `ex_loop.h:1902–1921` visits completion queues even with no
  staged record. A zero target completes immediately; existing targets wait for
  durability. Failure is fatal under Always, not an indefinitely held success.

### Verification in progress

PRE built in `build/aofblock/PRE`. Free-state competing-owner unit and the fused
epoll BLPOP crash/recovery test pass. Full evidence and final row delta follow.

Current new rows: nine cases × two thread modes × two engines = +36 quick/+36
full, collected before the quick-tier exit. EXPECT constants and the reviewed
label fixture are deliberately unchanged; the maintainer owns their update.

### Measurement request

The maintainer runs ABBA and the layout control after correctness proof. No
performance claim is made by this lane. Final arm paths and symbol audit follow.
