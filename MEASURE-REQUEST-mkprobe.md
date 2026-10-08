# MEASURE-REQUEST — mkprobe

Instrument lane, branch `cx-mkprobe`. No performance claim. Gate rows **+0/+0**.

Code is committed and the serverless proofs pass. The requested live smoke was
**refused by the unchanged quiet preflight three times for each cell**; it started
zero servers and zero load generators. Mainline must rerun the smoke on an idle box.
The full campaign also has the fixed-split telemetry conflict below. It is not
ready to queue as an unattended successful campaign until that conflict is resolved.

## Scope and the observation conflict

Initial and final synchronization: `git merge origin/cpp`, latest merged origin
`65a9d0a22`. Final code proof: `11925a9f8efc288c086ea3e263651ec2ee3bc8d8`. `src/` and
`tests/gate.sh` have no lane diff. `EXPECT_QUICK` / `EXPECT_FULL` are untouched.
There are no new gate registrations. No production counter, layout or hot path changed.
The only existing source edit is the positive-integer `TOMO_MULTI_KEYS` override
of `tests/abba_workloads.py`'s `MULTI_KEYS`, defaulting to exactly 8.

The requested age/delay contract is stronger than the available fixed-split
instrumentation:

* `src/core/server.h:358` initializes flipctl only for Split **and** `flip_auto != 0`.
* `src/core/server.h:512-514` obtains age sampling from flipctl's signal rate.
* `src/core/flipctl.h:377` initializes that rate to zero. `flipctl.cc:647` arms
  it during a maneuver; `:1175` and `:1258` disable it again.
* The inherited fixed-split posture is `--flip-auto 0`. Merely choosing 2s does
  **not** produce age/delay samples. Enabling flip would introduce a different
  placement/controller experiment.
* `lbsignals.cc` emits `lb_fused_*` in 1s and `lb_io_*` / `lb_ex_*` in 2s. The
  tool preserves the native names; it never manufactures fused values in 2s.

The tool prints **not available** for 1s age/delay and 2s fused-only names. For
2s it requires executor queue-delay and oldest-age sample counts to **advance
inside the central interval**, and their measured values to be positive. Stale
warm-up samples and zero values fail. Consequently the existing fixed-split
campaign fails this contract. The owner was asked whether to retain that strict
failure or authorize a separate flip-enabled telemetry pass; the implementation
currently retains fixed geometry and strict failure. No missing production
measurement was replaced with an inferred value, and no production change was made.

## Cells, modes and row contract

`tests/mkprobe_cells.txt` contains **19** cells (the note's “~18” was approximate).

| IDs | Definition reused |
|---|---|
| m02 m03 m05 m06 m26 m27 m50 m51 m53 m54 m74 m75 | Exact rows from `tests/headline_cells.txt` |
| p8g p8s h05 h06 d128g_l0 | Exact rows from `tests/wb_rule_cells.txt`; h05/h06 IDs originate in headline, and wb_rule records the private-control provenance |
| mk128g mk128s | New rows: m03/m06 with only ID and depth changed to p128 |

No existing ID was re-derived or repurposed. Existing explicit generator pins
are retained; unpinned rows use `--instances 8`. Load-floor calibration metadata
is not borrowed for the modified instrument or the key sweep.

The 14-cell null is explicitly frozen as the twelve existing multi-key IDs above
plus h05 and h06. Its two arms use the **same path, SHA256 and wb-policy=1**;
three ABBA blocks produce six samples per arm per cell. Both median rate and
cyc/op must agree within ±0.15%; each same-arm range must be at most 2%.
Every contributing cell must also have median productive-role occupancy ≥95%.
A failed null exits nonzero and prevents dependent collection/verdicts.

| Mode | Collection |
|---|---|
| `null` | 14 cells × A/B × n=6, identical binary/policy, ABBA order |
| `probes` | 19 cells × n=6; core, coherence/TLB and symbol passes, each a fresh restored boot; **one combined row** per cell/sample |
| `counters` | Core counters and all INFO/shutdown telemetry; also supports the explicitly labeled `--atomic 0` diagnostic |
| `coherence` | Core pass followed by the separate five-event memory group |
| `symbols` | Core pass followed by an owned-server perf-record pass |
| `wb-pair` | m02 m03 m05 m06 p8g p8s h05 h06 × wb-policy 0/1; same binary, three ABBA blocks, six samples per arm |
| `keys` | m02 m03 m05 m06 × {2,3,4,7,8,9,16} × n=6; alternating ascending/descending sweeps; cycles **per key** |
| `smoke` | One sample each of m02 and p8g, with bounded quiet-only retries; never verdict evidence |
| `report` | Read/reconcile receipts and rows, render arithmetic and M1–M5 verdicts; starts no workload |

The stdout grammar is `MKPROBE_ROW <JSON object>`. Durable `rows/<job>.json`
and `rows.jsonl` retain the complete evidence; each job key includes cell, key
count, arm and sample. The stdout row is compact and points to those artifacts.
Complete rows include rate, instr_per_op, ipc, cyc_per_op, cycles_per_key,
retired_per_send, empty_serve_fraction, atomic_fanout_cuts,
atomic_read_cuts_held, cmdstat_mget_calls, cmdstat_mset_calls and native-role
masked-lane / age / delay columns. `keys` denotes the multi-key override;
`keys_per_command` is 1 for single-key controls. Missing required counters fail.
Failures have the same primary columns marked “not available”, with the reason.

Source/binary/memtier/perf SHA receipts, perf version and event descriptions,
CPU model/microcode, kernel/boot ID, relevant allocator/loader environment,
geometry, split ratio, generator count and actual argv are retained. Mainline
null reuse requires these bindings to match. `--output` must be fresh;
`--resume` requires an identical normalized receipt, skips complete job files,
and places new attempts in new directories. Prior attempts remain on disk and
are listed in the current row's attempt history. Owned process groups are stopped
and reaped on failure and interruption; the tool never kills another lane.

A shared SHA-bound snapshot cache is populated in an **unscored setup process**.
Every measured pass uses a fresh process and fresh copy of that snapshot. This
keeps wire population out of shutdown WB totals and fixes the data/hash seed
across samples. Successful private snapshot copies are removed; failed copies
and cached source images are retained. This is a restored-data diagnostic, not
a claim of equivalence to the headline harness's population history.

## Counter scopes and plausibility checks

The core perf group uses `abba_profile.EVENTS`: cycles, instructions and
reference cycles. `:Duk` pins the group and counts user/kernel execution on the
**server CPU set only**. Raw counts are never scaled. Every CPU/event must be
present, every group member must have the same running time, and running must
be 100%. Unsupported, missing, duplicate or multiplexed counters invalidate a
sample. Derivations follow `abba_profile`:

```
rate       = central workload calls / central elapsed seconds
instr/op   = grouped instructions / central workload calls
IPC        = grouped instructions / grouped cycles
cyc/op     = grouped cycles / central workload calls
cycles/key = cyc/op / actual keys per command
```

Perf brackets encompass the INFO endpoints; overhang >1% of the window fails.
They are explicitly approximate central-command ratios, not exact per-request
PMCs. The full, drained memtier HDR count must equal the whole-run server
command delta exactly. JSON Count/HDR differences use the existing finite
connections×pipeline bound, never a percentage tolerance. Connection/protocol
errors, interrupted loads, non-finite rates, impossible IPC/cycle counts,
missing connections, changed key counts and generator CPU exhaustion fail.

The second pinned group is a separate pass, with its **own command denominator**:

```
ls_any_fills_from_sys.all
ls_dmnd_fills_from_sys.all
de_dis_dispatch_token_stalls1.store_queue_rsrc_stall
ls_l1_d_tlb_miss.all
ls_l1_d_tlb_miss.all_l2_miss
```

The first two produce `(any − demand)/op`. This residual includes non-demand
fills and is not asserted to be a unique RFO count. Negative residuals fail.
The store event is dispatch-stall **cycles** for store-queue tokens; the final
event counts **page-table-walk requests**, not walker duration. Walk requests
cannot exceed all dTLB misses. All raw CPU counts are retained.

Symbol mode uses `perf record -p <owned-server-pid> -C <server-cores>` at 199 Hz,
with DWARF call graphs and `perf report --inline --no-children`. It reports
exclusive, period-weighted shares for malloc, free, realloc, je_* (separately),
the allocator union, SmallBuf::grow, refresh_snapshot_floor,
active_snapshot_floor, build_initial_groups, xshard_prepare, xshard_execute
and assemble_mget. The allocator union overlaps its component columns; do not
sum them. Lost samples or unreconciled period totals fail. An unobserved symbol
is not proof of zero cost. Raw perf.data and symbol tables remain available.
The collector reserves 5 GiB beyond its estimated artifact needs; the full
symbol campaign can retain roughly 100–130 GiB of stack/sample data at 32 CPUs.

`retired/sends_submitted` and `serves_empty/serves` cover the entire **restored
measured boot**, including warmup, tail and bounded observers. They are not
central deltas; sends must drain and shutdown must be clean. Observer calls
must be below 0.1% of workload calls. Atomic fanout cuts is a central delta;
held cuts is the maximum **observed gauge**, not a cumulative cut count.
At atomic=1, fanout cuts may be zero by construction; the report directs the
reader to held cuts. The separate atomic=0 MGET diagnostic prints the
fanout-cuts/calls arithmetic. Queue values are observed central maxima with
native role provenance; cumulative full-event counts are labeled as such.

Quiet screening uses the unchanged 20-second `gate_quiet.QuietMonitor`
selected-core budget and intended-port exclusion. A separate read-only /proc
screen tracks CPU progress of known competing compilers/servers/generators;
affinity alone is not treated as activity. The historical boxguard.sh is not
installed here, so it is **not claimed to have run**. Unknown background work
cannot be excluded by the named-process screen; mainline still owns the idle
box/serial queue. No gate, competitor benchmark, NIC campaign or production
A/B was run by this lane.

## Verdict rules

No mechanism can be judged before the matching 14-cell null passes first, and
every contributing multi-key cell/variant needs n≥6 complete samples. The
script uses deterministic 2,000-resample percentile intervals for diagnostic
uncertainty; missing data or unresolved intervals stay UNRESOLVED.

| Mechanism | Frozen prediction and decision |
|---|---|
| M1 | For rl0 scattered MGET/MSET p8/p32 and the new p128 pair, retired/sends must be in [0.9,1.1], the explicit operational meaning of “~1.0”. wb0/wb1 must be a multi-key rate/cycles null within ±0.15%, and GET/SET must lose rate and cost cycles with wb0. Every check and the conjunction print **PASS/FAIL** arithmetic. Resolved contradiction refutes; uncertainty remains unresolved. Read-local MGET controls are not mistaken for scattered traffic. |
| M2 | Report n≥6 depth/control distributions of demand fills, any-minus-demand fills and walk requests, plus xshard_execute share. Those aggregate observations cannot isolate cold-fragment cost from allocation, gather or floor traffic, so the causal mechanism remains UNRESOLVED with that reason. No absent per-fragment counter is synthesized. |
| M3 | On cycles/key, MGET 7→8 and MSET 3→4 must each have a resolved positive step beyond the propagated null band; each absolute step must be larger at p32. MGET 9→16 must not add another positive per-key step beyond the band. All 28 key-count/cell variants require n≥6. Resolved contrary behavior refutes; overlapping intervals stay unresolved. |
| M4 | Report demand-fill, store-stall, dTLB and walk-request distributions for MGET p8/p32 versus GET p32. Aggregate counters do not locate a stall at the table probe or isolate the causal cost of omitted prefetch; the tool explicitly leaves that attribution UNRESOLVED. A localized profile or code-lane intervention is needed for a stronger decision. |
| M5 | Sum exclusive refresh_snapshot_floor and active_snapshot_floor shares without caller double counting. Require n≥6 and ≥1,000 samples per symbol pass. A p32 upper interval below 0.3% refutes the predicted importance; resolved growth p8→p32→p128 confirms the stated share signature. Missing p32 attribution remains unresolved. |

Current report: **M1 UNRESOLVED; M2 UNRESOLVED; M3 UNRESOLVED; M4 UNRESOLVED;
M5 UNRESOLVED**. No campaign observations or null have been collected. The
synthetic positive/negative self-test fixtures are never measurement evidence.

## Proofs retained in this worktree

Final `--self-test`: PASS. All nine `--dry-run` modes: PASS, with memtier help
grammar checked and generated memtier argv printed. Both pinned stat groups
and the perf-record FIFO enable/disable/ACK path were also exercised with
owned short CPU fixtures on 112–127; no server/load generator was involved.
The record fixture collected 191 samples and reaped both children.

Byte-identity proof checks **1656 complete argv vectors** covering all
181 frozen headline rows and all 19 probe rows, including the tail recipes,
using the unchanged Runner.memtier and the original workload module loaded
from git. Before/after vectors are UTF-8, NUL-separated and NUL-terminated.

```
headline SHA256:       d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350
frozen workloads SHA:  0060d75451b97c4274600eefcd8c950e0683359b31df910233d5e60765e15ce9
both argv streams SHA: e90f50fe6363bf7d44a3b7eb168641736ad3e6c6f9f0e6fe9c3d63b3b4c5facc
final probe source SHA: 6373cdb95f3dd3c08a65ca4c0ab0f64fdfc940cc2125e86945aa013b07891a82
```

All seven override values were round-tripped for both MGET and MSET, checking
key/value arity and restoration of the unset default. Zero/negative values fail.
An additional fresh-interpreter environment round-trip (unset → every requested
value → unset) also passes; its receipt is `environment-roundtrip.json`.
The grep audit found 33 matching encodings in tests/ and tools/; unchanged
“eight keys” assertions/comments describe the unchanged default or independent
correctness tests. Frozen headline bytes did not change.

Proof files:

* `build/mkprobe-proof/final-proof.json`, `self-test-final.log`, `default-argv.json`.
* `build/mkprobe-proof/dry-runs.json` and `dry-final-<mode>.log`.
* `build/mkprobe-proof/perf-groups.json` and `perf-record-control/proof.json`.
* `build/mkprobe-proof/text-encodings.log`.
* `build/mkprobe-smoke-01/receipt.json`, `rows.jsonl`, `report.json`, all attempt
  `row.json` / `quiet.jsonl` files, and `build/mkprobe-proof/smoke-01.log`.

The committed portable archive `docs/mkprobe/proofs.tar.gz` preserves the final
serverless logs, printed argv, raw stat-group fixture counts, record-control
summary, all six refusal records and a replayed report. Its internal manifest
binds all 38 members by SHA256; verification passed. Large perf.data files and
the server executable stay in build/.

Archive SHA256: `a260c22ee0ea7bc0fecf6bba509ddc36dffedff528991738227da0583f6b3189`.

The attempted smoke used a private copy of the existing
`/home/user/Projects/cx-final/build/tomokv`; no build was launched:
`SHA256 9407c432a8bfb8f6b78a641968a87bdd3e6a8ac602dadb39a3cc154a50a5d0eb`.
These refusal receipts identify instrument source commit `07de21711`; the final
serverless proofs identify `11925a9f8`. Since no smoke child started,
there is **no live row-shape or performance validation claim** for either version.

```sh
taskset -c 112-127 python3 tools/mkprobe_probe.py --mode smoke --binary build/mkprobe-server --cores 112-119,120-127 --output build/mkprobe-smoke-01
```

| Cell | Attempt UTC | Selected CPU seconds before refusal | Budget | Server/load children |
|---|---|---:|---:|---:|
| m02 | 2026-10-07 22:10:09 UTC | 1.92 | 0.48 | 0 |
| m02 | 2026-10-07 22:15:22 UTC | 8.33 | 0.48 | 0 |
| m02 | 2026-10-07 22:20:23 UTC | 1.01 | 0.48 | 0 |
| p8g | 2026-10-07 22:20:24 UTC | 1.31 | 0.48 | 0 |
| p8g | 2026-10-07 22:25:25 UTC | 0.66 | 0.48 | 0 |
| p8g | 2026-10-07 22:30:33 UTC | 1.12 | 0.48 | 0 |

Each cell had three attempts over approximately ten minutes. Both final rows
are FAILED with the required primary metric columns set to “not available”.
The quiet allowance was not widened, a failed sample was not skipped as a pass,
and no compiler attribution is inferred from CPU activity alone. Mainline can
rerun the smoke with a **fresh output directory** after the box becomes quiet.

## Exact mainline queue, in order

Resolve the fixed-2s sampler contract before queueing this campaign. The commands
below use the staged binary above and bind its SHA for every arm; the maintainer
can instead stage a reviewed current-mainline binary at that path before the
first null. No binary may change after the null. Every output below is fresh;
the shared snapshot cache is also inside this worktree. Execute serially on the
idle box, server CPUs 0–31 and generator CPUs 32–111. No PAD arm is involved.

1.

```sh
python3 /home/user/Projects/cx-mkprobe/tools/mkprobe_probe.py --binary /home/user/Projects/cx-mkprobe/build/mkprobe-server --cores 0-31,32-111 --samples 6 --snapshot-cache /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/snapshots --mode null --output /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/null
```

2.

```sh
python3 /home/user/Projects/cx-mkprobe/tools/mkprobe_probe.py --binary /home/user/Projects/cx-mkprobe/build/mkprobe-server --cores 0-31,32-111 --samples 6 --snapshot-cache /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/snapshots --mode probes --output /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/probes --null /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/null
```

3.

```sh
python3 /home/user/Projects/cx-mkprobe/tools/mkprobe_probe.py --binary /home/user/Projects/cx-mkprobe/build/mkprobe-server --cores 0-31,32-111 --samples 6 --snapshot-cache /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/snapshots --mode counters --output /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/counters-atomic0 --atomic 0 --cells m02,m03,mk128g --null /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/null
```

4.

```sh
python3 /home/user/Projects/cx-mkprobe/tools/mkprobe_probe.py --binary /home/user/Projects/cx-mkprobe/build/mkprobe-server --cores 0-31,32-111 --samples 6 --snapshot-cache /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/snapshots --mode wb-pair --output /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/wb-pair --null /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/null
```

5.

```sh
python3 /home/user/Projects/cx-mkprobe/tools/mkprobe_probe.py --binary /home/user/Projects/cx-mkprobe/build/mkprobe-server --cores 0-31,32-111 --samples 6 --snapshot-cache /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/snapshots --mode keys --output /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/keys --null /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/null
```

6.

```sh
python3 /home/user/Projects/cx-mkprobe/tools/mkprobe_probe.py --mode report --inputs /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/null /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/probes /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/counters-atomic0 /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/wb-pair /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/keys --output /home/user/Projects/cx-mkprobe/build/mkprobe-mainline/report
```

| Queue item | Result rows | Measured boots | Fixed warm/window/tail + preflight floor | Expected allowance |
|---|---:|---:|---:|---|
| 14-cell identical null | 168 | 168 | 134.4 min | 2.4–2.7 h |
| Three-pass probes, 19 cells | 114 | 342 | 197.6 min | 3.8–4.4 h, including record postprocessing |
| Atomic-0 cut witness, 3 MGET depths | 18 | 18 | 14.4 min | 16–20 min |
| wb-policy pair, 8 shapes | 96 | 96 | 76.8 min | 1.4–1.6 h |
| Seven-point key sweep, 4 shapes | 168 | 168 | 134.4 min | 2.4–2.7 h |
| Report | — | 0 | — | under a minute, excluding any manual perf inspection |

Total: **564 result rows, 792 measured boots**, a 9.29-hour fixed-time floor and
roughly **10–12 hours** allowing snapshot restore, startup, shutdown and profile
processing. Initial snapshot population is additional (normally one image per
shard geometry). These are planning estimates, not measurements of this campaign.
The 20-second preflight is per result sample; each measured boot separately gets
3 seconds warmup, 20 seconds central window and 5 seconds tail. The combined
probes mode avoids repeating the core pass when collecting the other two groups.

Reproduction of the final serverless checks:

```sh
taskset -c 112-127 python3 tools/mkprobe_probe.py --self-test
for mode in null probes counters coherence wb-pair keys symbols smoke; do
  taskset -c 112-127 python3 tools/mkprobe_probe.py --mode "$mode" --dry-run --cores 0-31,32-111 --output "build/mkprobe-review-$mode"
done
taskset -c 112-127 python3 tools/mkprobe_probe.py --mode report --dry-run --inputs build/mkprobe-smoke-01 --output build/mkprobe-review-report
```

No push was performed. Mainline owns the quiet-box rerun, campaign judgment,
any production telemetry follow-up, the gate and merge.
