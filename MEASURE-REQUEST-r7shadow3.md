# r7shadow3 — split isolation and AUTO occupancy floor

Worktree `/home/user/Projects/cx-r7shadow`, branch `cx-r7shadow`, PRE `665a0cb13`.
The owner confirmed the codex phase. This lane starts no server, benchmark, load
generator or gate. Builds and serverless witnesses run on CPUs 112-127.

## Split audit and the unresolved per-boot result

The launch binary has been preserved as `build/r7shadow3-pre/tomokv`. Its SHA256
is `5f72057199d456a09b4145d022fa3a9e3047cba021ace8c7d92c6f0e28a5b81a`, matching the
owner's frozen `bench-bins/tomokv-r7shadow2-665a0cb13` byte for byte.

Source tracing did **not** find the hypothesized request-dependent split leak:

- `main` resolves reorder after both configuration sources and validation, before
  placement, server initialization or worker creation. Mode is already final.
- `Server::init` resolves its private configuration before schedule allocation.
  `overlap=1` allocates the same 64-byte-per-thread shared schedule array for all
  three values. The policy fields use its existing padding. With overlap off,
  split allocates no schedule array.
- Parser stamping and late-read demotion are in the isolated armed call graph.
  `PolicyScope` and the AUTO observer live only in its IO loop. Ordinary
  `ThreadCtx::sample_depth` does not call the observer.
- The old split selectors read the resolved configuration, including on FLIP
  re-entry. No second raw reorder value, environment override or live setter was
  found. Both split executor template types were checked; `<true>` also means
  read-local capability and does not by itself mean fused placement.

POST removes the remaining **split role selectors** entirely: both ordinary
owner-entry sites in `main`, the read-local owner in `rl2s.cc`, ordinary split IO,
and split read-local IO call the baseline directly. This is structural enforcement
of the scope, not an assertion that one of those resolved selectors caused the
old tails. `Server::init` now also honors the PAD capability for direct callers.
Fused behavior remains selected at fused boot.

The old serverless fixture pre-resolved reorder before initialization, weakening
its allocation witness. The new fixture passes the raw value. Its instrumented
R7 object counts operational envelope entries, parser stamping, policy scope,
sampling, queue construction and reorder-info traversal. The allocation witness
counts reorder-requested sidecar allocation and independently compares every C++
allocation's size/alignment sequence through boot and the synthetic workload.
Instrumentation has no release counters, storage, branches or calls. Cold
configuration resolution and capability reporting are intentionally not counted
as operational R7 entries.

At the gate geometry (8 threads, 6 IO + 2 EX, 16 shards), all 12 combinations of
raw `0/1/-1`, overlap `0/1`, and read-local `0/1` passed: operational paths **0**,
reorder allocations **0**, identical allocation traces, FIFO handler order and
RESP retirement. The real INFO handler reports `reorder:0`, `reorder_retired:1`,
no reorder counters/policy, and no schedule array when overlap is off. The
overlap-owned array is inspected for zero reorder state when overlap is on.
Fused positive controls count actual R7 work. All 16 negative controls are
detected, including a sidecar allocated and freed before the final inspection.
Receipt: `build/r7shadow3-split-witness.json`.

The saved six 985K split boots in `tailgen-rs2s2{on,off}/r*-ro*-985000/server.log`
all report the same 32-thread placement: 16 IO + 16 EX, 256 shards, split mode,
overlap on. They do not record effective reorder, INFO, hash seeds, live load
balance state or per-window profiles. They also include population work in their
shutdown counters. Their executor operation totals are similarly balanced in
both the slow and fast boots; IO distributions vary in both arms and do not
uniquely distinguish the slow boots.

There are real once-per-boot/connection choices independent of reorder:
`main` seeds hashing with `getrandom`, address/allocator placement varies between
processes, and SO_REUSEPORT hashes connections onto separately created IO
listeners. The tailgen seed controls arrivals, **not** those server choices.
They can feed different load-balancer trajectories. These are candidate
explanations, **not a demonstrated cause**. Three whole ON boots followed by
three whole OFF boots cannot distinguish a request effect from those choices or
run-order drift. The 11.207/4.367/9.863 versus 4.399/4.103/4.199 ms observation
is retained as a blocking failed null, not dismissed as noise. The precise cause
of the bimodality remains unresolved; this lane has no supporting profile and
will not manufacture one. POST needs the matched split null measurement below.
One aggregate per boot also cannot establish whether the deciding event occurred
at boot or later in the load-balancer trajectory.

## AUTO occupancy floor

The current fused schedule uses `kGenthreadExBatchOps` (32), including with
overlap armed. AUTO now requires sampled owner depth **strictly greater than
that gather capacity**, in addition to all three existing conditions: a current
short head behind a Long, depth at least the rolling mean, and more displaced
short heads than Longs over the window. The full sample-window prerequisite and
same-tick disengagement remain. There is no offered-load percentage or new knob.

Fresh synthetic windows at 16/32/64 tasks test the 0.5x/1x/2x boundary. All other
conditions are deliberately true. They require shallow windows to stay off,
the 2x window to engage, immediate release on a shallow sample, and continued
inactivity after the mean has decayed to that shallow depth. The existing tests
independently exercise the three earlier conditions. The production inbox test
now uses two real gathers, rather than its old four-task queue, and checks the
actual priority permutation followed by a disarmed FIFO drain. Mutants remove
the floor, make it inclusive, prevent engagement and prevent disengagement.

This proves the queue-depth boundary, not that every 880K sample lies below it.
The 880K no-engagement and 985K positive-engagement requirements remain box
acceptance conditions. Disarmed AUTO still does parse-side shadow stamping and
samples the existing signal tick; no claim of zero AUTO overhead is made.

## Wall and acceptance scope

The following are the **owner's round-2 measurements**, not this lane's results:

| Fused offered rate | ON p999 ms | AUTO | OFF | PAD A | Reading |
| --- | ---: | ---: | ---: | ---: | --- |
| 880K | 2.78 | 3.07 | 2.75 | 2.78 | Forced ON null; AUTO costs 12% |
| 985K | 7.04 | 6.83 | 7.60 | 8.04 | ON improves 7% vs OFF, 12% vs PAD |
| 1030K | 16.0 | 16.6 | 16.1 | 15.5 | Null in round 2 |

Round 1 also improved at 985K (14% vs OFF, 12% vs PAD). That **93%-of-wall
regime** is the reproducible acceptance target. The 1030K wall gain is **not
reproducible**: round 1 improved 20%, round 2 is null; the pooled six-round 10%
gain sits inside approximately 30% spread. No wall-specific code change or
round-3 wall speedup is claimed, and a wall rerun is not an acceptance substitute.

## Mainline measurement request — not run by this lane

Use the current gate instruments and their validated geometry/pins. Keep
atomics, key balancing and client balancing armed. Tailgen retains the standing
32-core server / 256-shard geometry, read-local=0, overlap=1, 8:2 GET/BITCOUNT,
512 connections, Poisson arrivals and outstanding bound 64. This differs from
the 8-thread/16-shard serverless gate-geometry witness; report both accurately.

| Cell | PRE | POST OFF | POST ON | POST AUTO | PAD A ON | Deciding number |
| --- | --- | --- | --- | --- | --- | --- |
| 2s tails 985K | round-2 0/1 | 0 | 1 | -1 | optional | Same-binary ON/OFF/AUTO null |
| 1s tails 880K | round-2 AUTO/OFF | 0 | 1 | -1 | 1 | AUTO stays inactive and matches OFF/PAD |
| 1s tails 985K | round-2 ON/AUTO | 0 | 1 | -1 | 1 | Preserve the PAD-controlled short/overall p999 gain |
| rate h05 | v7 | cell ro=0 | — | — | cell ro=0 | Matched-load rate, cycles/op, instr/op, IPC |
| rate h07 | v7 | — | cell ro=1 | — | cell ro=1 | Same metrics; POST vs PAD isolates armed cost |

For h05/h07 use GET p32, 512 connections, 1s, read-local=0, overlap=1 and the
existing load ladder. Compare both POST and PAD against the same v7 reference;
retain the round-2 PRE read to attribute this revision. The rate instrument's
private-cell grammar is ro=0/1; do not silently relabel a rate cell as AUTO.

Use at least three balanced/interleaved boots per tail arm with matched arrival
seeds. The standing `calib/tailgen-run.sh LABEL BINARY REORDER ROUNDS RATE`
currently runs whole-arm blocks and resets seeds to 1..ROUNDS; mainline must
control interleaving/seed pairing explicitly rather than call block order a
paired design. Preserve binary hashes, requested/effective config, initial role
placement, raw per-round JSON and per-window profiles for any failing split boot.
Record INFO SERVER and INFO LB before and after traffic. A repeated split
separation fails acceptance even if the unit and code audit pass; investigate
the bad and good boots, including a repeated OFF/OFF null, rather than average
away the bimodality or attribute it to R7 without a path witness.

The existing `TG_INFO=SERVER` hook collects only an end snapshot. For AUTO,
collect one immediately after population and another after the traffic window:
880K requires **zero engagement delta**, no engaged owners at the start, and
increasing samples. 985K requires increasing samples, engagement evidence and
permutations during traffic (an already-engaged starting owner is explicit
evidence). Population-only engagement cannot satisfy the 985K witness. An AUTO
arm that never engages at 985K does not pass by coincidentally having low tails.

Judge paired **short p999 and overall p999**; retain short/long p99 and p999,
achieved load, completions, outstanding maximum, omitted arrivals, over-limit
fraction, mean/p50, pacing lag and drain time. Lower achieved load or long-class
starvation is not a gain. Use the instrument's standing null, not an invented
tolerance. No round-3 PRE/POST rate or tail is available yet; all requested
measurement cells are **pending**.

The maintainer must still boot both modes and run `tests/gate.sh iteration` with
the ordinary GET/SET/MGET/MSET regression controls before merging. No gate row
was added/removed and no EXPECT constant was edited. They remain 419/435 at
lines 254/255; the quick-tier exit is at line 2764. The new split witness is an
explicit serverless preflight, not a claimed extra gate row.

## Final artifacts and validation

Server source revision: `6eb8e3bca`; subsequent changes are tests/reporting only.
PRE was preserved before editing and checked against the owner's frozen binary.
POST was rebuilt with the default release flags. No measured server result below
is implied by a successful build or serverless check.

| Arm | Path | .text bytes | SHA256 |
| --- | --- | ---: | --- |
| Round-2 PRE | `build/r7shadow3-pre/tomokv` | 4190381 | `5f72057199d456a09b4145d022fa3a9e3047cba021ace8c7d92c6f0e28a5b81a` |
| Round-3 POST | `build/tomokv` | 4190557 | `e79aeea3f0008c37022ab8f3db720d450b8ed108736f02c217cf6a2781d8613e` |
| Kind-A FIFO PAD | `build/tomokv-pad` | 4190557 | `a1b9a51cf758c34de6d98137e9c5484cdfc3d9b59cc43553509db80819e2d990` |

**PAD A is a behaviour twin: PRE FIFO (`--reorder 0`) behaviour with POST's exact
text size/layout.** It is not round-2 forced-shadow or old ratio-only R7 behavior.
Run it with `--reorder 1`. It differs from POST by exactly one byte: the capability
return immediate at file offset 3665589 changes `01` to `00`. Both files are
91896336 bytes; every other byte, symbol and section is identical. Receipt:
`build/tomokv-pad.json`. The text change from PRE is +176 bytes; no inverse PAD
arm is requested.

Completed checks:

- Default release, PAD and all seven `make unit` programs built/passed without
  compiler warnings or errors (`build/r7shadow3-final-build.log`).
- The unchanged strict normalizer/exclusions report **169/169 identical FIFO
  bodies** against PRE (`build/r7shadow3-final-off-witness/audit.json`). Cold
  selector edits required compiler-budget locks of 146255 in main and 161715
  in rl2s; genthread stays 128880. No differing FIFO body was waived.
- The final instrumented split witness passed all 12 cells and 16 forbidden
  path/allocation controls, and binds its binary SHA in
  `build/r7shadow3-split-witness.json`. `nm` finds no test counter/interposer
  symbols in the release executable.
- Real production parser/inbox/handler fixtures passed for POST and a separately
  patched kind-A unit twin (`build/r7shadow3-final-engagement{,-pad}.log`). They
  preserve three-FIFO priority, per-connection eligibility, special barriers,
  the oldest-task fairness turn, late read-local demotion, foreign-owner shadows
  and RESP retirement. The deep AUTO fixture checks the fairness turn after one
  gather of priority picks; it does not relax that bound to put every short first.
- The AUTO depth tests and ASan/UBSan unit passed. All eight scheduler/policy
  mutants failed their required assertions (`build/r7shadow3-auto-unit.log`,
  `build/r7shadow3-auto-asan.log`, `build/r7shadow3-auto-mutants.log`).
- `netcmd-unit config` passed (`build/r7shadow3-final-config.log`). Generated
  envelopes, `bash -n tests/gate.sh` and `git diff --check` passed.
- Debug-info type queries confirm Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
  FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624, ModeScheduleStats 64
  (`build/r7shadow3-final-layouts.log`). GDB did not run/start/attach a process.

Reproduction commands (all serverless):

```sh
taskset -c 112-127 make -j8 all build/tomokv-pad build/reorder-engagement-unit build/r7shadow-split-unit build/netcmd-unit unit
taskset -c 112-127 python3 tests/r7shadow_split_witness.py build/r7shadow-split-unit --receipt build/r7shadow3-split-witness.json
taskset -c 112-127 python3 tests/r7shadow_noop.py build/r7shadow3-pre/tomokv build/tomokv build/r7shadow3-final-off-witness
taskset -c 112-127 ./build/reorder-engagement-unit on shadow
taskset -c 112-127 python3 tests/r7shadow_pad.py build/reorder-engagement-unit build/r7shadow3-engagement-pad --scope fifo --receipt build/r7shadow3-engagement-pad.json
taskset -c 112-127 ./build/r7shadow3-engagement-pad off shadow
taskset -c 112-127 make build/r7shadow-unit-asan
taskset -c 112-127 ./build/r7shadow-unit-asan
taskset -c 112-127 python3 tests/r7shadow_mutants.py
taskset -c 112-127 ./build/netcmd-unit config
python3 tests/r7shadow_sync.py
```

Append the quiet-box outcomes to `MEASURE-RESULT`. Split-tail equivalence and the
AUTO 880K/985K separation are still **unmeasured acceptance requirements**; this
delivery does not claim the per-boot latency failure is cured or merge-ready.
