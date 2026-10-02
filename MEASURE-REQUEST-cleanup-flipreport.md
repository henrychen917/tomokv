**cleanup-flipreport — unused report residue removed; landing is PENDING MAINLINE.**

The cost-gate horizon was already wired and working. This is **unused report
residue, not a broken cost-gate horizon**. PRE and POST are **not byte-identical**:
removing the redundant report assignment changes instructions inside `report()`.
A separate **kind-A PAD behavior twin** retains exact PRE bytes and has POST's
verified section layout, function addresses and sizes. Mainline must supply the
controlled performance null before landing. No performance or footprint gain is
claimed.

No server, live battery, benchmark, load generator, gate, performance measurement
or push was run. Builds and serverless executions used **cores 112–127**; make
builds used **-j16**. All changes and artifacts are inside this lane's worktree.

**Reference and diagnosis.** The clean lane started at staging commit
`5b3d9c4292bf8b332d493beb485266ecc5a289aa`. The required first merge fast-forwarded
to launch `origin/cpp`, **`2a9e484035960b0ba5925824cc581148c359c0f8`**. Under the
latest launch instruction, that launch commit is PRE. Staging 5b3d9c429 is retained
in `freeze/revisions.txt` and the requested staging-relative diff below; it is
not mislabeled as the built PRE. PRE was built and captured before candidate
compilation. `freeze/PRE-source.tar`, build commands, dependency hashes, history
and the original producer/consumer search are retained under
**`build/cleanup-flipreport/`**; artifact paths below are relative to that directory.

Rechecked anchors in the launch tree:

| Item | PRE file:line | Evidence |
|---|---|---|
| Old member/default | `src/core/flipctl.h:263` | `double stationary_s = 0`; no reader |
| Old producer | `src/core/flipctl.cc:1390` | Always assigns zero in `report()` |
| Report wrapper | `src/core/server.h:519` | Returns `flipctl_.report()` |
| INFO consumer | `src/cmd/t_server.cc:2123`–`:2166` | Prints other report members; never this member |
| Live clock | `src/core/flipctl.h:501` | `stationary_since_ms_` remains controller state |
| Idle reset / nonidle start | `src/core/flipctl.cc:496`, `:514` | Existing clock rules |
| Trigger reset / preservation | `src/core/flipctl.cc:626`–`:630` | Change triggers reset; forced re-examination preserves the clock |
| Live calculation and call | `src/core/flipctl.cc:919`–`:925` | Local seconds from synthetic/current time passed directly to `flip_cost_gate` |
| Horizon consumer | `src/core/flip_policy.h:478`–`:493` | Stores horizon and prices benefit against cost |
| DEBUG output | `src/core/flipctl.cc:1422`, `:1458` | Prints `model_cost_.horizon_s`, independently of `FlipctlReport` |

`freeze/producer-consumer.txt` searches source, tests and tools before editing.
There was no report-member consumer in those trees. The local arithmetic argument
and the DEBUG horizon are separate, live paths. `freeze/history-601d65d4a.txt`
and `freeze/history-stationary.txt` retain the actual history: commit
`601d65d4a` introduced the live local calculation, clock rules, and constant-zero
report assignment together. The old “cost gate input never wired” diagnosis is
therefore incorrect. No missing live contract was deleted or replaced by a new
INFO signal.

**Change and scope.** Production changes are exactly the member replacement at
POST `src/core/flipctl.h:263` and deletion of the assignment before POST
`src/core/flipctl.cc:1390`. The replacement is explicitly inert, initialized
eight-byte layout storage. `FlipctlReport` remains **360 bytes**, with
`refine_decision` at **320** and `refine_steps` at **352**. Every surviving report
offset matches PRE. `FlipController` remains 1752 bytes. The eight required locks
remain Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144 and Config 624; production builds retain their offset assertions
in both namespaces. `layout/PRE.txt` and `layout/POST.txt` retain the complete
layout comparison.

`source-proof.json` compares every frozen production source file against an
explicit two-edit expectation. The clock, its reset/start rules, the local
cost-gate calculation, `maneuver_start_`, `ThreadMeasure::busy_ns`, the gain_mean
parameter and INFO aliases are untouched. There are no new knobs or hot-path
edits. Tests use one include in the existing core battery and one compile-time
assertion in the existing model unit; Makefile changes only add test prerequisites.

An inherited owner-law conflict remains outside this cleanup: the merged
readreply report already flags the per-operation topology sequence handshake
and validation. Current anchors include `src/store/flatstore.h:867`, `:919`,
`:930`, `:3253`, `:3268`. Those guards protect topology/torn-read safety and
conflict with the literal no-sequence-protocol law; this lane neither removes
them nor redesigns them. No additional ownership, migration, QSBR, RYOW,
multi-key atomicity or reply-order change was made.

Implementation commits before this report: `7281b3dc4` (cleanup), `b008696f8`
(existing-battery proofs), `54ef598b8` (offline controls), `376ffa8f8` (accurate
padding comment). The final comment-only rebuild matches the captured POST
**whole-file byte for byte for all 85 artifacts**: `final-build-identity.json`.

**Build and machine-code evidence.** The Makefile links **42 normal and 42 db0
production objects**. Its broad header prerequisite rebuilds all 84. Compiler
dependency resolution identifies **38 actual includers** of the report header,
including both namespaces' `main`, `xshard`, `acl`, `t_server`, `scripting`,
`functions`, `snapshot`, `aof`, `climon`, `tracking`, `server_tail`, `slowlog`,
`lbsignals`, `flipctl`, `genthread`, `rl2s`, `lbstall`, `multidb` and `reorder`.
`freeze/object-inventory.json` retains every command and dependency, with include
path aliases resolved for this classification. All 84 objects were compared.

Compiler: **GCC 13.3.0**, default release flags
`-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, jemalloc enabled and
unchanged per-TU compiler parameters. PRE/POST use the same worktree, source
paths and `build/` output paths. The 84 compile commands plus link command match
exactly. `freeze/reproducibility.json` verifies **1019 hashed dependency/toolchain
paths**, including include-path aliases: only the two production files and
test-prerequisite-only Makefile differ. System headers, compiler and libraries
match. Logs: `PRE-build.log`, `POST-build.log`, `final-build.log`.

Each of `PRE/`, `POST/`, `PAD-A/` contains `artifacts/`, `manifest.json`,
`SHA256SUMS` and `dumps/`. Retained evidence includes raw `objdump -drw`,
`readelf -W -h -l -S -s -r`, `nm`, binary dumps of **every executable section**,
section metadata, full relocation targets/addends, and allocated symbol
addresses. PAD's dumps are inherited from the byte-identical PRE copy and
explicitly verified against its separately named artifacts.

The existing strict checker in `tools/ttlstate_proof.py` compares actual byte
strings, not normalized instructions or counts. It covers `.text`, every
executable `.text.*`, all SHF_EXECINSTR sections, allocated data, relocation
targets, linked addresses, program headers and entry point. DWARF and its
dependent build ID are reported separately, never used to excuse code changes.

| Arm | Binary | Full ELF SHA-256 |
|---|---|---|
| PRE | `PRE/artifacts/tomokv` | `6d2d82e315bed28a300dc9549c8a486afd798126201e7c2adadade3e9ebad927` |
| POST | `POST/artifacts/tomokv` | `1c4f87974f3a71461a89f5271bd6537b74704f270aa07211301868d36f901b70` |
| PAD **(A), behavior twin** | `PAD-A/artifacts/tomokv` | `6d2d82e315bed28a300dc9549c8a486afd798126201e7c2adadade3e9ebad927` |

All three files are **176985360 bytes**. Their linked `.text` is **7564433 bytes**;
all six linked executable sections total **7574265 bytes**; entry point is
**0x4dc10**. There are **10016 function symbol entries**, with identical addresses
and sizes, and **10618 allocated symbol entries**. All **3786 linked relocations**
match. `binaries.json` and `linked-identity.json` retain these inventories.

`identity.json` correctly reports **82/85 artifacts passing production byte/layout
checks**, auditing **8594 executable sections** across the objects and linked image.
Only normal/db0 `flipctl.o` and the linked binary differ in production sections;
other full ELF hashes may differ through DWARF. In each affected object, the 3939-byte
`FlipController::report()` loses an eleven-byte zero store; GCC fills the freed
space before the next aligned block with NOPs. Instructions/call relocations
inside the function move, and branches to/from them change. There are 163 changed
raw object function bytes per namespace. Linking resolves those changes into
168 bytes per report body and one byte in each 368-byte cold report fragment.
The changed linked production sections are `.text` and `.eh_frame`; linked
dynamic relocations and all other allocated contents match. Object relocation
offsets/addends change consistently with the moved report instructions.
`code-deltas.json` and `report-initial-diff.txt` expose this difference. No other
function's code changes; INFO's formatter objects match PRE.

**PAD mapping.** `tools/flipreport_proof.py pad` first checks every object's and
the linked image's allocated-section layout, symbol addresses, function sizes,
entry point and program headers against POST. Here PRE already has POST's exact
function address table and section layout, so **zero layout adjustment is needed**.
Only after those checks does it copy PRE into the separately named kind-A arm.
`PAD-A-layout.json` passes 85/85; `identity-PRE-PAD-A.json` proves complete-file
identity for all 85 artifacts. PRE behavior is established by exact bytes, not
an assumption about a prior R7 PAD or a footer of NOPs. Internal report instruction
positions still differ from POST, as recorded above.

`identity-PAD-A-POST.json` correctly has the same 82/85 result as PRE/POST.
This control is an identical-binary null partner for PRE and a PRE-behavior
partner at POST's function layout. It does **not** establish candidate parity.
Measure PRE/POST and PAD-A/POST; PRE/PAD-A supplies the identical-arm control.
No kind-B inverse control is required: linked `.text` size changes by **zero**.

**Serverless assertions and negative controls.** PRE and POST model units pass,
including all 12 rate rows and the existing horizon cases now at
`tests/flipctl_unit.cc:855`–`:859`, `:875`–`:878` (PRE :850–:854, :870–:873).
The extended existing `route` battery also passes: `POST-route.log`.

`tests/flipreport_checks.inc:29` creates a fresh 16-shard, eight-thread **6 IO +
2 EX** fixture and drives the complete production `tick()` with synthetic
commands, role work and time. Five bounded ticks establish the short state;
one further tick advances to the long state. A 20-tick observed flip supplies a
23-second blackout; equal role demand projects the 6:2→4:4 move. Actual results:

| Synthetic now_ms | Actual cost horizon | Benefit / cost (commands) | Decision |
|---:|---:|---:|---|
| 11000 | 10 seconds | 0 / 69000 | `sampling-cost`, does not pay |
| 46000 | 45 seconds | 132000 / 69000 | `move`, pays; flip issued |

These are arithmetic/state results, **not performance measurements**. The checks
run in normal namespace databases=1/4 and db0 databases=1. PRE, POST, PAD-A and an
independently compiled **assignment-only PRE control** produce identical traces.
That last control retains the old member and removes only its redundant
assignment, proving that this removal does not affect the horizon.

The same eight test executables invoke the actual INFO FLIPCTL and DEBUG FLIPCTL
handlers, including RESP2 framing. They cover disabled, anchored, short and long
split states and fused-unavailable output: **24 decision traces and 120 wire
replies** in total. All bytes match PRE; no wire field was added or removed.
Receipts: `controls/positives.json` and `controls/trace-*.stdout`. Normal trace
SHA-256 is `e131a3d9a0039f53b268a434329b90d01f3321b90178eb6f2a0e5ce8947873a9`;
db0 trace SHA-256 is `a186ff24c99399a8bc66a41625b72911d22a1765da8c55c49910862aeec26b12`.

| Assertion / exercised state | Throwaway control | Exact failure; observed result |
|---|---|---|
| Removed member, model unit compile | Restore old declaration in header overlay | `unused stationarity report member must remain absent`; compiler exit 1 |
| Short, cost window entered | Bypass role-demand sampling | `FAIL flipreport short: cost window entered`; exit 1 |
| Short, actual horizon 10 | Force **local** calculation to zero | `FAIL flipreport short: actual horizon is 10 seconds`; exit 1 |
| Short, cost blocks move | Bypass cost refusal at now=11000 | `FAIL flipreport short: cost blocks move`; exit 1 |
| Long, horizon grows to 45 | Freeze local horizon at 10 | `FAIL flipreport long: actual horizon grows to 45 seconds`; exit 1 |
| Long, cost permits move | Force cost verdict false at now=46000 | `FAIL flipreport long: cost permits move`; exit 1 |
| Actual wire handler entered | Omit handler call | `FAIL flipreport short: wire entered`; exit 1 |
| Exact wire comparison | Remove `flipctl_refine_steps` from a copied actual reply | `controller trace/wire bytes differ`; rejected |
| Report size and subsequent offsets | Remove inert storage in header overlay | Size 352 instead of 360, offsets 312/344 instead of 320/352; rejected |
| Linked executable bytes | XOR one `.text` byte in copied ELF | `executable .text: bytes differ`; rejected |
| Executable `.text.*` bytes | XOR one subsection byte in copied object | Exact subsection byte mismatch; rejected |
| Relocation targets/addends | Change executable-section RELA addend | `allocated relocation targets differ`; rejected |
| Linked function addresses | Move a function symbol address by one | `allocated symbol addresses/identities differ`; rejected |
| Entry point | Move ELF entry by one | `ELF kind/machine/entry or program headers differ`; rejected |

Controls, commands and generated sources/binaries are retained in `controls/`,
`layout/` and `elf-controls/`. All deliberately corrupted ELF artifacts are
nonexecutable `*.NEVER-RUN` files and were **never executed**. Missing arming fails
after the deterministic bounded warm-up; it cannot skip or widen a tolerance.
All new mechanism controls are serverless; no new live-control binary is needed.

**Gate rows and pending live work.** No gate script was edited or added. Existing
emission lines are model unit **tests/gate.sh:1209**, extended core route **:1254**,
live controller **:869**, FLIP state **:1930**, verified load **:1933**, TTL **:1936**,
saturated FLIP **:1972**, shutdown **:1984**. All are above the quick block at
**:2871**, exit **:2875**. Delta: **446 + 0 = 446 quick; 463 + 0 = 463 full**.
Neither EXPECT constant was edited by this lane. Changes to gate constants seen
in the staging-relative diff came from the required mainline merge. Gate scripts
retain their grep convention and existing script inventory.

Both live thread modes, databases=1/>1, read-local 0/1, the flipctl.py campaign,
FLIP state/load/TTL/shutdown batteries and instrumented gate execution are
**PENDING MAINLINE**, not PASS. The scheduled source gate command is:

```bash
cd /home/user/Projects/cx-cleanup-flipreport
tests/gate.sh iteration --server-cores 0-7 --server-smt '' \
  --load-cores 8-111 --load-smt '' --ports 8700-8799 \
  --reference-binary "$PWD/build/cleanup-flipreport/PRE/artifacts/tomokv"
```

Adding `--candidate-binary "$PWD/build/cleanup-flipreport/POST/artifacts/tomokv"`
tests the exact archived candidate but the gate withholds its source receipt for
an external candidate. Preserve the existing live controller launch at 6:2,
16 shards, `--atomic 0 --flip-auto 1 --enable-debug-command yes`, followed by
`python3 tests/flipctl.py --host 127.0.0.1 --port "$PORT" --stable-seconds 30`.
Its bounded stationary-hold re-rolls and failure-on-unentered-window stay intact.

**Frozen mainline performance request.** The base inventory remains **h01–h64**:
512 connections, GET/SET × p1/p32 × both modes × every read-local/overlap/reorder
combination. Exact launch bytes, 64-byte payload and load plans are frozen in
`freeze/headline_cells.txt`, `freeze/gate_measurements.json` and
`freeze/h01-h64-plans.json`. Their first two hashes are respectively
`d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350` and
`883634597e70a073c6f7c011524924723a90f77dbed328a1334b4fad26e96afb`.
No existing cell or load plan was edited.

The initial **14 generic cleanup cells**, following atomiccollapse's explicit
subset, are **h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64**.
Their unchanged lines are `freeze/generic14.cells.txt`, SHA-256
`e762a136c88081ac5e3ef3b3fac4d77ab698e105afe76ca42820aabd156589fb`.
This subset does not replace the h01–h64 guard.

`freeze/feature-cells.json` names **80 additional requested regimes** without
altering an h cell: `fr-<regime>-<hNN>-db<1|4>`. Split shapes are
**h17,h18,h25,h26,h49,h50,h57,h58**; fused neutral counterparts are
**h01,h02,h09,h10,h33,h34,h41,h42**. They retain p1/p32, GET/SET, read-local 0/1,
overlap=0, reorder=0, atomic=1 and 512 connections. Use databases **1 and 4**,
**16 shards**, eight physical server cores and **6:2 for split**. Fused has eight
fused workers; its controller is unavailable, so only its neutral regime applies.

| Regime | Required witness | PRE metrics | POST metrics | PAD-A metrics |
|---|---|---|---|---|
| Neutral `off` (32 cells) | flip-auto=0 | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Exercised `stable` (16 cells); no gain required | flip-auto=1; anchored stable window entered | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Possible deficit `shift-short` (16 cells) | Shift/recovery with short stationarity; requested residence 10 s | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Possible deficit `shift-long` (16 cells) | Shift/recovery with long stationarity; requested residence 45 s | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |

Each metrics cell means cycles/op, instructions/op, IPC, rate and relevant p99/
p99.9 tails. There is no claimed benefit regime; the exercised stable path is
reported separately from disabled and possible-deficit regimes. Mainline must
freeze the live shift/recovery schedule, actual stationarity witnesses, offered
loads and productive-role worker floors before POST. The synthetic 10/45-second
proof above is not substituted for a live residence measurement. Any unentered
live window gets bounded fresh-state re-arming and then FAIL, never SKIP.

Use **PRE/POST, PRE/PAD-A, PAD-A/POST**. Establish the productive-role plateau
with enough independent workers at **both p1 and p32**; a single connection is
not a saturation witness. At matched offered loads, retain each cell/block and
require stable-reference parity and these independently fixed bounds:

```text
abs(100 * (B_cycles / A_cycles - 1)) <= epsilon_cyc[cell]
100 * (1 - B_rate / A_rate)         <= epsilon_rate[cell]
100 * (B_tail / A_tail - 1)         <= epsilon_tail[cell]  # each relevant tail
cycles/op = instructions/op / IPC
```

Do not average away a losing cell or widen a bound after observing POST. A gain
is not required. PRE/PAD-A is byte-identical; that fact does not discharge the
PRE/POST or PAD-A/POST null.

**Instrument status that mainline must resolve before candidate measurements.**
The nullrefresh5 frozen fingerprint is
**`cc6c06bde1ce7939b7f001489fde7287476c4086929f51badf774811d087dd36`**;
manifest SHA-256 is
`ce0967f2e8b932367c3da15f276eec21b561cb8d7ddc11ca31b954671378f683`.
All **23** dependency files were recovered from
`64fec17603a5a3f9c69c95dfd5efc8e4204caf6d`, verified against that manifest, and
copied into `freeze/nullrefresh/instrument/`. The current nullrefresh worktree
differs in five files; both checks are retained in `freeze/nullrefresh/`.
The matching frozen campaign stable binary SHA is
`ef52de792f72ab8dae240fcd8194e1f14aa94b3828dc7e512eea7256b50c1133`.

The launch gate's separate stable reference is **90ba908d3**, SHA
`76854108e8e5080ae1a8e42e362cb8e071d5796ec29a66ca869397a999ced068`;
the declared file was read and its hash verified. This cleanup's A/B reference
is the launch PRE **2a9e48403**, SHA `6d2d82e315bed28a300dc9549c8a486afd798126201e7c2adadade3e9ebad927`.
These three identities are not interchangeable.

No qualified per-cell null/independent holdout certificate was supplied with the
inspected frozen metadata; its `full-null.json` path was absent. Per-cell cycles,
rate and tail resolution remains **PENDING MAINLINE**, explicitly unset in the
request JSON. The frozen campaign geometry is 32 cores/16:16. Its launcher
(`freeze/nullrefresh/instrument/tests/abbagate.py:1440`) selects 64 shards for
eight-core fused runs and fixes flip-auto=0 for split. `abba_saturation.py:22`
exempts p1 from the plateau requirement. `abba_profile.py:1` explicitly labels
its cycles/op denominators approximate and not null evidence. Merely selecting
eight CPUs cannot satisfy this request's geometry, flip regimes and aligned
cycles/op evidence. Mainline must supply the validated instrument/configuration
and freeze its digest, stable reference SHA, per-cell resolution, load plan and
fixed epsilon values before measuring POST. No instrument/controller repair or
unverified tolerance is bundled in this cleanup.

**Serverless replay and receipts.** From the lane worktree:

```bash
taskset -c 112-127 make -j16 all build/flipctl-unit build/signalacct-core-unit
taskset -c 112-127 build/flipctl-unit
taskset -c 112-127 build/signalacct-core-unit route
taskset -c 112-127 python3 tools/flipreport_proof.py source
taskset -c 112-127 python3 tools/flipreport_proof.py controls
taskset -c 112-127 python3 tools/flipreport_proof.py wire-control
taskset -c 112-127 python3 tools/flipreport_proof.py elf-controls
# Expected exit 1: PRE/POST genuinely differ in production code.
taskset -c 112-127 python3 tools/ttlstate_proof.py compare \
  build/cleanup-flipreport/PRE build/cleanup-flipreport/POST \
  --output build/cleanup-flipreport/identity-replay.json
```

Fresh arm capture uses `tools/ttlstate_proof.py capture` with
`freeze/object-inventory.json`; PAD creation uses `tools/flipreport_proof.py pad`
and refuses to overwrite an existing arm. The supplied arms are already captured.
`sha256sum build/tomokv` after the final build is:

```text
1c4f87974f3a71461a89f5271bd6537b74704f270aa07211301868d36f901b70  build/tomokv
```

Requested `git diff 5b3d9c429 --stat`, including the first mainline merge and this
report (the actual lane-only baseline is 2a9e48403):

```text
 MEASURE-REQUEST-cleanup-flipreport.md | 378 ++++++++++++++++++++++++++++++++++
 MEASURE-REQUEST-cleanup-readreply.md  | 371 +++++++++++++++++++++++++++++++++
 Makefile                              |   4 +-
 src/core/ex_loop.h                    |  63 +++---
 src/core/flipctl.cc                   |   1 -
 src/core/flipctl.h                    |   2 +-
 tests/core_concurrency_unit.cc        |   5 +-
 tests/flipctl_unit.cc                 |   5 +
 tests/flipreport_checks.inc           |  87 ++++++++
 tests/gate.sh                         |   2 +-
 tests/gate_measurements.json          |   8 +-
 tests/rltopo_unit.cc                  | 148 ++++++++++++-
 tools/flipreport_proof.py             | 331 +++++++++++++++++++++++++++++
 tools/readreply_proof.py              | 369 +++++++++++++++++++++++++++++++++
 14 files changed, 1723 insertions(+), 51 deletions(-)
```

Lane-only `git diff 2a9e484035960b0ba5925824cc581148c359c0f8 --stat`:

```text
 MEASURE-REQUEST-cleanup-flipreport.md | 378 ++++++++++++++++++++++++++++++++++
 Makefile                              |   4 +-
 src/core/flipctl.cc                   |   1 -
 src/core/flipctl.h                    |   2 +-
 tests/core_concurrency_unit.cc        |   5 +-
 tests/flipctl_unit.cc                 |   5 +
 tests/flipreport_checks.inc           |  87 ++++++++
 tools/flipreport_proof.py             | 331 +++++++++++++++++++++++++++++
 8 files changed, 808 insertions(+), 5 deletions(-)
```
