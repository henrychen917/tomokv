# PURE-WORKER batched ceiling rig

--pure-worker-rig SECONDS runs a finite foreground measurement of the EX-worker instruction
ceiling. The switch must be argv 1. It is a one-shot process path after initServer() and before
initIOThreads(), so it creates no IO threads, network listeners, dispatch/freeback rings, or CDBs.
The worker path never triggers or drains the main slot's startup notifier.

Each worker owns four pre-generated batches of exactly WORKER_POP_BATCH entries. Every key is
deterministically hashed to that worker, installed quietly in its node's flat table before readers
start, and selected so its flat-table home slot is collision-free. The timed loop rotates those
batches through the same production sequence:

1. exPrefetchBatch(batch, WORKER_POP_BATCH), including the interleaved scoreboard state machine.
2. The production drain/flush/cross-shard classifier branches in issue order.
3. exExecOrdinaryFake(): lookup, atomic version resolution when enabled, command accounting,
   reply formatting, bucket-load accounting, and reply-size EWMA.
4. Reset of the already-allocated inline reply buffer, with no completion publication or IO drain.

There is no scalar per-command substitute and no random choice in the timed loop. Time is sampled
once per 256 full batches; operations, formatted bytes, and resets are derived from batch count so
the rig adds no timed per-op validation counters. All entries are warmed and their exact 23-byte
RESP2 reply is checked before the counters are baselined.

## Invoke

The thread counts are per node and remain required by normal TomoKV topology validation. A flat
table requires at least two EX workers per node:

~~~sh
./src/redis-server --pure-worker-rig 30 \
  --tomokv-thread-mode static \
  --tomokv-thread-io 1 \
  --tomokv-thread-ex 4 \
  --maxmemory-policy noeviction \
  --save ""
~~~

A positive duration forces static topology and foreground/no-supervisor operation before topology
resolution. --pure-worker-rig 0 only consumes the two private argv entries and continues through a
normal boot: it allocates no rig state and changes no server configuration. Normal boots without the
switch have no rig predicate on any worker hot path.

LFU policies are rejected because LFU hit updates call the global random generator from the GET
loop. The maximum duration is 24 hours.

Add --tomokv-atomic yes to measure the version resolver. Seeds are installed uncommitted, acquired
by their owner lifecycle, stamped with one reserved sequence, then published through commit_seq
before the workers start. The intentionally unlicensed single-version hint makes each timed atomic
GET take the real slow resolver; healthy output therefore has atomic_fast=0 and
atomic_resolves=ops.

## Attach perf

READY reports the Linux thread IDs and then leaves a two-second attachment window before START.
The coordinator should parse the comma-separated tids= field and attach to those threads, for
example:

~~~sh
duration=30
log=/tmp/pure-worker-rig.log
./src/redis-server --pure-worker-rig "$duration" \
  --tomokv-thread-io 1 --tomokv-thread-ex 4 \
  --maxmemory-policy noeviction --save "" >"$log" 2>&1 &
server_pid=$!

until ready=$(grep -m1 '^PURE-WORKER-RIG READY ' "$log"); do :; done
tids=$(printf '%s\n' "$ready" | sed -n 's/.* tids=\([^ ]*\).*/\1/p')
perf stat -t "$tids" -e cycles,instructions,branches,branch-misses -- \
  sleep "$((duration + 3))"
wait "$server_pid"
~~~

The duration begins at START, not at process launch or READY.

## Healthy output

A healthy run ends with one WORKER status=ok line per EX worker and:

~~~text
PURE-WORKER-RIG RESULT status=ok ... full_batches=yes ring_pops=0 cdb_notifications=0 io_threads=0
~~~

The proof counters should also show:

- commands=ops, hits=ops, misses=0;
- reply_resets=ops, reply_bytes=23*ops;
- pf_batches=batches, pf_gated=0, pf_slot=ops, pf_kvobj=ops;
- atomic off: atomic_fast=0, atomic_resolves=0;
- atomic on: atomic_fast=0, atomic_resolves=ops.

./notifyguard.sh remains the source audit for the 11 production notification/CDB layout and
batching protections. Its healthy final line is:

~~~text
RESULT: PASS -- all 11 protections intact.
~~~
