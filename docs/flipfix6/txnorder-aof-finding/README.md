# Separate finding: fused epoll AOF storm timeout

The POST epoll supplement recorded `txnorder-fused-1` as FAILED. Its ordinary
rows a/b/c passed; the fresh AOF boot for row d returned
`FAIL d TimeoutError('timed out')`. Ordinary SIGTERM cleanup then aborted with
`database worker shutdown timeout elapsed_ms=2703 grace_bound_ms=900 stage=0 request=0`.
Geometry: CPUs 32-39, load CPUs 40-47, 8 fused threads, 16 shards, read-local 1,
atomic 1, databases 16, epoll, AOF enabled / appendfsync no, and FLIP/key-LB/client-LB
all disabled. LC_ALL=C. Original logs and the failed ledger are retained here.

The unchanged PRE e32b04a44 arm reproduced **both signatures** on trial 04-PRE
of a bounded, alternating PRE/POST diagnosis. The same `tests/txnorder.py --only d`
ran against fresh boots with the gate's exact effective options. GDB launched
the unchanged binaries, with no breakpoints, stepping or injected production
code; on test completion the harness sent ordinary SIGTERM. The failure's abort
was the server's own shutdown check (no manual SIGABRT). There was one failure
in eight PRE trials and zero in eight POST trials. These counts describe this
small correctness diagnosis; they are not an estimate of failure probability.

The PRE abort trace shows:

- two workers retrying commit-chunk publication in `aof_commit_group`,
  `src/persist/aof.cc:1233`, from EXEC and a cross-shard mover;
- another worker in `ReadLocalDeferredQueue::force_oldest_grace`,
  `src/core/read_local.h:408`, reached by ordinary INCR immutable replacement;
- the other workers waiting in `AofManager::worker_shutdown` after SIGTERM.

`src/persist/aof.cc`, `src/core/read_local.h`, `src/store/flatstore.h`,
`src/cmd/t_string.cc` and `src/cmd/multi_execute.inc` are unchanged relative to PRE.
The stack suggests AOF publication/backpressure interacting with reclamation,
but it does not establish the complete dependency cycle. The original POST
abort has no thread trace, so exact cycle identity is not claimed. The same
failure class demonstrably exists on PRE, in a mode where FLIP is unavailable.
No transaction, persistence or reclamation change is made by this lane to address it.

Four native repetitions of the exact gate job then passed: PRE 2/2 and POST
2/2, without a debugger. The full job also reruns ordinary rows a/b/c and armed
validation before its fresh AOF row d. Commands, exit codes and durations are
in `../txnorder-native-recheck.json`; the four ledgers and evidence archives are
retained alongside it. These passing retries do not turn the original failed
row green.
