reb-r7: v7 rebuild and 2s tail measurement handoff

No server, benchmark, load generator, live flip test, or gate was run by this lane.
All compilation, unit execution and binary inspection used taskset -c 112-127.
There are no new performance results or performance claims in this report.

Base and merge

- Initial branch/worktree: cx-reorder-R7, /home/user/Projects/cx-reorder-R7;
  HEAD 02df1344d5a31274b26000d06c725cc86e246825. The worktree was clean, so
  there was no pending work to commit as "wip before rebase".
- Ran git merge --no-edit cx-final. Merged reference:
  115da17210a0ce651d2fccdbdef018b2d163a3c5 = v7 84846e904 plus local rebaseline.
  Merge/reimplementation commit: 9a6b9d63c.
- Eight conflicted paths: .gitignore, Makefile, src/core/ex_loop.h,
  src/core/flipctl.cc, src/core/flipctl.h, src/core/reorder.h,
  tests/gate_measurements.json, tests/reorder_unit.cc.
- Kept mainline ignore policy, measurement definitions and reference digest;
  combined mainline build rules with the R7 object/unit/PAD rules. Kept the R7
  scheduler and its unit after mainline's modify/delete conflicts.
- flipctl.cc and flipctl.h are exactly cx-final, including the landed count-noise
  floor. Removed the old lane's nanosecond sampler changes and obsolete clock
  fixture. tests/flipctl.py is exactly cx-final. Removed the old lane's BITCOUNT
  alignment override: src/cmd/t_string.cc is exactly cx-final.
- Deleted the retained legacy bucket-sort header reorder_fifo.h. The v6 static
  PASS is not resurrected, even as dead compiler input.

Implementation

--reorder remains the single config.h numeric 0|1 parser, default 0, boot-only.
CONFIG GET reports the effective value; CONFIG SET retains its boot-only refusal.
INFO reports reorder_retired:0 in POST, plus fresh batch/permutation witnesses
only when R7 is armed. Zero selects the existing role bodies, with no scheduler
scratch, per-op branch, queue allocation or reorder witness storage. Overlap can
independently allocate its existing witness sidecar.

R7 retains the two owner-local FIFOs, 4:1 short/long service, homogeneous and
single-client bypass, and at most one gathered batch of carry. Capacity is two
batches. A short entry must be a live ROB head. Long entries retain the admitted
short frontier, so a ratio turn cannot overtake an own predecessor. Special
commands are barriers. Both queues finish inside one inbox drain, before local
read service, snapshot/control work, ownership acknowledgement or return to IO.
No scheduler sidecar survives a shard or role migration; no Op/Client fields,
reader retries, seqlocks or in-place write permissions were added.

The armed executor and fused IO envelopes were regenerated from current v7
methods, replacing only the fresh-task drain/dispatch calls and method names.
This retains current O1 IO windows, O6 prefetch, L4 prebuild, deferred work,
notification, ownership and idle-accounting behavior. The 2s IO bodies themselves
remain mainline. tools/reorder_sync.py fails if the isolated copies drift from
the production envelopes; --write refreshes them. The ordinary FIFO definitions
remain in their original translation units. R7 links last to preserve mainline
weak-symbol selection.

GCC 13 release inlining budgets for main.o and rl2s.o change from 146170/161750
to 146165/161735 (inline-unit-growth remains 0). These are compiler locks, not
runtime knobs. The initial unchanged budgets changed two checked off-path bodies;
the final budgets pass every checked body. genthread.o retains mainline's 128880.

The gate's existing feature/orthogonality/workload checks now distinguish the
retired reference/PAD from active R7. Active R7 requires fresh permutations;
disabled R7 must expose no scheduler counters. Missing engagement remains a
failure after bounded fresh-state arming. The old shared scope probe remains a
historical pre-R7 instrument and explicitly rejects this continuous scheduler.

Gate ledger: zero rows added or retired. tests/gate.sh is byte-for-byte cx-final;
EXPECT_QUICK=419 and EXPECT_FULL=435 are unchanged. The existing flip unit row
is at lines 1196-1200, before the quick-tier exit at line 2764. The restored R7
unit is a make-unit check and a manual witness, not a silently added gate row.

Artifacts

| Arm | Path | SHA256 |
| --- | --- | --- |
| PRE, rebuilt cx-final | build/r7-pre/build/tomokv | fb61f96bd05d5a23dfed0166f4b847712fa87caacfd41052fbfc1ef795ea4b90 |
| POST | build/tomokv | 71a1ed2ec7638c9c07facfd0497ba5cf0771627666a24af81bb5d93d9fbf46c2 |
| PAD A | build/tomokv-pad | a905b2c343a1b920ac5abeb6a2832a49f35ac7ed0d6c8397cf0046cea3603fc4 |

The frozen reference remains /home/user/Projects/bench-bins/tomokv-headline-84846e904,
SHA256 f8e53f984d7f46d96e7a388e71b260a6144f9c475f5100faf1be572a49f0708f.
The locally rebuilt PRE has exactly the frozen reference's .text AND .rodata
bytes; full ELF digests differ. Receipt: build/r7-reference-identity.json.

PAD semantics: (A) behavior twin, PRE FIFO behavior with POST's exact text size,
layout, symbol addresses, section metadata and all other bytes. The offline tool
copies POST and patches only the noipa reorder_available() body, preserving CET:
three bytes at file offset 3663428 become 31 c0 c3 (false; return). The boot clears
reorder before Server allocation, and INFO reports reorder_retired:1. Thus PAD
with --reorder 1 also executes FIFO. L4 prebuild and flipband remain enabled.
The patch changes no request-path instruction and adds no runtime control knob.
Receipt: build/tomokv-pad.json. No relinking, placement exceptions or inverse
control are used. PRE .text is 3,557,219 bytes; POST/PAD are 3,749,267 (+192,048).
This text growth is a measurement consideration, not a performance result.

Verification

| Check | Result / evidence |
| --- | --- |
| Default make -j8 and PAD construction | PASS; build/r7-final-build.log, no compiler warnings/errors |
| Strict reorder=0 witness | 169/169 identical; build/r7-noop-final/audit.json |
| Scheduler bodies | 32/32 identical |
| IO envelopes, including O1 pipeline passes | 76/76 identical |
| Dispatch | 28/28 identical |
| Retirement | 8/8 identical |
| GET/SET command bodies | 8/8 identical |
| Multi-key command bodies | 17/17 identical |
| Production queue engagement | 12/12 configurations; build/r7-engagement-final.log |
| PAD production engagement fixture | 12/12 FIFO configurations; build/r7-engagement-pad-final.log |
| Scheduler native and ASAN/UBSAN | 205 required batch permutations plus carry, barriers, immediate destruction, ring wraps, quota/dependency and 1024-task connection streams at capacities 32/128 |
| FIFO scheduler mutant | Required permutation oracle fails with exit 1; build/r7-fifo-mutant.log |
| make unit | Parser, flip controller, both read-local rings, scheduler and waits PASS |
| tests/flipctl_unit.cc | Existing model checks and all 12 landed rate-floor rows PASS |
| INFO/CONFIG handler fixture | build/netcmd-unit config PASS; build/r7-netcmd.log |
| Gate verdict negative controls | 55 tests PASS; build/r7-gates-unit.log |
| ABBA self-tests | 89 + 10 + 7 tests PASS; build/r7-abba-unit.log |
| Historical scope-tool unit | 8 tests PASS; build/r7-scope-unit.log |
| Envelope synchronization and bash -n tests/gate.sh | PASS |

The former 217-body manifest belonged to the pre-v6/O1 code. This reference has
147 physical bodies in that original scope. The refreshed manifest additionally
checks 22 surviving O1/prefetch/sweep bodies, giving 169; no differing body was
excluded. The audit retains every opcode, register, immediate, member offset,
branch, instruction width and internal block offset. Only verified relocation
bytes are normalized, with complete consumed read-only literals and switch
case destinations checked. A hoisted epoll switch table now has the same strict
verification; negative controls reject a changed case target or clobbered base.
Cold boot selection, config and INFO deliberately change and are not claimed
byte-identical. The audit is a hot-body identity proof, not a rate measurement.

The production fixture posts 64 real Tasks through the production inbox, calls
the production drain, and records actual handler order. Armed order must equal
the independent 4:1 oracle and both emitted gathers must retain O6 prefetch.
It covers 1s and 2s with read-local armed, plus the ordinary read-local=0 2s owner,
each with overlap 0/1 and requested reorder 0/1. Every task completes, every ROB
prefix retires and no carry/deferred debt remains. The same exact capability
patch makes all requested-1 PAD cases FIFO. No listener, worker loop or io_uring
instance is started. The FIFO mutant bypasses submit() in a build-only header;
it is not used by any release artifact.

All layout locks hold (GDB type inspection, without running the server):
Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144, Config 624. See build/r7-layout.log.

Development checks caught and resolved: two initial off-body inlining changes;
an intermediate budget restored IO but changed ExLoop::run (final audit is clean);
the new engagement fixture initially omitted inbox initialization (fixed in the
fixture); the PAD symbol search initially also matched a global initializer
(now requires the exact capability symbol). The netcmd fixture requires the
config argument; that completed invocation passes.

Maintainer measurements requested — nothing below was executed

Rate cells: h05/h07 = 1s GET p32, reorder 0/1; h21/h23 = 2s GET p32, reorder 0/1.
All four have overlap=1, read-local=0, atomic=1, 512 connections; preserve the
instrument's balancers, populations, offered loads and perf counters. Compare
POST vs the frozen v7 reference and POST vs PAD A, including reorder=0 controls.
The current pinned rate geometry is server 0-31, load 32-111, no SMT, 2s 16:16.
Use the current checked-in instrument, not a pre-v6 harness copy. Example:

    python3 tests/abbagate.py --candidate-binary build/tomokv \
      --reference-binary /home/user/Projects/bench-bins/tomokv-headline-84846e904 \
      --build-reference 0 --only h05,h07,h21,h23 \
      --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
      --output build/r7-rates-v7
    python3 tests/abbagate.py --candidate-binary build/tomokv \
      --reference-binary build/tomokv-pad --build-reference 0 \
      --only h05,h07,h21,h23 \
      --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
      --output build/r7-rates-pad

The active/disabled witness fix changes the instrument fingerprint to
3b37211e3b74e6083e78bbc299f0dd27df645c799ace179d0ff0e8109b869873.
Existing load-floor hashes must therefore be requalified by the harness, with
a matching same-binary null/receipt. No pins or thresholds were edited here.
Judge matched-load rate; report PRE/POST/PAD rate, cycles/op, instructions/op and
IPC. POST vs its own reorder=0 arm is required: a gain against an older active
sorter is not evidence that scheduling beats FIFO.

Primary tail question: tailgen, 2s at 830000, 880000 and 930000 offered ops/s.
Use the standing /home/user/Projects/calib/tailgen-run.sh population and geometry:
server cores 0-31, --shards 256, --thread-mode 2s, --ratio 16:16, --read-local 0,
--overlap 1, --atomic 1, --key-lb 1, --client-lb 1, --flip-auto 0; no persistence.
Populate 2,000,000 64-byte short keys and 65,536 256-KiB blocker keys (16 GiB).
This is separate from the correctness gate's 8-core 6:2/16-shard geometry.

At EACH rate, compare POST --reorder 1, POST --reorder 0 and PAD A --reorder 1;
include PRE --reorder 0 as the layout baseline. Use paired ABBA blocks for
POST-0/POST-1 and PAD-1/POST-1, plus PRE-0/PAD-1 and a same-binary null. Repeat
at least four blocks, alternate which arm starts, match seeds, and preserve every
warmup and measured run. Do not pool a first-boot cold interval into warm evidence.
For each arm/rate, the current tailgen command after population is:

    taskset -c 84-111 /home/user/Projects/cx-tailgen/build/tailgen \
      --host 127.0.0.1 --port 7899 --rate RATE --threads 16 --conns 32 --cores 84-111 \
      --mix 'GET:8,BITCOUNT:2' --spacing poisson --seed SEED \
      --short-keys 'memtier-{1..2000000}' --long-keys 'blocker:memtier-{1..65536}' \
      --warmup 3 --duration 20 --max-outstanding 64

RATE is exactly 830000/880000/930000; use the same SEED for each paired arm.
The existing standing runner accepts TG_MODE=2s and TG_SERVER_EXTRA for the
explicit ratio/balancer/flip flags above; retain JSON AND stderr. A four-round
single-arm invocation is, for example (schedule/interleave the paired arms):

    TG_MODE=2s TG_SERVER_EXTRA='--ratio 16:16 --key-lb 1 --client-lb 1 --flip-auto 0' \
      /home/user/Projects/calib/tailgen-run.sh r7-on-830 \
      /home/user/Projects/cx-reorder-R7/build/tomokv 1 4 830000

Deciding number: paired change in short.p999_ms (also top-level p999_ms) at the
same offered rate, beyond the matched same-binary spread. Also retain short
mean/p50/p99, long.p999_ms, achieved cohort rate, class counts, outstanding_max,
over_max_outstanding_fraction, pacing lag, omitted arrivals, queued bytes and
drain time. A lower achieved load, missing replies, generator lag or long-class
starvation is not a tail win. Capture before/after INFO SERVER and DEBUG LB:
POST-1 must have fresh reorder_permuted_runs; POST-0 must lack reorder counters;
PAD-1 must report reorder=0/reorder_retired=1. A queue-selection unit does not
prove network egress during a blocker; only this scheduled end-to-end read can
answer the owner's p99.9 question. No latency conclusion is drawn from memtier's
depth-capped tail cells.

Flip interaction: run the existing gate row "flip controller: ramp gate, hold,
surge + mix re-maneuvers" for PRE, POST-0, POST-1 and PAD-1, at least three rolls
per arm, with the gate's parallel-battery conditions. Exact row geometry:
GATE_CORES=0-7, --shards 16 --ratio 6:2 --atomic 0 --flip-auto 1, normal tick.
Include overlap 1 to exercise the candidate setting (retain the ordinary row's
other settings), then the maintainer's tests/gate.sh iteration. Require unchanged
ramp/hold/surge/mix assertions; record pass/fail, final split, rate_band,
anchor_rate, trigger counters and DEBUG FLIPCTL. Do not conclude from standalone
passes alone: the prior rail anchors depended on the gate's concurrent jobs.

PRE/POST/PAD measurement table to fill (all cells pending):

| Cell | PRE | POST reorder=0 | POST reorder=1 | PAD A | Verdict |
| --- | --- | --- | --- | --- | --- |
| 1s p32 GET, h05/h07 | pending | pending | pending | pending | pending |
| 2s p32 GET, h21/h23 | pending | pending | pending | pending | pending |
| 2s short p99.9, 830K | pending | pending | pending | pending | pending |
| 2s short p99.9, 880K | pending | pending | pending | pending | pending |
| 2s short p99.9, 930K | pending | pending | pending | pending | pending |
| Flip row, >=3 rolls/arm | pending | pending | pending | pending | pending |

Commands run by this lane (read-only git/rg/sed/nm/objdump inspection omitted)

    git add -A                           # clean; no WIP commit needed
    git merge --no-edit cx-final
    mkdir -p build/r7-pre
    git archive cx-final | tar -x -C build/r7-pre
    taskset -c 112-127 make -C build/r7-pre -j8
    python3 tools/reorder_sync.py --write
    taskset -c 112-127 make -j8
    taskset -c 112-127 make -j8 all build/reorder-engagement-unit build/reorder-unit-asan unit
    taskset -c 112-127 make -j8 all build/tomokv-pad build/reorder-engagement-unit unit
    taskset -c 112-127 make -j8 build/reorder-engagement-unit
    taskset -c 112-127 ./build/reorder-engagement-unit on
    taskset -c 112-127 ./build/reorder-unit-asan
    taskset -c 112-127 python3 tools/reorder_pad.py build/reorder-engagement-unit \
      build/reorder-engagement-unit-pad --receipt build/r7-engagement-pad.json
    taskset -c 112-127 ./build/reorder-engagement-unit-pad off
    taskset -c 112-127 python3 tests/reorder_noop.py \
      build/r7-pre/build/tomokv build/tomokv build/r7-noop-final --literal-pools
    taskset -c 112-127 make -j2 build/netcmd-unit
    taskset -c 112-127 ./build/netcmd-unit config
    taskset -c 112-127 python3 -m unittest discover -s tests -p gates_test.py
    taskset -c 112-127 python3 tests/abbagate.py --self-test
    taskset -c 112-127 python3 tests/reorder_scope_test.py
    taskset -c 112-127 bash -n tests/gate.sh
    taskset -c 112-127 python3 tools/reorder_sync.py
    sha256sum build/tomokv build/tomokv-pad build/r7-pre/build/tomokv
    size -A build/tomokv build/tomokv-pad build/r7-pre/build/tomokv
    git diff --check

The compiler-budget search used the same release CXX/JE flags with
inline-unit-growth=0, main budgets 146140/146155/146165 and rl2s budgets
161720/161735/161745, producing build/r7-tune/*.o and a diagnostic relink. The
final default build recompiles from Makefile with the selected budgets. See
build/r7-tune.log, r7-noop-first.log, r7-noop-current.log, r7-noop-tuned.log and
r7-noop-final.log. The temporary FIFO-mutant header adds an immediate FIFO emit
and return to ExReorderQueues::submit; it was compiled with:

    taskset -c 112-127 g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread \
      -Ibuild/r7-fifo-mutant -I. -iquote src/core tests/reorder_unit.cc \
      -o build/reorder-fifo-mutant

Its exit 1 and exact permutation failure were checked by a pinned Python
subprocess wrapper. GDB ran only the initial serverless engagement fixture to
locate its missing inbox, and inspected sizeof types in the server executable
without run/start/attach. Binary section comparisons used the offline ELF reader.
Source changes were committed throughout; this named report is force-added
through mainline's MEASURE-REQUEST* ignore. No root MEASURE-REQUEST was written.
