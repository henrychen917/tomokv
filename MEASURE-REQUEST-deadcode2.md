# deadcode2 — tier-4 cleanup and null request

Work is committed on `cx-deadcode2`; no push, server, gate, load generator, or
measurement was run. All builds and executable serverless proofs use CPUs
112–127. Mainline owns the live checks and the 14-cell null below. No throughput,
cycles/op, instruction, IPC, or latency improvement is claimed.

Launch `0e894d165` is protected by `deadcode2-start-0e894d165`. The initial
`--no-ff` merge of `origin/cpp` (`d81b6d3a2`) produced `98cbf12e5`, protected by
`deadcode2-pre-cleanup-98cbf12e5`. PRE is built from that merge's source (identical
to upstream/merge-base `d81b6d3a2`). The final fetch and `--no-ff` merge found
upstream unchanged. Category commits, including reversions of rejected
candidates, are listed in [commits.txt](docs/deadcode2/commits.txt).

**Scope retained for review:** RO7 has live test/PAD dependencies. NET22, WB10,
and the detector-arm portion of CT19 are held back because their candidates
failed the required ordinary-body identity. These are explicit skips, not
successful deletions. Rejected patches and compiler controls remain reviewable.

| Item | Action taken / skipped and reason |
|---|---|
| NET20 | Deleted `TOMO_WEDGE_FORENSICS`, its impossible Client layout/counters, all use sites, and its shutdown reporter. Production PRE never emitted the disabled arm. |
| NET21 | Deleted `kIfidPending`, `set_ifid_pending`, and `ifid_pending`. No other bit moved. NET9a's bit-6/7 overlap was checked: the read-local Op flags and Client blocked bit retain their existing meanings and values. |
| NET22 | **Skipped after trial.** Removing `try_ktls`/memory-BIO initialization changed parser bodies. Restoring NET22 alone restored every body in the single-DB read-local TU. The merged tree also has a real forced-fallback TLS unit caller passing false; it was restored. [Rejected diff](docs/deadcode2/NET22-not-landed.patch). |
| RO8 | Deleted production `r7::ex_schedule_batch` and its false documentation. The two units use an explicitly test-only adapter in `tests/reorder_batch_fixture.h`; all four build targets depend on it. The obsolete production no-op exclusion was removed. |
| RO7 | **Retained.** `tests/r7shadow_pad.py` patches `shadow_available`; reorder engagement and queue units exercise the false/FIFO arm. The R7 identity/parity controls therefore depend on both the noipa selector and `ExReorderQueues`. Removing either would break the requested gate/control machinery. |
| WB9 | Corrected all three statements: physical split includes SplitLocal; `IoPipe = (!Fused || SplitLocal) && Pipeline == 1`; natural/retire helpers pass SplitLocal; the relevant IO entry is `run_fused`/`run_loop`. |
| CT16 | Removed the two duplicate trigger INFO aliases and their duplicate arguments. `tests/flipctl.py` reads the canonical `flipctl_rate_*` counters. A TU-local compiler budget preserves every unrelated `t_server.cc` body. |
| CT19 | **Partial.** Corrected the learned-band documentation and removed both dead `ratio == 0` disjuncts from live and PAD LB controller streak updates. The floor is strictly positive for the admitted owner counts. Detector-arm/selector deletion is held back: its interaction with WB10 changes ordinary writeback bodies. Original detector implementation, constructor/state, and original unit coverage are retained. [Rejected detector diff](docs/deadcode2/CT19-detector-not-landed.patch). |
| CT17 | Renamed all six client-balancer counters to `tomokv_clientlb_*`, without aliases. Updated literal and constructed-prefix readers; seeded INFO fixtures check unique nonzero values in both modes and database counts 1/4. The external calib reader was updated concurrently outside this lane; see below. |
| CT18 | Removed `LbSnapshot::ratio_star_io_frac`, INFO publication, and DEBUG's three `ratio_star_*` values. Preserved actual topology and foreign fraction. Updated documentation and `tests/lbsignals.py`; the seeded fixture asserts absence and surviving fields. |
| WB10 | **Skipped after trial.** The only production caller initializes Config, so hardcoding 1 is semantically appropriate, but removing the call/patch point changed ordinary writeback bodies. Searches of compiler budgets and source controls did not restore all of them. The original default function and its historical arms builder are retained together. [Rejected diff](docs/deadcode2/WB10-not-landed.patch). |
| IO11 | Ledgered the nine constants and duplicate cadences; replaced the cache-line duplicate with existing `kCacheLine`, both bare epoll 50s with `Ring::kWaitTimeoutMs`, and the cron 100 with `1000 / kClientCronBeatsPerSecond`. Tied the duplicate writeback backstop to its named constant. Updated source-check readers and regenerated R7. No numeric cadence changed. |
| IO12 | Ledger records both shipped fused quanta as **32**, with the ROB-depth/wider-chunk derivations **OPEN / unapplied**. No performance constant changed. |
| RL5 | Extracted the shared 355-line classification block into `src/core/read_local_parse.inc`, included in the same lexical context by FIFO and R7. No new function boundary or reader protocol. The isolated same-budget proof passed before acceptance; final combined audit is recorded below. |

The authoritative `scratchpad/constants-ledger.html` named by the audit is
absent from this checkout, all local Git history, and the accessible home tree.
[constants-ledger.md](docs/deadcode2/constants-ledger.md) is an explicit addendum
using the audit's ledger columns, for incorporation by the maintainer. It does
not claim that the missing canonical HTML was edited.

The active CT17 readers changed in this worktree are `tests/gates_test.py`,
`tests/feature_gate.py`, `tests/lb_stationary.py`, and `tools/lb_episodes.py`.
The latter now separates key/client prefixes in dynamic counter, spread and
refusal readers. `/home/user/Projects/calib/lbplanner-judge.py` is outside this
worktree, so this lane did not modify it. At finalization it had changed concurrently and
already accepted the new names, while retaining old-name compatibility. Its
current hash and this observation are in
[calib-clientlb.json](docs/deadcode2/calib-clientlb.json). The earlier
[calib-clientlb.patch](docs/deadcode2/calib-clientlb.patch) is an old-base review
artifact, superseded by that external edit; **do not apply it to the current
file**. Removing external reader compatibility aliases, if required by the
strict no-alias rule, remains a maintainer integration step. Archived calib source snapshots and frozen JSON performance
evidence retain their original vocabulary. Negative fixtures intentionally
mention removed names. The historical `legacy_reorder_witness.py` examines its
frozen old commit, so its old wrapper reference remains valid.

Every requested name and its dynamic-prefix forms was searched with **grep**
across tests, tools, and the external calib tree. The compressed match receipt
is [final-readers.txt.gz](docs/deadcode2/proofs/final-readers.txt.gz). No `rg` was
used. No `EXPECT_QUICK`/`EXPECT_FULL` edit was made.

**Byte evidence.** The complete object-function inventory does not omit cold
functions or newly missing symbols. Raw object bytes and equality after
resolving relocation targets are reported separately. Relocation equality is
not advertised as literal linked-image identity. Every changed body has a
reason in [changed-bodies.md](docs/deadcode2/changed-bodies.md), with machine
receipts alongside it. The hot inventory is the existing
`tools/lbstall_artifacts.py compare`; the linked parser/dispatch inventory is
`tests/r7shadow_noop.py --inventory splitlocal`. No normalizer was widened.

RL5's isolated PRE-extraction→POST-extraction comparison uses identical compile
budgets: **1492/1492 hot object bodies are literally identical**, and **396/396
splitlocal physical bodies** pass the existing linked-body normalizer. Both
namespaces and both FIFO/R7 instantiations are included. The compressed
`rl5-hot` and `rl5-inventory` receipts under `docs/deadcode2/proofs` preserve that
proof independently of later, unrelated reversions.

The required layout locks remain **336 / 1984 / 1408 / 1440 / 944 / 192 / 144 /
624** for Op / Client / ThreadCtx / Shard / FlatStore / Rob<64> / AtomicEntry /
Config, in both namespaces. FlipShiftDetector/FlipController remain 560/1752;
Server remains 108736 in `tomo` and 108352 in `tomo_db0`. GDB type inspection is
read-only; neither binary is started. No ownership migration, read retry,
seqlock, in-place overwrite, or RYOW mechanism was introduced.

**PAD-A is kind A: PRE observable behavior with POST text size and layout.**
Deleted production arms are unreachable and ordinary live semantics are shared.
The observable differences are diagnostics. `tools/deadcode2_pad.py` transplants
PRE's exact INFO/DEBUG LB reporting bodies, including their real estimator, into
production-unreachable RO7 `Shadow=false` code slots, preserving every existing
function/section address and size. Entry jumps redirect only the reporting
functions. A read-only segment holds copied strings and relocated exception
records; the GNU unwind index includes the transplanted bodies. CT16's aliases
reuse the canonical trigger arguments through positional printf conversions.

This is a null-only control, not an independent performance treatment. The
builder verifies `shadow_available` returns true, exact function/section tables,
and equality of every original byte outside the planned patches. Missing
transplant, moved-symbol, and unrelated-byte mutations must all fail. A
serverless ASAN unit twin exercises both modes and database counts 1/4, with
client values 11/13/17 and spreads 19/23/29, trigger counts 31/37, and a computed
PRE estimator of 0.25 (derived split 2/6). POST fails the PRE-schema assertion;
PAD fails the POST-schema assertion. **Do not apply `r7shadow_pad.py` to this
PAD-A:** its false-arm slots are deliberately occupied. Production POST retains
the ordinary R7 PAD machinery unchanged. No PAD-B is supplied.

**Maintainer execution request (not run by this lane).** First review the concurrent external
calib reader update and incorporate the ledger addendum. Run the requested
correctness subset at the gate's real geometry, 16 shards and its ratio:

```sh
GATE_ONLY_JOBS="$(cat docs/deadcode2/gate-jobs.txt)" \
  taskset -c 112-127 tests/gate.sh iteration \
  --server-cores 112-119 --load-cores 120-127 \
  --server-smt '' --load-smt '' --ports 18340-18342
```

Suite/job names are one per line in the manifest. This is a partial correctness
run, not a full green gate receipt. The added INFO assertions run within the
existing `lbfix` unit path; manual PAD selections add no gate row. Selected
correctness rows precede the quick exit at `tests/gate.sh:3366`. **Row delta:
quick +0, full +0. Expected counts stay 500 / 517** (plus the gate's existing
conditional NIC accounting). The gate file is unchanged.

Mainline runs the **14 unchanged cells** in
[generic-merit-cells.txt](docs/deadcode2/generic-merit-cells.txt), with its own
instrument and scheduling. Compare PRE↔POST and PRE↔PAD-A with ABBA order and a
same-binary A/A control; POST↔PAD-A checks the diagnostic control is null. Use
the existing gate offered-load/connection/value-size settings for each row.
The decision is the gate's two-sided null against its same-binary band, per cell:
rate at matched offered load, with p99/p999 guards for latency cells. Report
cycles/op, instructions/op and IPC together, and retain raw receipts. A changed
instruction count alone cannot accept a result. Any non-null result blocks
landing and requires reworking or reverting its category; PAD cannot excuse it
as placement. Append the measured results as `MEASURE-RESULT` in this worktree.

| Metric, every requested cell | PRE | POST | PAD-A |
|---|---|---|---|
| Matched-load rate, p99, p999 | pending mainline | pending mainline | pending mainline |
| cycles/op, instructions/op, IPC | pending mainline | pending mainline | pending mainline |

Final build identities, full byte counts, and serverless proof results are
recorded in the artifact appendix below.

| Final static proof | Result |
|---|---|
| Complete object inventory | 17,009 bodies; 16,993 literal matches; 16,999 matches after resolving exact relocation targets; 10 intentional changed bodies and 6 relocation-only bodies, all listed. |
| Existing hot object inventory | **1492/1492 literal byte matches**, also exact relocation-target matches. |
| Existing linked splitlocal inventory | **393/396** under its unchanged normalizer, `strict_noop=False`; the three differences are unnamed jump-table anchor offsets. Independent bounded-switch proof checks **54/54 identical destinations**. This is disclosed rather than normalized away. |
| RL5 isolated same-budget proof | 1492/1492 literal hot bodies; 396/396 linked physical bodies. |
| PAD structural and negative controls | Exact POST function and section tables; three deliberate mutations rejected in production and ASAN unit images. |
| Data layout | All required locks and both Server layouts equal PRE. |

Only the modified single-DB `t_server.cc` TU receives an extra compile setting: `max-inline-insns-auto=16` (15 before); its existing `large-unit-insns=31582` is unchanged. This restores the ordinary `reply_err` body. No parser, R7, fused, or main-TU budget changed, including across the RL5 extraction.

| Arm | Binary | SHA-256 | .text bytes |
|---|---|---|---:|
| PRE | `build/deadcode2/PRE/tomokv` | `aa0742922e4bfbe130441469754ff647b0e8172cfd079c1cd70376403bc2b53a` | 7812565 |
| POST | `build/deadcode2/POST/tomokv` | `8b8376500d8dd0afbd55cdeea01ba02ea7b7461bf2f4c182917457ee34965b8e` | 7811893 |
| PAD-A | `build/deadcode2/PAD-A/tomokv` | `cb47dbfa8955945ae879c135522503871f3c285780c66515e0a5773b7cf55e97` | 7811893 |

Production source is `2cef2744397e4d6a307b03fc2388f88140e3dbac`; merge-base is `d81b6d3a2b095224d59049dc60342a6ca1574674`. `build/tomokv` is byte-for-byte the POST binary. `.text` changes by -672 bytes; PAD-A has POST's exact executable layout. The full binary/function/section hashes are in [arms.json](docs/deadcode2/proofs/arms.json) and the PAD receipts.

Serverless suites are listed one per line in
[serverless-suites.txt](docs/deadcode2/serverless-suites.txt). Final rebuilt
reorder/R7 ASAN units, flip controller, seeded INFO/DEBUG, `lbfix`, exact flip
wire report, splitlocal forwarding/park controls, writeback (720 deterministic
transport cases), wbland grammar/endpoints/exits/INFO in both namespaces, and all
five TLS socketpair cases pass. Reader replays pass (7 feature-failure tests and
50 LB episode tests). R7 source sync and its stale-envelope negative control,
Python compilation, shell syntax, and whitespace checks pass. The INFO-schema
negative controls fail at the specific seeded-counter assertion, not by timeout
or a crash. Logs are under `docs/deadcode2/proofs/units`.

The LB PAD source guard needed one corresponding update: its frozen reference
still contains the retired `ratio == 0` disjunct. The tool removes exactly one
known disjunct from that reference, records this cleanup explicitly, and still
requires exact source equality for everything else. It never normalizes the
candidate or accepts an arbitrary source change.

To reproduce the principal artifact proofs without starting a server:

```sh
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare build/deadcode2/PRE build/deadcode2/POST build/deadcode2/recheck-hot.json
taskset -c 112-127 python3 tools/deadcode2_artifacts.py build/deadcode2/PRE build/deadcode2/POST build/deadcode2/recheck-all.json
taskset -c 112-127 python3 tests/r7shadow_noop.py build/deadcode2/PRE/tomokv build/deadcode2/POST/tomokv build/deadcode2/recheck-linked --inventory splitlocal
# The preceding existing checker reports the three disclosed anchor moves.
taskset -c 112-127 python3 tools/deadcode2_linked.py build/deadcode2/PRE/tomokv build/deadcode2/POST/tomokv build/deadcode2/recheck-linked build/deadcode2/recheck-targets.json
taskset -c 112-127 python3 tools/deadcode2_pad.py build/deadcode2/POST/tomokv build/deadcode2/PAD-A/recheck build/deadcode2/recheck-pad
taskset -c 112-127 build/core-concurrency-unit deadcode2-info
taskset -c 112-127 build/deadcode2/PAD-A/core-concurrency-unit deadcode2-info-pre
```

The final rebuilt LB planner suite passes: monitor handoff, publication/staleness/allocation controls, both-mode timing/PAD witnesses, all three timing mutants, and the designated POST-rejects-PRE assertion. The complete structured result is [lbplanner-checks.json](docs/deadcode2/proofs/lbplanner-checks.json).
