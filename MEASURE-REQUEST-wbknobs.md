TomoKV wbknobs — owner handoff, 2026-10-09

The measured S=16 / D=3 completion bounds are now boot-only knobs. The production
default remains the landed bounded hybrid, and `--wb-small-pipe 0` selects the
plain half rule in the same executable. The half fraction remains compiled.
Performance acceptance is **PENDING mainline measurement**. This lane built the
artifacts and ran serverless witnesses/instruction traces; it did not start a
server, load generator, benchmark, differ, or gate.

**Knob contract.** Configuration-file names and CLI spellings are identical
apart from the CLI `--` prefix. Both use the existing Redis-style canonical
integer parser: `0` or a nonzero decimal digit followed by decimal digits, in
range. Signs, leading zeroes, whitespace inside the value, fractions, suffixes,
trailing junk, overflow and missing arguments fail boot parsing.

| Config name | CLI | Default | Range | Meaning of 0 |
| --- | --- | ---: | --- | --- |
| `wb-small-pipe` | `--wb-small-pipe N` | 16 | 0..64 (`kRobWindow`) | Disable completion; use the plain half rule |
| `wb-complete-visits` | `--wb-complete-visits N` | 3 | 0..255 | Unbounded completion for eligible small pipes; do not increment the counter |

For policy 1, pipes of at most S commands complete for at most D deferrals, then
use the half rule. The existing <=1, staged/reply-byte and scatter exits still
apply. With S=0, D has no effect. Policy 0 still serves every ready head.
`CONFIG GET`, `CONFIG REWRITE` and `INFO WRITEBACK` expose the actual boot values.
The INFO fields are `wb_policy`, `wb_small_pipe`, `wb_complete_visits`, in that
order. Both `CONFIG SET` paths reject all values with exactly the wb-policy
reply: `-ERR parameter is immutable at runtime\r\n`.

`wb_rule.h` now calls S/D measured **defaults** and retains the existing ledger
addendum 12 / PLAN-SERIAL citations and D-curve numbers. The merged source cites
addendum 12 for both constants; no new provenance was invented. `tomokv.conf`
retains those provenance lines. `docs/CONFIGURATION.md` was regenerated with
`python3 tests/docs_drift.py --write`; the generator now derives the new defaults
from source and rejects documentation drift.

**Artifacts and source.** This branch merged origin/cpp at the start and fetched
and merged it again before the final proof. Both resolved to
`dab7409642bf0a6d125fb5f479e6d190c7636083`, the PRE merge base. PRE was compiled
from its archived Makefile, source and third_party tree under this worktree.
Production POST source is commit `c64b98974`; subsequent commits add fixture
setup, measurement tooling and receipts, without changing production bytes.
Compiler: GCC 13.3.0, ordinary repository O2/march-native/jemalloc flags, both
database namespaces. No compile-budget overrides were added.

| Arm | Path | SHA-256 |
| --- | --- | --- |
| PRE | `build/wbknobs/PRE/tomokv` | `6bc964937b2267062d5863fc70e6471314cd8579a465bdf5be2314d37a7a454d` |
| POST | `build/wbknobs/POST/tomokv` = `build/tomokv` | `d5c64375fb4e7e445cdfb96d3fd2306c489921391617b9ecf4751128b3155d89` |
| Newest headline at handoff | `/home/user/Projects/bench-bins/tomokv-headline-db86e5b4a` | `9325d80919fb4826751de0969b851ed567563cc7686e5fc13929aa69a9d7b248` |

The headline is commit `db86e5b4a051929c68108d33b1dc358428c59bca`, selected by
`tests/gate_measurements.json`; it is intentionally distinct from the PRE merge
base. Recheck which headline is newest when mainline schedules the run and
record its path/hash if that selection advances. The lane's PRE remains the
merge-base code-cost reference.

The binary manifest is [binaries.json](docs/wbknobs/binaries.json). PRE/POST
`.text` is 7,845,285 / 7,844,245 bytes (POST -1,040). Debug ELF file size is not
used as a performance explanation. Compressed build logs are in `docs/wbknobs/`.

**Storage and caching.** `Config` uses eight reserved tail bytes at offsets
572/576; its reserved array decreases from 52 to 44. `IoLoop` stores policy/S/D
in three existing padding bytes at offset 1349, copied only by
`cache_writeback_config()` from `IoLoop::init()`. Every production gather/serve
call passes this cache. There is no per-visit Server/Config lookup, recomputation,
detector/probe, allocation, or new per-operation state. The one-byte counter at
Client offset 72 saturates at bounded D; the D=0 path leaves it untouched and
cannot wrap. FIFO removal still resets it.

[layout.json](docs/wbknobs/layout.json) proves, in both namespaces, every prior
Client/IoLoop/Config member offset and size (except the reserved tail array),
and these size locks: Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. IoLoop remains 7144;
Client ROB stays at 128. No existing field or object footprint moves. No PAD arm
is requested: reserved bytes supply the storage, and the required S=0/default
merit pair uses identical ELF bytes. This does not claim that the PRE/POST text
size difference is harmless; the default null must establish that.

**Instruction-per-visit receipt.** [code-costs.json](docs/wbknobs/code-costs.json)
contains 656 raw traces (164 cases x PRE/POST x two namespaces) using the existing
`wb_rule_2s_trace.cc` ptrace instrument and reply fixtures. These are instruction
counts, not elapsed-time or PMU measurements. They count one wrapper/defer visit,
including its cached input load(s), excluding fixture setup. PRE's wrapper loads
policy from a fixture cache; it does not model the old outer Server pointer
chase. Values below are identical in both namespaces. All traces execute zero
library instructions.

| Visit / input | PRE instructions | POST instructions | Delta |
| --- | ---: | ---: | ---: |
| Policy 0 | 8 | 7 | -1 |
| p1 early exit | 13 | 12 | -1 |
| p8, no Done replies, first completion visit | 75 | 77 | +2 |
| p8, one Done GET, first completion visit | 101 | 103 | +2 |
| p8, one Done GET, D exhausted | 104 | 109 | +5 |
| p64, one Done GET, half rule | 102 | 104 | +2 |
| p8, one / two Done OK replies | 105 / 135 | 107 / 137 | +2 / +2 |
| p8, one / two Done integer 12345 replies | 142 / 209 | 144 / 211 | +2 / +2 |
| p8, one / two integer replies, D exhausted | 145 / 212 | 150 / 217 | +5 / +5 |
| 512 bytes already staged, before reply walk | 35 | 47 | **+12** |

Additional reply growth stays exactly PRE: OK +30, 71-byte GET +26, integer +67,
at each initial counter value 0..3. The volatile completion predicate remains
off the integer encoder's live register set. Ordinary deferral visits add 2..5
instructions, in the requested small per-visit class. The staged-byte fast exit
is an explicit exception: the cached pointer changes GCC's register-save path,
adding six pushes and six pops there. It is not hidden in an average and is not
claimed below the instrument without the requested null. Instructions alone do
not prove the hot-path latency law.

[defer-body-identity.json](docs/wbknobs/defer-body-identity.json) verifies all
16 emitted core defer instances (PRE/POST, both namespaces, main/genthread/rl2s/
reorder) equal the corresponding traced fixture body, using canonical bytes and
resolved relocation targets. Reproduce offline with:

```sh
taskset -c 0-111 python3 tools/wbknobs_receipts.py costs
taskset -c 0-111 python3 tools/wbknobs_receipts.py body
taskset -c 0-111 python3 tools/wbknobs_receipts.py layout
```

**Body audit.** Direct production body changes and reasons are:

| Body | Reason |
| --- | --- |
| Config default initialization | Add S/D in the reserved tail |
| `parse_config_args` | Parse the two canonical numeric boot knobs and display their help |
| `validate_config` | Reject out-of-range programmatic Config values |
| IoLoop default initialization / `init` / `cache_writeback_config` | Initialize and latch three bytes in existing padding at boot |
| `wb_rule::defer(Connection&, const Settings&)` | Load cached bounds; bounded count or unbounded completion |
| `wb_rule::defer(Connection&, int, unsigned, unsigned)` | Preserve the direct fixture/default API through the same implementation |
| `Phase2::gather` / `Phase2::serve` | Pass the IO-local cache |
| `wb_rule::info` / `Server::wb_policy_info` | Format and forward both boot values |
| command-layer `init_config` | Register immutable GET/REWRITE bindings |

[changed-bodies.json](docs/wbknobs/changed-bodies.json) lists **every** changed
emitted body, its object, mangled/demangled name, PRE/POST sizes and reason.
[body-summary.json](docs/wbknobs/body-summary.json) and the complete compressed
[inventory](docs/wbknobs/bodies.json.gz) cover 17,089 bodies: 16,847 equal, 242
changed, across ten objects (main/genthread/rl2s/reorder/t_server, both namespaces).
Of 1,213 command-handler bodies, 1,208 are equal; all five changed entries are
CONFIG/INFO, including cold clones. GET/SET/MGET/MSET handlers are unchanged.

There are 68 compiler-consequence entries whose own source is unchanged,
including some dispatch, encoder and worker helpers in affected translation
units. They are individually included in the changed-body list, not asserted
neutral. The existing `ccfix_audit.py` inventory was used without modifying its
normalization; its strict ordinary-hot-body identity assertion exits 1 for this
intentional change (1,354/1,496 hot entries equal). This is **not** an identity
PASS. Its output is the audit inventory; the 14-cell default comparison is the
required performance verdict.

**Witnesses.** All original four policy mutants, 19 clause mutants and three
physical-schedule bypass mutants still fail with their required assertions.
The existing S/D boundary and FIFO-reset mutants also remain. The anchored
call-site proof now claims only the exact cache declaration, one init call and
the exact boot copy; every other cache/knob reference is rejected. Detector,
clock, allocation and probe bans remain, and `cfg(` is now explicitly banned
inside the rule. New source controls reject a hardcoded cache value, re-caching
per visit and a direct Config read in the rule. New runtime mutants reject an
ignored S, ignored D=0 and unbounded-counter increments.

The independent decision oracle sweeps S={0,1,2,8,16,17,64},
D={0,1,3,255}, ROB starts {0,61}, every size 0..64 and every Done prefix, and
initial counts {0,1,2,3,254,255}. Real gather/serve lifetime witnesses exercise
D=255 saturation and 1024 unbounded visits. The real physical schedules cover
fused FIFO/R7 and split coarse/natural/shallow, read-local off/on, both namespaces,
using S/D pairs (16,3), (0,3), (8,1), (64,0).

| Serverless check | Result |
| --- | --- |
| wbland clauses | 83/83 strict outcomes, including 49 required rejections |
| wbland paths | 31/31, including 7 required rejections |
| wb-rule policy / phase / stages / split-phase / split-overlap | 37/37, 32/32, 12/12, 35/35, 64/64 |
| Existing policy instruction traces | 352 calls pass; both always-defer controls rejected |
| Ordinary netcmd config matrix | PASS |
| New wb-small-pipe / wb-complete-visits cases | PASS in multi and db0 |
| Config parser / placement fixture | PASS |
| docs drift and its negative controls | PASS; 89 knob names |
| Gate source inventory | 521 declarations; no gate execution |
| Measurement coordinator | Arm selection and ignored-knob/missing-INFO/override controls PASS; CLI normal/diagnostic delegation tested without processes |

The new matrix cases cover defaults, endpoints, file/CLI precedence, malformed
grammar, exact immutable rejection through validation and dispatch, INFO, and
REWRITE/reparse at each boot value. `tests/knobs.py` adds live default/immutable/
INFO coverage for mainline's gate. Literal/encoding searches used **grep** across
`tests/`; [before](docs/wbknobs/text-before.txt) and
[after](docs/wbknobs/text-after.txt) receipts retain quoted ledger/anchor matches.

An extra, non-gate invocation of the full **db0** netcmd `config` case fails at
`tracking map swapped`: its existing tracking test calls swap(0,1), unsupported
in db0. A separately compiled exact PRE fixture fails at the identical assertion
and exit 1. See [PRE](docs/wbknobs/pre-db0-config.log) and
[POST](docs/wbknobs/netcmd-unit-db0-config.log). The gate uses ordinary netcmd for
that case. The assertion was preserved; both new db0 knob cases pass.

Gate rows are exactly **+2/+2**. The two `NETCMD_CASE` additions are emitted by
`tests/gate.sh:1679`, before the quick exit at line 3407. The implementation
commit adds both rows and the explicitly authorized EXPECT update together:
502/519 -> **504/521**. The label fixture is source inventory, not a fabricated
run ledger.

**Mainline experiments.** Use the gate's existing ABBA instrument. The coordinator
only supplies the same-binary sweep's per-arm boot flags; sampling, population,
quiet checks, load accounting and scores remain in `tests/abbagate.py`.
It enforces equal ELF SHA-256 for the sweep and verifies CONFIG GET plus INFO
WRITEBACK before every population. Its source hash and arm settings enter the
receipt. No cell `srv=` override can replace the writeback arm settings.

Use the retained study's bench geometry: 32 real server cores 0-31, loaders
32-111, no SMT, loopback, 512 connections. The instrument derives 256 shards in
these fused cells. Deep cells retain **eight loader instances**; p1 cells retain
four. Do not replace these cell-specific instances with the headline load floor.
Mainline alone schedules these commands on a quiet box. The correctness gate's
16-shard / 6 IO + 2 EX / cores 0-7 geometry is a separate reproduction geometry.

| Set / file | Exact cells | Arms | Decision |
| --- | --- | --- | --- |
| Default null, `tests/wbland_merit_cells.txt` | h05, h06, p8g, p8s, d1g_l0, d1s_l0, m8g_l0, v1g_l0, d128g_l0, d32g_l1, d8s_l1, d32s_l1, x9_32_l1, x9_32_l0 | A newest headline defaults; B POST defaults | All 14 cells within the contemporary class band |
| Same-binary merit, `tests/wbknobs_sweep_cells.txt` | p8g, p8s | A POST policy=1,S=0,D=3; B the identical POST policy=1,S=16,D=3 | Default/half GET and SET each reproduce **+6..+10%** loopback merit |

The 14-cell shapes are GET/SET p32; GET/SET p8; GET/SET p1; MGET p8; GET:1024 p32;
GET p128; read-local GET p32; read-local SET p8/p32; and MIX 9:1 p32 with and
without read-local. Every cell is fused, overlap=1, reorder=0, atomic=1.

Run from this worktree, with unique output directories:

```sh
python3 tools/wbknobs_measure.py --experiment null \
  --candidate-binary build/wbknobs/POST/tomokv \
  --reference-binary /home/user/Projects/bench-bins/tomokv-headline-db86e5b4a \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --ports 8700-8799 --output build/wbknobs/mainline-default-null

python3 tools/wbknobs_measure.py --experiment sweep \
  --candidate-binary build/wbknobs/POST/tomokv \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --ports 8700-8799 --output build/wbknobs/mainline-same-binary-p8
```

Retain all four A/B/B/A samples and gate quiet/standing-null qualifications. For
the default comparison, require two-sided parity in every cell, using the
current band without widening it. The current simple check uses 3% for plain
and 5% for read-local cells; it only rejects regressions, so its PASS alone does
not establish a two-sided null. Investigate identical-arm spread >2% as
contention or a defect. Missing/refused cells are pending evidence, not passes.
The p8 deciding number is `100 * (median(default rate) / median(S=0 rate) - 1)`
for GET and SET separately; `wb-policy 0` is not the half-rule control.

Record rate at matched offered load, latency distributions, commands/send,
cycles/op, instructions/op and IPC. In this merged instrument PMU collection
is available only through its permanently diagnostic path. To obtain those
complementary counters, repeat each command with `--profile 1` and a distinct
output directory (`mainline-default-profile`, `mainline-p8-profile`). The
coordinator preserves the ordinary quiet checks and the instrument's untrusted
diagnostic marker. Those profiled runs explain the rate; they do not substitute
for the default `--profile 0` acceptance runs above. Preserve per-cell/arm
profiles with the comparison; do not combine samples across instrument modes.

| Pending performance receipt | A | B | Result |
| --- | --- | --- | --- |
| 14-cell default rate/latency null | Newest headline | POST defaults | MAINLINE PENDING |
| p8 GET merit | POST S=0 | Same POST defaults | MAINLINE PENDING |
| p8 SET merit | POST S=0 | Same POST defaults | MAINLINE PENDING |
| Per-cell cycles/op, instructions/op, IPC | Corresponding A | Corresponding B | MAINLINE PENDING |

Mainline also runs `tests/gate.sh iteration` at its own geometry. Targeted differ
suite names, one per line (with the ordinary zero-regression gate retained):

```text
compatintro
infofix
psfix
string
xshard
multi
```

Append the measured verdict and artifact paths to this worktree as
`MEASURE-RESULT`. No throughput, latency parity, or merit PASS is claimed by the
offline receipts.
