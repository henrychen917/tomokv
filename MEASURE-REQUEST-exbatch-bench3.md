# exbatch-bench3: XGROUP preload launch repair

Branch `cx-exbatch3`, worktree `/home/user/Projects/cx-exbatch3`.
Merged `origin/cpp` first, fast-forwarding to `649116c91`. Repair commit:
`c71017b34`. No push. No server, memtier workload, or gate was run. All native
fixtures, compilation, Python checks, and the existing perf busy-loop self-test
ran on CPUs 112–127. The only memtier execution was `--help`.

The reproducible cause is the guard's receipt creation across `taskset`'s exec,
not a warm-up budget. `Children.start()` supplies `LD_PRELOAD` and
`EXBATCH_ZERO_RECEIPT` to an argv beginning with `taskset`. The old guard
constructor creates the receipt with `O_EXCL` inside `taskset`; exec runs the
constructor again inside the target, which exits **86: cannot create receipt**.
The old parent reads MONITOR before checking that exit, so it waits for commands
that were never sent and raises the bare socket `TimeoutError: timed out` after
10 seconds. Perf has not started at that point. The 20-second quiet preflight
plus that wait is consistent with the reported roughly 30-second failure.

The supplied `cx-final/build/exbatch-directed/mainline2-*` logs/results were
absent in this environment. This identifies and reproduces a deterministic
launch defect in the merged tool; it does not claim to reconstruct the missing
historical samples or explain the earlier >2% plateau rejection. Warm workers
finish before the wire probe begins and have separate 60-second socket and
600-second process budgets.

Serverless PRE/POST proof used the same memory-only valid-reply fixture after
the real `taskset -> exec` boundary, with the old versus repaired guard source.
No socket or server was involved:

| Control | Old guard | Repaired guard |
| --- | --- | --- |
| Valid fixture through taskset | Exit 86, `cannot create receipt`, empty file | Exit 0; 1 connection, 152 bytes, 38 zero replies |
| Nonzero integer or error reply | — | Exit 86; no success receipt |
| Truncated reply | — | Exit 86; no success receipt |
| No replies | — | Exit 86; no success receipt |
| Reuse completed receipt path | — | Exit 86; original receipt preserved |

The constructor now resolves receive symbols and records the receipt path.
Exclusive receipt creation happens only when the receiving process finishes,
after complete zero replies have been validated. The per-receive parser and
exact guard/HDR reconciliation are unchanged. `O_EXCL` still rejects reuse.
The wire probe waits for its child's exit before reading the at-most-12 short
MONITOR lines, so a launch failure surfaces immediately with its stderr.
All existing timeout budgets remain unchanged.

Failures now include the step, its elapsed time, total elapsed time, and partial
evidence in the terminal error and JSON artifacts:

- `wire-probe-failure.json`: connect versus MONITOR acknowledgement versus
  memtier exit versus MONITOR frames versus validation; child PID/status,
  received/expected frames, decoded frames, last raw reply, and bounded tails
  of the memtier log, JSON, and guard receipt (including absent/empty files).
- `warm-N-failure.json` / `verify-N-failure.json`: key batch, current command,
  reply index and successfully checked replies, plus connect/send/read phase.
- `sample-failure.json` and `sample.json`: enclosing phase, child statuses,
  bounded log/guard/worker-failure evidence, and phase timings. Perf ACK timeout
  text includes the command, elapsed time and partial ACK bytes.

The plateau refusal still uses **max(rate) / min(rate) <= 1.02**. A failure now
prints the arm, both repeat rates in frames/s, spread, and both sample paths.
Productive occupancy, quiet-box checks, matched-load limits, PMU timing limits,
workload grammar, and frozen binary identities are unchanged. Gate row delta
is **0 quick / 0 full**; `tests/gate.sh` and its expected-count constants were
not edited. No server code/layout change or new server PAD is involved.

Completed validation:

```bash
taskset -c 112-127 python3 tools/exbatch_directed.py --self-test
taskset -c 112-127 python3 -m py_compile tools/exbatch_directed.py
git diff --check
```

**30 tests passed, no skips:** 28 Python controls plus the native exec-chain
test and existing real-perf control. New controls inject timeouts into each
wire stage, retain one partial frame, exercise warm/verify progress, prove an
exit-86 child is checked before MONITOR reads, verify successful XGROUP and
WATCH witnesses, and check both plateau repeat positions around the 2% limit.
The old guard fails the new positive native exec fixture; the fixed guard
passes it and retains the negative controls above.

The complete `--dry-run --blocks 1` output was compared with merged baseline
`649116c91` using the same script path and output argument. It is byte-identical:
**600 samples, 5,958,621 bytes**, SHA256
`9a7cbe1dbbe40ed9a9c933d022ef8a569793f70929df43ace3a32030a783fd6e`.
No dry-run output directory was created. Local raw evidence is under
`build/exbatch-bench3/`: `self-test.log`, `pre-reproduction.json`,
`exec-reproduction.json`, native fixture sources/binaries, `pre-dry-run.log`,
`post-dry-run.log`, and `dry-run-identity.json`.

Mainline should run **only xgroup32**, sequentially in the two requested
regimes, with fresh output directories on the scheduled quiet box. Install this
tool change into the mainline worktree and use the original SHA-bound EXBATCH
arms from `docs/exbatch/binaries.json` at the paths expected by `arm_paths()`.
This lane did not rebuild those server arms; a current unrelated
`build/tomokv` is not a replacement for the frozen POST.

```bash
cd /home/user/Projects/cx-final
taskset -c 0-111 python3 tools/exbatch_directed.py --cell exbatch_xgroup32 --regime f0 --blocks 1 --output build/exbatch-directed/mainline3-f0x
taskset -c 0-111 python3 tools/exbatch_directed.py --cell exbatch_xgroup32 --regime s0 --blocks 1 --output build/exbatch-directed/mainline3-s0x
```

Geometry remains server CPUs 0–7, 16 shards, f0 fused/read-local=0 or s0 split
6:2/read-local=0, eight memtier instances on CPUs 8–111, 512 connections and
pipeline 32. Each regime has 40 fresh-server samples: plateau and matched
passes, each with PRE/PRE nulls followed by PRE/POST, PRE/PAD-A, PAD-A/POST, and
EX6-OLD/POST ABBA comparisons. **PAD-A is kind A, a behaviour twin: PRE behaviour
at POST text/function/data layout. EX6-OLD is the kind-A partial control for
EX6 at POST layout.** Existing arm SHA checks remain mandatory.

The completion criterion is `results.json.complete == true`, exact zero-reply
guard/HDR reconciliation for every probe and scored instance, accepted quiet
blocks in both regimes, and **eight endgame rows per regime** (four comparisons
times two passes). Retain both repeat rates and reject/recollect any >2% block;
do not widen the band. Performance decisions remain matched-load rate plus
cycles/op, IPC and instructions/op for the original arms. This repair makes
no performance claim. Append mainline's results as `MEASURE-RESULT` with the
result/log paths, or retain the new named failure receipts if a run stops.
