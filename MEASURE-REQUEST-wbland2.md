TomoKV wbland2 — detector parity audit and measurement handoff, 2026-09-29

The supplied study and wbland1 already compute the same f sequence from the
same pass timestamps, idle counters and ownership counts. The requested
100-us detector-cadence difference is absent from those sources. This lane
copies the study's complete Window literally, adds an independent replay and
builds the requested arms; it does **not** claim to have fixed the measured
tail loss. The live eight-sample acceptance remains pending.

Worktree `/home/user/Projects/cx-wbland`, branch `cx-wbland`. Required mainline
`37eeb5e90be9997805cfe2456021ad07dc0c18f9` was merged first as `5e909a315`;
the sole conflict retained both topology and writeback build prerequisites.
Production/replay commit `158a943c1`; matched-baseline object comparison
`7dbc115f8`. All builds and offline checks were pinned to cores **112-127**.
No server, benchmark, load generator or gate was run. Nothing was pushed.

Detector source and exact diff

The study binary `/home/user/Projects/cx-wbmode/build/tomokv-pol2-k1` matches
its recorded SHA-256, `7df8c94a99728144d2ef1db230a12a4394e23da5f93f91d464bc753477a8c710`.
Its lane's evidence records source commit
`60e4221ec5cf36425eb339d3eca608c1a1e64a6d`; the feature originated in
`35558d75f`, with subsequent lane commits through `8dc139364`. The replay
extracts the **complete original** `wbmode.h` and original `signalacct.h`
from that pinned commit, and the complete original wbland `wb_rule.h` from
`f6d2e969f`. Only test include paths and namespaces are relocated. It does
not reconstruct a second detector from the candidate's equations.

Both `60e4221ec:src/core/io_loop.h:532` and
`60e4221ec:src/core/reorder.cc:825` execute this unconditionally on every pass,
exactly as the current two envelopes do:

```cpp
const uint64_t pass_ns = tenure.pass();
wb_policy.pass(pass_ns, sig.idle_ns, self_->clients().size());
```

The current `IoTenure::pass()` samples `Clock::now()` and returns that fresh
value **on every call**. Only `account(next)` and its shared `busy_ns` store
are gated by `publish_at_ = next + 100000`. The study accounts eagerly, but
neither writeback detector reads that published busy counter. The study's
own `MEASURE-REQUEST-wbmode.md`, “One signal, one window definition,” explicitly
documents this independence from delayed busy-counter publication.

| Property | Study pol2-k1 | Original wbland1 | wbland2 |
| --- | --- | --- | --- |
| Detector input/cadence | Every pass: wall timestamp, current idle, owned clients | Same | Same |
| Busy-counter publication | Every pass | First pass, then 100 us, plus exit | Same as wbland1 |
| Block width | `max(1, owned)`; ownership changes affect the next block | Same | Literal copied Window |
| History/hold | Current + previous completed block, weighted by duration; hold between boundaries | Same | Same |
| Fixed-point map | `curve(floor(256*(wall-idle)/wall), 1)` | Identity curve specialized away | Same |
| Startup/zero duration | f=0; two valid blocks required; zero duration holds | Same | Same |
| Raw zero-idle flag | `saturated = rest == 0`; unused by pol2-k1 | Removed | Restored literally |

The production diff restores the study's `saturated` member and assignment,
plus provenance/cadence comments. `Window` is byte-for-byte source-identical
to the pinned study's definition. This raw flag is used only by the study's
separate switching policy; our linear `fraction = window.busy` does not use it.
There is no additional engage/disengage band in pol2-k1 to port.

The 0/1/-1 grammar, no-allocation fixed policies, split AUTO half-rule fallback
and separate split probe remain. The 512 B clause, acquire walk, empty/full
pipe and MGET exits, all Phase 2 schedules and tenure hook locations are
unchanged from wbland1. The selection/Phase 2 suffix was compared byte for
byte as source. All eight locked type-size assertions compile. No new
per-operation synchronization, clock or completion-side store was added.

Replay witness and the requested negative control

`tests/wbland2_replay.cc` drives the production candidate, original study
policy 2 / arm 0x103, and original wbland1 through the same saved CSV inputs.
It uses the actual current 100-us and original eager IoTenure implementations
with an injected clock. It checks every f, the candidate's complete Window
state, fresh timestamp return on every pass, and equal final accounting.

No live-recorded busy trace was present in the two lane artifacts, and none
was supplied during this task. Consequently the completed replay uses a
**synthetic**, persisted trace: 20 ms warm, 100 ms burst, 40 ms recovery,
20 ms idle, then a new tenure with zero-duration intervals. It varies pass
durations and ownership, reaches f=0/f=1, and is explicitly labeled synthetic
in `build/wbland2/synthetic-burst.csv`. This is not a recording of the
maintainer's 931K session and does not fulfill that live-recorded evidence
requirement. The runner accepts a real trace via `--trace PATH` without
changing either detector. Columns are `tenure,wall_ns,idle_ns,owned`, with
relative cumulative idle starting at zero for each tenure; retain every pass.
An INFO-only or aggregate busy fraction lacks the per-pass/ownership history
needed for this exact replay.

Output in each database namespace:

```text
PASS wbland2 replay: rows=18771 tenures=2 windows=8029 transitions=2837 candidate_mismatches=0 wbland1_mismatches=0 busy_counter_differences=15000 cut_gated_differences=14177 idle_endpoint=1 full_endpoint=1
CONTROL first_difference_row=33 wall_ns=297984 pol2_f256=65 cut_gated_f256=0
FAIL wbland2 replay: candidate f sequence equals pinned pol2-k1 on every pass
```

The FAIL above is required with exit **1** for a deliberate mutation that
calls the candidate only at 100-us accounting publication cuts. Success,
crash, timeout or a different assertion fails the runner. Both namespaces
pass the positive and reject this mutation: **4/4 strict outcomes**.

The requested negative result for the **actual original tenure-based
wbland1** cannot honestly be reported: it has **zero** mismatches. The
deliberately cut-gated mutant is not the original landing. Equal f for equal
inputs does not establish equal live pass timing, ownership, idle histories
or latency between complete binaries. The supplied tail loss remains real;
this audit rules out the alleged input-cadence difference in the named source.

Receipts: `build/wbland2/replay-proof.json`, `sequence.csv`, `source-proof.json`,
and the committed `tests/wbland2_evidence.json`.

Per-pass cost

Finite ptrace single-step counts through one noinline detector call, including
called helpers and entry/return, using the same flags and fixture for all
three sources. This is an instruction receipt, not a timing benchmark,
cycles/op, IPC or a throughput prediction. The window-closing case is seeded,
has a previous 1-us block, and closes another 1-us all-busy block at W=16.

| Detector invocation | Original wbland1 | wbland2 | Pinned study pol2-k1 |
| --- | ---: | ---: | ---: |
| Fixed bypass | 4 | 4 | 4 |
| AUTO / fraction, ordinary pass | 9 | 9 | 9 |
| Valid two-block closing pass | 94 | 97 | 108 |

The literal restored raw saturation flag costs **+3 instructions per closing
pass**, zero on the ordinary pass. At stable W, this slice averages
`9 + 88/W` for wbland2 versus `9 + 85/W` for wbland1, after startup. All three
closing paths include 17 library instructions for wide division. The study's
remaining cost is its general policy/curve dispatch. INFO publication,
IoTenure accounting, selection, encoding and network work are outside this
slice. `build/wbland2/costs.json` and `costs.log` contain the raw receipts.

Offline verification

| Battery | Strict outcomes |
| --- | ---: |
| Existing detector endpoints/windows/grammar/publication and mutants | 33/33 |
| Runtime-derived clauses and acquire/byte/marker mutants | 37/37 |
| Fused/reorder/split/overlap/read-local physical paths and mutants | 31/31 |
| Original policy 1 policy/phase/stages/split-phase/split-overlap | 180/180 |
| Pinned-source replay plus cut-gated controls, both namespaces | 4/4 |

Config parser and serverless CONFIG command checks also passed; gate shell
syntax and generated R7 envelope parity passed. GET/SET has **16/16 opcode
and relocation identities against locally rebuilt 37eeb5e90 objects**.
The first comparison against the older 9c4717da0 objects gave 14/16: the two
`cmd_set_notify` wrappers differ, and both match 37eeb5e90. That older failure
is retained in `build/wbland2/identity-vs-9c.json`; the matched-baseline pass
is `build/wbland-command-identity.json`. Release and replay builds emitted no
warnings; intentionally deleted mutant code produced its expected unused
variable/parameter and indentation warnings. Both live boots and the gate
remain for mainline.

Frozen arms and PAD

All candidate arms have identical section sizes, symbol addresses and bytes
except the two cold `wb_rule::build_arm()` immediates. They intentionally
retain one ELF build ID; use SHA-256 to identify them. Do not override a named
arm with `--wb-policy` during measurements.

**PAD kind A, behaviour twin:** mainline's fixed half-composite behaviour in
the candidate's exact text/layout, with detector/publication disabled. Common
fixed-policy dispatch remains, so pol1 versus mainline still has to be null.
Candidate `.text` is **7,608,109 B**, versus 37eeb5e90 **7,576,545 B**
(+31,564 B) and original wbland1 **7,611,245 B** (-3,136 B, including the
required mainline merge). Every image has `.tdata=112`, `.tbss=480`.

| Artifact | SHA-256 |
| --- | --- |
| `build/tomokv` — AUTO | `5b0aa57973ecfea83fe3d47d3560d523db133564b9308a8ec550f1aea7f096d3` |
| `build/tomokv-pol1` | `eefe0f0173ad88d6d5a4bc49044cdac6a1de145d726eff6e177a2e9920cd9ffe` |
| `build/tomokv-pol0` | `be72d796cc9fbdb13c5f5b6f25a1c4daf4d921e05d6a27e532b4274c31082940` |
| `build/tomokv-pad` — A | `24228d3445be5535a3e1d98c3b77bbb7c4137203d68b8e6fd088169d0467c90c` |
| `build/tomokv-auto2s-probe` — retained study probe | `bea143c3d783ce33c86c12fd32860c8cdd265dc1e2953083639704e4ae1c8b67` |
| `build/wbland2/tomokv-wbland1` — preserved original AUTO | `3ced0605f055a4dd9e780f68c1490fcaada17635b591d588a617a1c8a9a376f3` |
| `/home/user/Projects/cx-wbmode/build/tomokv-pol2-k1` | `7df8c94a99728144d2ef1db230a12a4394e23da5f93f91d464bc753477a8c710` |
| `/home/user/Projects/bench-bins/tomokv-headline-37eeb5e90` | `ba5ec37b90bc0f8f92a2dad0931befc85e1ab2a491182861cd612822f65a8869` |
| `/home/user/Projects/bench-bins/tomokv-headline-9c4717da0` — prior campaign reference | `84ddb8abba4d8c32196edadb860da45114379490432a900dfee76efb71bfdd72` |

`build/wbland-artifacts.json` preserves the exact-byte proof and the old
campaign reference. `tests/wbland2_evidence.json` adds the merged reference,
original AUTO and study arm receipts.

Mainline measurement request — unchanged cells, stronger tail acceptance

Use the gate's own instrument, quiet box, fresh identical-arm nulls, matched
offered load and interleaved ABBA blocks. Keep the prior session's reference
and all server/loader placement and workload settings fixed when reproducing
its percent deltas. Also compare pol1 with frozen **37eeb5e90**, so the required
mainline merge is not charged to detector behaviour. Record achieved/offered
rate, short p50/p90/p99/p999, long p50/p99, commands/send, cycles/op,
instructions/op, IPC and per-arm spread. A failed saturation proof, failed
witness or >2% identical-arm spread leaves the cell unresolved.

1. **Acceptance: 931K GET:BITCOUNT 9:1, 100 ms burst, reorder 0 and 1.**
   Run new AUTO head-to-head with the exact study `tomokv-pol2-k1`, in the
   same session, **at least eight valid samples per arm per reorder state**.
   Include the same reference, pol1, pol0 and PAD A; retain original wbland1
   for attribution. Preserve the established keyspace, long-operation size,
   pipeline/connections, burst timing, warmup/duration and CPU placement from
   the September 29 comparison. The new AUTO p99 percent delta must be
   **within 2 percentage points of pol2-k1 in each reorder state** over eight
   samples, using the same common-reference normalization. Report the direct
   AUTO/study ratio and every sample too. Judge each reorder state separately;
   throughput or the other reorder state cannot compensate for a failed tail.
   Keep p50 and p999 visible to catch the earlier median cost. A source-parity
   pass is not a substitute for this acceptance.
2. **Same 14-cell merit:** `tests/wbland_merit_cells.txt`, AUTO and pol1 versus
   the reference, PAD on deciding cells, pol0 at p8. Server 0-31, loader pool
   32-111; 512 connections, four loaders for p1/eight otherwise; preserve each
   row's read-local/overlap/reorder/atomic values. Pol1 must be null; preserve
   p8 gains, with other saturated cells inside measured twin/null spread.
3. **Same 4096 cells:** `tests/wbland_4096_cells.txt`, GET/SET p1/p8/p32 in
   both modes; eight loaders, same pools, split 16 IO + 16 EX. AUTO/pol1/PAD
   versus reference, pol0 as needed. Preserve p1 latency and deeper-pipe rate.
4. **Same steady ladders:** GET:BITCOUNT 9:1 and 8:2 at 700/800/880K offered,
   warmup 5 s, duration 20 s, at least two interleaved rounds and more near
   spread. AUTO/pol1/pol0/PAD/reference; fused reorder 0/1 and split overlap
   0/1. AUTO must stay within pol0 spread below the knee; pol1 must be null.
5. **Same single-process ramp:** 500/600/700/800/880/900/931/950/1000K and
   reverse, then genuine idle, for both mixes. Keep connections/server alive;
   retain per-owner INFO busy256/f256/window_passes/windows plus LB signals.
   Run fixed anchors and the split probe too. Demand completed windows and
   response to observed busy demand; aggregate offered load does not prove
   f=1. For the outstanding recorded replay, save each owner's pass timestamp,
   cumulative idle, owned count and tenure boundaries; do not infer them from
   the slower INFO publication stream.
6. **Same 25GbE rig:** two-netns GET/SET p8 and p32, AUTO/pol1/PAD/reference,
   pol0 p8 anchor, fresh nulls and ABBA. Preserve NIC/CPU/loader settings and
   capture send counts and matched-load counters. Require p8 benefit and p32
   neutrality inside the qualified spread.
7. **Same split coverage:** production AUTO remains fixed half. Retain the
   existing probe on `tests/wb_rule_2s_cells.txt`, split 4096, both ladders and
   ramp: GET/SET p1/p8/p32, MGET/MSET p8 and tails, 16:16 IO/EX. Repeat deciding
   h21/h22 and w2g8/w2s8 with overlap/read-local 0/1 and reorder null checks.
   Compare IO/EX demand; do not reclassify deferred work as idle or arm split
   AUTO without its own acceptance.

The supplied September 29 results are historical inputs, not new measurements:
original AUTO p8 GET/SET +9.5/+9.1% loopback, GET p8 +15.6% wire; p32 inside
twin spread, 4096 flat, pol1 null. Four-sample burst p99 was AUTO +3.0/-3.4%,
PAD +3.1/+1.9%, study -8.6/+2.3% for reorder 0/1; reorder-off p50 was AUTO
+10.2% versus study +5.8%. Earlier eight-sample study p99 was about -15/-10%.
No POST rate or latency result is claimed here; all new-arm deciding cells
remain **pending mainline**.

Reproduction and gate bookkeeping

Build/offline replay commands only:

```sh
taskset -c 112-127 make -j16 all wbland-units build/config-parser-test build/netcmd-unit
taskset -c 112-127 python3 tests/wbland2_checks.py check
taskset -c 112-127 python3 tests/wbland2_checks.py check --trace /path/to/recorded-burst.csv
taskset -c 112-127 python3 tests/wbland2_checks.py costs
taskset -c 112-127 python3 tests/wbland_checks.py check detector
taskset -c 112-127 python3 tests/wbland_checks.py check clauses
taskset -c 112-127 python3 tests/wbland_checks.py check paths
taskset -c 112-127 python3 tools/wbland_artifacts.py arms
```

The command with `/path/to/recorded-burst.csv` was **not run**; it is the entry
point for the missing live input. Frozen mainline source was archived under
`build/wbland2/mainline-src`; its four GET/SET objects were built on 112-127.
Their identity check is:

```sh
taskset -c 112-127 python3 tools/wbland_artifacts.py identity --pre-build build/wbland2/mainline-src/build
```

No new gate row was added in wbland2: replay extends the existing detector row.
The inherited three wbland rows are collected at **tests/gate.sh line 2742**,
before the quick-tier exit at **line 2871**. The merged topology rows are also
before that exit, as `MEASURE-REQUEST-rltopo2.md` already records. This tree's
maintainer-owned constants remain `EXPECT_QUICK=441`, `EXPECT_FULL=461`, exactly
as on merged mainline. Required counts are **446 = 441 + 2 topology + 3 wbland**
for quick and **464 = 461 + 3 wbland** for full, plus the existing optional NIC
adjustment. No lane edit changed either constant. After performance acceptance
and the maintainer's count update, mainline runs `tests/gate.sh iteration` at
its normal eight-core, 16-shard, 6 IO + 2 EX geometry and confirms both boots.

This handoff stops at the report. The recorded-trace requirement and the
eight-sample tail acceptance are explicitly outstanding.
