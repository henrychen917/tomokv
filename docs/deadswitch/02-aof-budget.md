# 2 — AOF writer batch: LIVE on the syscall engine; retained

PRE `dab740964` and two literal-mutant production binaries are built under
`build/deadswitch/{pre,aof-1,aof-4096}/tomokv`. `build_aof_arms.py` reproduces
them: all PRE objects are retained except the two AOF objects, whose literal is
changed to 1 or 4096. Compiler/link commands and logs are retained. No production
selector, compiler-budget change, or configuration field is added.

The serverless witness links **actual production objects** and calls the real
`writer_pass`. It queues 384 GCMT chunks behind an undecided dependency so each
admission consumes the real pass budget, with no disk submission, initialized
io_uring, listener, worker, timer, or load generator. Missing arming, a wrong
consumed count, a lost chunk or an AOF error fails the test. Running the budget-1
arm with the PRE expectation fails, demonstrating that this is not a passing
test of a grep result.

| Engine / pass | Budget 1 | PRE (16) | Budget 4096 |
|---|---:|---:|---:|
| epoll / ordinary | 1 | 16 | 384 |
| epoll / drain_all | 256 | 256 | 256 |
| uring / ordinary | 256 | 256 | 256 |
| uring / drain_all | 256 | 256 | 256 |

The directed budget witness also passes in `tomo_db0` for all three arms.
The unchanged serverless persistfix ack/remote/shutdown/refusal cases pass on
all three budgets; all nine existing clause-deletion controls fail at their
named assertions. PRE and 4096 pass the frame-order suite. **Budget 1 fails**
its first-pass arming check (`ready GCMT and OPEN large record coexist`), because
the fixture assumes several chunks are consumed in one pass. This failure is
retained in `02-persistfix-schedules.json`; the fixture was not weakened, skipped,
or relabeled as a successful recovery test. `persistfix_arms.py` reproduces all
24 schedules and records that distinction explicitly.

This proves scheduler liveness, not disk recovery or performance. The requested
live `aof-epoll`, `aof-uring`, and persistfix recovery batteries have **not run**:
the task's request to run them conflicts with the shared no-server/no-gate rule,
and clarification was requested. Exact maintainer commands belong to the root
measurement request. No live result is inferred from the serverless witness.

Both mutants preserve **1492/1492 hot bodies and 17076/17078 total bodies**.
The only changed emitted bodies are `AofManager::writer_pass` in `tomo` and
`tomo_db0`, each 1144 -> 1144 bytes. The immediate `mov $16,%edx` becomes
`mov $1,%edx` or `mov $4096,%edx`; the engine/drain selection and all relocation
targets remain unchanged. The disassembly shows the shared runtime function,
so an entire-function claim of “uring bytes identical” would be false: the
changed immediate remains in the shared body, although uring's selected budget
is always 256. Both namespaces are in the complete inventories.

**Action: no deletion, no unmeasured retuning.** A single `aof-writer-batch`
control shared by both engines (including the uring reserves) is the appropriate
follow-up after the requested recovery runs and choice of default/auto policy.
That unification is not landed by this receipt. Replacing the live syscall
budget with 256 merely to remove a name would change behavior already witnessed
here. Gate rows +0/+0; production POST for this candidate remains PRE.
