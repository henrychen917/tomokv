**atomfix2 — repair the AT1/AT2 live battery, 2026-10-03**

Worktree/branch: `/home/user/Projects/cx-atomfix` / `cx-atomfix`.
Launch HEAD: `bb34726854065d6f4d567bf0907e322bc634389f`.
First operation: `git fetch origin cpp && git merge --no-edit origin/cpp`.
Fetched `b47544aad6cb8a81f835f54145b2387beade0bc7`; merge committed as `ad90e115c`.
Resolved the gate/fixture conflicts by retaining both atomfix labels and the incoming
HEXPIRE regression, and preserving the launch count constants. Battery fix: `870dd58e8`.
Nothing pushed. No server, live battery, benchmark, or gate was run. Builds and executed
serverless checks were pinned to CPUs 112–127.

The immutable-knob failure is fixed in the harness. Both production serverless arms pass;
the ten frozen PRE controls still fail at their named assertions. **Live POST/PRE validation
is pending mainline**, as required by the addendum. No live PASS is claimed.

**Diagnosis and change**

Both supplied `atomfix-gate-atomic-plain-{0,1}.txt` logs show the production unit passing and
the Python battery failing before any live race. The first invalid operation is
`CONFIG SET key-lb 0`; the cleanup path then repeats the invalid SET.
`src/cmd/t_server.cc:344` registers `key-lb`, `client-lb`, and `flip-auto` with
`immutable=true`; `:616` rejects their runtime mutation. `src/core/config.h:851` implements
their existing `--name 0|1` boot grammar. `atomic` is mutable, but this battery now verifies
the boot's value instead of changing it. No mutability or knob grammar was changed.

* `tests/gate.sh:1635`: `job_debug` boots with the existing `--atomic $AT
  --enable-debug-command yes` plus `--key-lb 0 --client-lb 0 --flip-auto 0`. Stable owners
  are therefore provided by the boot rather than attempted runtime changes.
* `tests/atomic_plain.py:74`: `verify_boot` uses only `CONFIG GET` and fails before any race
  on the wrong mode or balancer setting. There are no configuration writes or restores
  anywhere in the live path.
* `tests/atomic_plain.py:83`: all delay hooks are reset on cleanup, including COMMIT-DELAY;
  every reset is attempted, the admin connection is closed, and a reset failure does not
  replace an existing data/arming error. A cleanup failure on an otherwise successful run
  remains a failure. OFF-HOP and COMMIT-DELAY are existing aliases of the same word
  (`src/cmd/t_server.cc:1076`).
* `tests/atomic_plain.py:234`: the existing four-attempt bound is retained, with a fresh
  `Race`, keys and connections each time. Only `WindowMiss` is retried. Wrong data, stale
  cuts, and lost replies remain terminal. There is no skip or widened deadline.
* `tests/atomic_plain.py:285`: `--self-test` runs eight serverless harness tests. Both
  existing gate rows now run this self-test, the real-owner unit, then the live battery.
  This adds no gate rows.

The five original newest-cut fixes and diagnostic are unchanged by this follow-up.
The six calls remain at `scatter_engine.inc:3103,3137,3308,3343`, `blocking.inc:628`, and
`atomics_glue.inc:1019`; all supply `UINT64_MAX`. The first five were the corrections.
The diagnostic remains `atomics_glue.inc:32` / `DEBUG ATOMIC-PLAIN-STALE-CUTS`
(`t_server.cc:1059`). The original proof and caller audit are in `MEASURE-REQUEST-atomfix.md`.

The stall-doctrine explanation still holds: a resumed pop mutates one selected key on its
owner and may consume that key's newest committed version. The resolver excludes foreign
undecided/aborted versions, and a group's shared committed epoch is published only after
its installs. This does not combine different cuts into a multi-key read. Immutable
predecessors, older readers' cuts, and session-order gates remain intact. Waiting for an
unrelated client's reservation to advance the safe watermark would impose cross-client
ordering without protecting a torn read or RYOW. Source:
`/home/user/.claude/projects/-home-user-Projects/memory/tomokv-atomics-stall-doctrine.md`.

**Window audit and serverless proof**

The live assertions remain mandatory:

| Window | Required evidence before a round can pass |
|---|---|
| Held EXEC (`atomic_plain.py:138`) | `atomic_exec_read_cuts` advances and its reply is still pending |
| AT1 (`:157`) | Source removal observed; mover and held EXEC pending both before and after the acknowledged destination write; exact final members; zero stale cuts |
| AT2 (`:190`) | Waiter registered; push acknowledged; blocker and held EXEC pending; `atomic_commit_windows` advances; exact pop reply and surviving element; zero stale cuts |

`atomic_commit_windows` advances when a publisher observes another open commit bracket
(`src/core/server.h:2725`). Here the wake push/resume run on one owner while the unrelated
EXEC holds the other. The 30 ms sleep is only scheduling assistance; it cannot substitute
for the counter and pending-reply witnesses. Four misses fail at
`window never opened after four fresh attempts`.

The self-test drives the actual mover/blocking bodies with correct data replies while
individually removing each pending-reply or commit-counter witness: all **24** missing-witness
cases must raise `WindowMiss`. Nine positive fixtures check that the correct replies with
all witnesses can pass. Other controls verify bounded fresh attempts, absent probe progress,
fatal data/reply errors, boot mismatches, and cleanup errors. Socket creation is forbidden
inside the self-test; these are harness checks, not simulated database correctness results.

Recorded checks:

```text
taskset -c 112-127 make -j16 all build/atomic-survivors-unit
exit 0 (build/atomfix2-build.log)

taskset -c 112-127 python3 tests/atomic_plain.py --self-test
Ran 8 tests in 0.039s
OK

POST plain_0: exit=0
  PASS AT2 six blocking pop kinds, atomic=0
  PASS AT1 SMOVE
  PASS AT1 LMOVE
  PASS AT1 RPOPLPUSH
  PASS AT1 LMPOP
  PASS AT1 ZMPOP
  PASS AT1 MSET
  PASS AT1 DEL
  PASS AT1 UNLINK
PASS plain_0
POST plain_1: exit=0
  PASS AT2 six blocking pop kinds, atomic=1
PASS plain_1
```

Logs: `build/atomfix2-self-test.log`, `build/atomfix2-post-proof.log`.
The build retains all layout locks: Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. Existing unit-harness allocator
warnings remain. Python syntax, `bash -n tests/gate.sh`, and `git diff --check` passed.
No io_loop.h, wb.h, or reorder.cc source was changed, so the conditional writeback witness
is not triggered. No layout change or performance claim; no PAD arm is requested.

Two kinds of negative control were executed, all serverless:

```text
OLD setup atomic=0: expected failure at CONFIG SET key-lb: ERR parameter is immutable at runtime
POST setup atomic=0: PASS, configuration unchanged, connection closed
OLD setup atomic=1: expected failure at CONFIG SET key-lb: ERR parameter is immutable at runtime
POST setup atomic=1: PASS, configuration unchanged, connection closed
witness omitted: expected self-test exit 1 at test_correct_data_without_each_window_witness_still_fails
retry exhaustion ignored: expected self-test exit 1 at test_unentered_window_fails_after_four_fresh_attempts
```

`build/atomfix2-harness-controls.py` loads the actual launch-HEAD Python source against a
protocol double that permits mutable atomic SETs but rejects immutable SETs. It also removes
the window check or exhaustion error in disposable in-memory copies of the current battery;
each must fail its named self-test. Production source is not changed. Transcript:
`build/atomfix2-harness-controls.log`; detailed failures: `build/atomfix2-control-*.log`.

The **database lost-update** negative control comes from the retained real-production
serverless PRE unit, not the protocol double. Its source twin reverts exactly the original
five cut expressions and retains the counter/tests (`tools/atomfix_controls.py`). Re-ran all
ten named cases, requiring exit **1** and the exact assertion text:

| PRE cases | Required failure, observed |
|---|---|
| `plain_SMOVE_0` | `AT1: SMOVE preserves the acknowledged destination write` |
| `plain_LMOVE_0`, `plain_RPOPLPUSH_0`, `plain_LMPOP_0`, `plain_ZMPOP_0` | `AT1: phase-two RMW preserves the acknowledged write` |
| `plain_MSET_0` | `plain write stale-cut counter is zero` |
| `plain_DEL_0`, `plain_UNLINK_0` | `DEL/UNLINK counts the newest committed key` |
| `plain_blocking_0`, `plain_blocking_1` | `AT2: resumed pop consumes the acknowledged wake push instead of re-parking` |

Transcript: `build/atomfix2-pre-proof.log`. This carries the executed lost-update negative
control because live server execution is forbidden to this lane. The retained PRE server is
also available for mainline to run the live commands below; its hash is unchanged from the
original handoff. It predates the unrelated HEXPIRE merge.

| Artifact | SHA-256 |
|---|---|
| `build/tomokv` (rebuilt POST) | `e9fa6951ce77d82ebeaa7f987029c488aebbf4e954e544fbb862162fd4219d51` |
| `build/atomic-survivors-unit` | `2f6481b992e5b4a6f445de8f5ac05894ea5df064d85e490c054f3d9f2abd02db` |
| `build/tomokv-atomfix-pre` (frozen PRE) | `4674397ed0f2b66d33be3147dab70e72317983466b2c6db2fcd3a5c6ddc9da53` |
| `build/atomic-plain-pre-unit` (frozen PRE unit) | `1c7ef087d7c9a47f21d47d19fa048cef553d1149e1e1c220441cdcd83b8f7205` |

**Gate budget**

No atomfix2 row was added or retired. The two existing rows are declared at
`tests/gate.sh:1642`, collected for atomic 0 and 1 at **2818**, before the quick-tier exit
at **2893**. The incoming HEXPIRE row (`:1385`) is collected at **2771**, also before that exit.
The merge therefore changes launch totals **448 / 465 → 449 / 466**. Relative to fetched
origin/cpp, atomfix contributes **+2 / +2** to its 447 / 464.

On-disk constants remain **EXPECT_QUICK=448 / EXPECT_FULL=465**, exactly as at launch.
Mainline must update them to **449 / 466** for this merged tree. The fixture contains 466
labels, preserving legitimate duplicate occurrences. The source-only inventory independently
counts 449 before quick exit and 466 total. Its on-disk count check correctly refuses the
one-row mismatch; it passes with proposed EXPECT_FULL=466 substituted **in memory only**.
Transcript: `build/atomfix2-row-budget.log`. This is not a gate run.

**Mainline-only commands — not executed by this lane**

Schedule the box first. Each boot uses fresh disposable persistence state and only its own
PID is stopped. Both modes have eight CPUs and 16 shards; 2s has 6 io + 2 ex. Fused omits
`--ratio`, as required by its boot grammar. Run from this worktree to use the recorded binaries.

```bash
cd /home/user/Projects/cx-atomfix
atomfix2_live() (
    set -u
    binary=$1; mode=$2; atomic=$3; shift 3
    port=16399
    test -z "$(ss -H -ltn "sport = :$port")" || exit 1
    data=$(mktemp -d "$PWD/build/atomfix2-live.XXXXXX") || exit 1
    args=(--thread-mode "$mode")
    if [ "$mode" = 2s ]; then args+=(--ratio 6:2); fi
    taskset -c 0-7 "$binary" "${args[@]}" --shards 16 --atomic "$atomic" \
        --bind 127.0.0.1 --port "$port" --enable-debug-command yes \
        --key-lb 0 --client-lb 0 --flip-auto 0 --protected-mode no \
        --dir "$data" --save '' --appendonly no >"$data/server.log" 2>&1 &
    server_pid=$!
    trap 'kill -TERM "$server_pid" 2>/dev/null || true; wait "$server_pid" || true' EXIT
    ready=0
    for attempt in $(seq 150); do
        kill -0 "$server_pid" || exit 1
        if taskset -c 112-127 redis-cli -p "$port" PING 2>/dev/null | grep -q PONG; then
            ready=1; break
        fi
        sleep 0.2
    done
    test "$ready" = 1 || exit 1
    taskset -c 112-127 python3 tests/atomic_plain.py 127.0.0.1 "$port" --atomic "$atomic" "$@"
)

# POST: require nine witnessed races at atomic 0 and six at atomic 1, in each mode.
for mode in 2s 1s; do
    for atomic in 0 1; do
        atomfix2_live ./build/tomokv "$mode" "$atomic" \
            >"build/atomfix2-live-post-$mode-$atomic.log" 2>&1 || exit 1
    done
done

# PRE: disposable data only. A setup error or unentered window is NOT a valid control.
pre_status=0
atomfix2_live ./build/tomokv-atomfix-pre 2s 0 --case movers \
    >build/atomfix2-live-pre-AT1.log 2>&1 || pre_status=$?
test "$pre_status" = 1 || exit 1
grep -q 'AT1:.*preserves the acknowledged destination write' build/atomfix2-live-pre-AT1.log || exit 1
for atomic in 0 1; do
    pre_status=0
    atomfix2_live ./build/tomokv-atomfix-pre 2s "$atomic" --case blocking \
        >"build/atomfix2-live-pre-AT2-$atomic.log" 2>&1 || pre_status=$?
    test "$pre_status" = 1 || exit 1
    grep -q 'AT2:.*consumes the acknowledged wake push instead of re-parking' \
        "build/atomfix2-live-pre-AT2-$atomic.log" || exit 1
done

# After mainline updates the two constants to 449 / 466 for this merged tree:
GATE_CORES=0-7 GATE_RATIO=6:2 tests/gate.sh iteration
```

No requested correctness assertion is disabled. The verdict is POST retaining acknowledged
elements and completing waiters with zero stale cuts, while PRE fails at the named data
assertions. An unentered window is always a failed run.

`git diff bb34726854065d6f4d567bf0907e322bc634389f --stat` (includes the required upstream merge):

```text
 MEASURE-REQUEST-atomfix2.md                   | 254 +++++++++++++++++++++
 MEASURE-REQUEST-hexpirefix.md                 | 288 ++++++++++++++++++++++++
 Makefile                                      |   2 +-
 src/cmd/t_hash_ttl.cc                         |  10 +-
 tests/atomic_plain.py                         | 308 ++++++++++++++++++++++----
 tests/fixtures/nullrefresh-ledger-labels.json |  33 ++-
 tests/gate.sh                                 |  14 +-
 tests/gate_measurements.json                  |   6 +-
 tests/hexpire_oom_checks.inc                  | 162 ++++++++++++++
 tests/netcmd_unit.cc                          |   8 +-
 10 files changed, 1021 insertions(+), 64 deletions(-)
```

The lane's changes after the merge are confined to `tests/atomic_plain.py`, `tests/gate.sh`,
and this report; HEXPIRE/config-measurement changes in the launch diff came from origin/cpp.
