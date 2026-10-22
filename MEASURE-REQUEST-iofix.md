# IO loop refinement

## iofix

Base `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`, branch/worktree `cx-iofix`,
`/home/user/Projects/cx-iofix`. No push. All four findings reproduced on PRE;
none is NOT REPRODUCED. Performance acceptance remains pending maintainer
measurement. No throughput claim is made here.

### Changes

- **WB4.1:** only advancing a bounded deferral counter reports work. The Dth
  increment still schedules the immediate half-rule retry. Saturated/unbounded
  entries retain FIFO/lifetime pins and park through existing completion
  arm/recheck/wake, with the existing 50 ms ceiling where no completion supplies
  a wake. The test identifies the actual IO owner by DEBUG IO-THREAD and CPU
  affinity, then reads its schedstat, rather than substituting whole-process
  CPU. All policy arms require a real remote LPOS window and exact oracle
  replies. **WB4.2 remains unchanged:** D=3 still counts visits that can expire
  in rapid passes. Removing the subsequent indefinite spin does not make the
  low-load small-pipe completion clause effective.
- **IO4.9:** Redis 7.4 hz/dynamic-hz grammar, defaults, CONFIG GET/SET, file
  parsing, REWRITE and INFO reporting. hz accepts canonical integers in
  0..INT_MAX and clamps to 1..500; default 10. dynamic-hz defaults yes and
  doubles effective hz while clients/hz >200, capped at 500. Both cron cadence
  and max(5, client_count/hz) share follow effective hz. Oracle assertions cover
  invalid/duplicate/case/all-or-nothing replies, file/rewrite/reload, dynamic
  scaling, cadence and 256 timeout clients at hz=1. A stale /10 share fails.
- **IO4.10:** a global DEBUG SLEEP rendezvous at IO/executor pass boundaries.
  Duration starts after all participating workers stop. Role changes update
  membership; synchronous admin dependencies release/retry admission without
  replying OK early. Completion tickets preserve requests and ordering. Direct
  and EXEC sleeps, every IO owner, read-local, fused R7, disconnect and signal
  interruption are covered. Parsing follows the local Redis 7.4 strtod,
  microsecond truncation and nanosleep behavior, including zero, sub-us,
  numeric-prefix and invalid values. Signal interruption closes the race with
  sleep admission. There is no per-operation sleep gate.
- **IO4.17:** publish the signal request and ring the existing eventfd at once.
  Elected IO begins the shutdown save on its next pass, independent of the
  one-second cron. Drain the request edge before saving and retain a terminal
  wake after success. IO/executor polls are one-shot and rearmed only for a
  nonterminal request. The elected IO also drains a late request write after
  a failed save cleared the pending bit. A separate terminal latch restores
  a stop edge caught by that drain. Other observers never consume the wake.
  Oracle/target assertions cover SIGTERM/SIGINT, saved-data reload, failed-save
  service/retry, NOSAVE and signal during sleep. Existing FLIP tests cover
  shutdown during a role change and second SIGINT.

All eight locked layouts remain unchanged: Op 336, Client 1984, ThreadCtx 1408,
Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. Config uses
reserved tail space; server coordination is appended. No ownership, QSBR,
immutable replacement, RYOW or transaction dispatch law is weakened.

### Evidence and geometry

Source oracle `/home/user/Projects/redis/src`; binary oracle
`/home/user/Projects/redis74/src/redis-server`. Correctness servers/oracles use
CPUs 80–87, clients 88–95, builds 80–95/-j16; ports 19800–19899. Every new job
owns all four legs: **2s 6:2 and eight-worker 1s, 16 shards, uring and epoll**.
The test oracle uses the adjacent port and same server CPU mask. Directed
witnesses disable LB/automatic FLIP. Raw initial reproduction evidence is in
`docs/iofix/reproduce*.jsonl`; the first fused attempt's invalid ratio is kept
alongside the successful corrected attempts.

Runtime verification uses **tests/gate.sh's own job interface**, GATE_ONLY_JOBS
and its ordinary batteries. The full positional tier exposes the standard
differential jobs; selected partial runs are not full-gate receipts. The
candidate adapter only supplies a missing engine/mode and execs the frozen
ELF; separate forced-engine runs record actual argv when old helpers explicitly
choose uring. PRE uses archived PRE source and its own units. Minimal fixture
interface adaptations are recorded in `docs/iofix/pre-harness.txt`.

The raw logs and ledgers are retained in `docs/iofix/proof/`. Every touched fixture
and every DEBUG SLEEP grep user is mapped to its owning gate job in
`docs/iofix/affected-jobs.md`. The corrected debug assertions and all new
oracle reply comparisons retain their oracle runs.

The final release directed run (`PHoa8J`) passed **72 rows, zero failures**.
Its exact command, binary hash and complete archived evidence are in
`docs/iofix/final-directed-receipt.json` and `docs/iofix/proof/final-directed/`.
The identical new batteries on PRE (`1FCQ6x`) produced **39 passes and seven
expected failures**: four new rows, two existing writeback phase/split-phase
rows containing the stronger park assertion, and the corrected global DEBUG
SLEEP row. Every new mode/engine leg ran. PRE hz also attempted file/rewrite/
reload phases despite the missing knob; PRE sleep attempted every direct,
EXEC, read-local and R7 variant despite earlier phase failures. The PRE signal
row reaches the target and fails specifically on the forced save-cron wait.
`docs/iofix/directed-witness-audit.json` checks each of the 16 PRE failures
against its intended defect and the matching final POST pass, with raw-log links.

Review then found a late-writer race in the signal eventfd. The new deterministic
`netcmd config` witness failed all six dispatch variants on that release
(`dCuZVC`: 16 passes, one expected failure). It explicitly opens the late-write
window and checks elected-owner draining and terminal-edge retention. The
final directed run passes all six variants with explicit late-write draining
and terminal-edge retention. The earlier passing runs are retained as interim
evidence; they do not establish this stronger property.

Actual connection-owner CPU, default policy=1/S16/D3, 16 remote LPOS windows:

| Mode / engine | PRE IO CPU / wall (ms) | POST IO CPU / wall (ms) |
| --- | ---: | ---: |
| 2s / uring | 425.999 / 426.639 | 0.450 / 427.584 |
| 2s / epoll | 425.795 / 426.271 | 0.472 / 427.398 |
| 1s / uring | 438.417 / 438.910 | 0.502 / 426.604 |
| 1s / epoll | 425.731 / 426.396 | 0.523 / 439.533 |

Policy 0, S0/D3 and S16/D0 evidence is in
`docs/iofix/deferred-cpu-comparison.json`. This is idle-IO CPU evidence, not a
throughput experiment. Forced fresh-beat shutdown took 1014.66–1014.77 ms on
PRE versus 3.16–7.22 ms on POST across SIGTERM/SIGINT and all four legs. Exact
values, failed-save idle CPU and oracle observations are in
`docs/iofix/signal-comparison.json` and the retained signal logs.

Build proof: make all, every job_production_units target and MDBQSBR live arms
built successfully. `docs/iofix/production-freshness-final.txt` records make -q
exit 0 for every target, with matching flags for the live arms.
`python3 tests/gates_test.py` passed **67/67**, including 14 nested persistfix
selftests, with GATE_TEST_PORT=19898 (`gates-test-final.log`).

### Row accounting

Four new rows at source lines 4147–4150 precede quick exit line 4351:
**DQ=+4, DF=+4**. EXPECT_QUICK=685 and EXPECT_FULL=702 are unchanged. The
maintainer's new values should be **689 / 706**. Source and fixture have the
same 706-label multiset, no missing/extra labels. The strict fixture check
correctly refuses the frozen 702 count; it is not called a pass. Evidence:
`docs/iofix/label-inventory.json`, `label-fixture-check-final.log`.

### Identity

Existing ccfix/lbstall tools ran against PRE and report differences; whole-
server strict identity is not claimed. All **762 changed emitted bodies**,
including added/removed COMDAT copies, reasons and actual PRE/POST link
provenance, are listed in
`docs/iofix/identity-final/changed-bodies-with-reasons.json`. Of these, 434 are
linked in PRE and 492 in POST. Discarded object copies are identified.

All **143 selected linked main-command bodies match PRE**, including GET/SET
handlers, read-local GET/MGET resolvers, captured MGET/MSET executors and their
scatter preparation/execution/completion/assembly. The body hashes and resolved
calls are in `linked-main-bodies.json`. Link-map-only rebuilds reproduce both
ELF SHA values exactly (`pre-map-receipt.json`, `post-map-receipt.json`).

EXEC-only sleep coordination is isolated in a cold command unit. Per-unit
budgets were re-derived from GCC initial-unit summaries and compile-only
trials (`docs/iofix/budgets/`): src rl2s 163972, src genthread 131500, db0
genthread 131400, src xshard 128800, db0 xshard 127741. The latter two preserve
ordinary scatter bodies after cold helper isolation adds 28 initial-unit
instructions. Other identity differences remain listed for merit judgment.

### Frozen arms

| Arm | SHA-256 | .text bytes |
| --- | --- | ---: |
| build/tomokv-pre | 41d90251d14de51c081a9d489469c47deda62b4bca3923eb5d8bde655e2b9e76 | 7,747,526 |
| build/tomokv | a7a3d72aa058fee0e790394f744e64acfb5cdb51b689a4608604ea8024c82260 | 7,796,422 |
| build/tomokv-pad-a | 409efd511fafa64b2bf170c08320486b690e3277704d29a5a2cda2ca0be7ac32 | 7,796,422 |
| build/tomokv-pad-a-wb | d9c7e12006eee966c474b705ad7f0bdd4156e63ee32057b7f34a799119ad3fb5 | 7,796,422 |

**build/tomokv-pad-a is kind A: full PRE behavior with POST's exact .text
size.** `tools/iofix_full_pad.py` first relinks the captured PRE objects to
PRE's original SHA, then appends one unreachable 48,896-byte return/NOP function.
All original PRE text function addresses and sizes remain unchanged; GNU CET
properties are preserved. The control matches total text size, **not POST's
function placement**. `docs/iofix/pad-a.json` records link inputs and checks.

**build/tomokv-pad-a-wb is a separate kind A control scoped to WB4.1:** PRE's
positive-work behavior whenever deferred, at POST's exact text/ELF layout.
`tools/iofix_pad.py` patches only the boolean at all 104 linked FIFO/R7
flush-ready sites (312 bytes). Section/symbol addresses/sizes are identical;
no other bytes change. `docs/iofix/pad-a-wb.json` records every patch. Its hz,
DEBUG SLEEP and signal-stop administrative behavior remains POST.

All nominated cells use default hz, 512 clients and no DEBUG SLEEP or
signal-save operation; effective cron stays 10 Hz. The two controls answer
different questions: total text size with full PRE behavior, and exact POST
placement with PRE deferred-work behavior. Neither alone attributes every
code-placement effect. PRE versus POST is the overall acceptance comparison.

### Maintainer merit request — NOT RUN in this lane

Use `docs/iofix/merit-cells.txt`: exactly the generic 14 cells from
`tests/wbland_merit_cells.txt` plus four **2s depth-1** cells (GET/SET ×
read-local 0/1), atomic=1, 512 clients. Use the gate's ABBA instrument for PRE
versus POST, then PRE versus each PAD-A control, including matched null controls. Preserve
hashes, CPU/SMT masks, ratio, shards, load shape, sample order and receipts.
Report rate at matched offered load and depth-1 p50/p99/throughput. Obtain
cycles/op, instructions/op and IPC in a separate diagnostic PMU pass using
the same instrument. The existing tools/wbknobs_measure.py --experiment null
--profile 1 path provides those windows; diagnostic profiling is not itself a
null acceptance receipt.

Current measurement metadata has reviewed **32-core, 16:16 split** for 2s
ABBA. Its 8-core 6:2 entry is correctness geometry only. Use the maintainer's
reviewed quiet-box ABBA allocation, or first review/calibrate an 8-core 6:2
performance entry and matched nulls; do not silently invent a performance
ratio. All lane-executed work stays on 80–95. The 18 cells were parsed without
starting servers; none of these ABBA/PMU commands was executed in this lane.
The gate's FLIP saturation job uses its own load generator solely to assert
correct role changes; its traffic is not used as performance evidence.

After the maintainer assigns reviewed masks in IOFIX_MERIT_SERVER and
IOFIX_MERIT_LOAD and supplies the instrument's matched nulls, the comparison
commands are:

```bash
common=(--reference-binary "$PWD/build/tomokv-pre" --build-reference 0
        --cells docs/iofix/merit-cells.txt --subset full
        --server-cores "$IOFIX_MERIT_SERVER" --load-cores "$IOFIX_MERIT_LOAD"
        --ports 19800-19899)
python3 tests/abbagate.py "${common[@]}" --candidate-binary build/tomokv \
    --output build/iofix-merit-post
python3 tests/abbagate.py "${common[@]}" --candidate-binary build/tomokv-pad-a \
    --output build/iofix-merit-pad-a
python3 tests/abbagate.py "${common[@]}" --candidate-binary build/tomokv-pad-a-wb \
    --output build/iofix-merit-pad-a-wb
python3 tools/wbknobs_measure.py --experiment null --profile 1 "${common[@]}" \
    --candidate-binary build/tomokv --output build/iofix-merit-pmu
```

Decision: compare POST with PRE in every cell. A material regression or
invalid/null failure prevents acceptance. Explain cycles/op as instructions/op
divided by IPC; fewer instructions alone prove no gain. For the scoped WB
control, a behavioral gain needs POST to move while PAD-A-WB stays with PRE,
subject to the same null envelope. Identical-arm spread above 2% requires
diagnosis, not a wider noise allowance. No 25GbE claim follows from loopback.

### Limitations and incidents

- Performance ABBA/PMU, full tests/gate.sh iteration, merging and pushing are
  **NOT RUN**; these remain the maintainer's scheduled work.
- The full PRE PAD-A controls text size, while the WB PAD-A controls exact
  layout only for WB4.1; these limitations apply to merit attribution.
- An initial splitlocal negative-control compile used that old fixture's
  hardcoded 112–127 mask. It now inherits 80–95 and was rerun. Database servers
  and oracles used the assigned server CPUs/ports. Initial gate selftests also
  used two ephemeral socket-only probe ports; the final run uses 19898. These
  initial attempts are retained as diagnostics.
- The first full PAD link lacked GNU CET properties; strict address checks
  rejected it before execution. The corrected builder preserves those notes
  and publishes the arm only after all checks pass.
- Earlier implementation/harness failures are retained and are not final
  passes. An early PRE signal attempt failed on an oracle log-string mismatch
  before reaching the target; it is not used as a negative witness. Final
  proof is indexed by frozen binary hash.
- The final `1H4VvA` batch passed all differential partitions but had two
  adapter failures: an inherited 128 KiB file-size limit rejected the growing
  launch log before AOF boot, and the R7 identity tool received the adapter
  script instead of an ELF. Launch records now use one short file per process;
  both affected jobs are rerun through the gate with the real, unchanged ELF.
  The failed batch remains in the evidence and is not labelled all-green.
