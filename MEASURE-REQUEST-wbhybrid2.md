wbhybrid2 — bounded completion wait, S=16. Performance verdict: PENDING MAINLINE.

Deliverables are REF, hyb16-d0/d1/d2 and exact-layout PAD A twins for d1/d2.
The checkout's production source and default `build/tomokv` retain the landed
policy-1 half rule. There is no runtime D selector. Candidate patches and source
copies are under `build/wbhybrid2/`. Mainline selects any eventual hardcode only
after the requested measurements and gate.

One requested proof has a limitation: strict byte identity of all unrelated
compiler-emitted bodies is not achieved. Source isolation, untouched-object
identity, d0 predecessor identity and exact PAD identity pass; the wider
compiler differences are disclosed under (d), not counted as an identity pass.

Launch HEAD: `018d23a4cac8f32a4eb56915ca394d80576b5883`. The FIRST action after
reading worktree status was merging `origin/cpp` (`90ba908d3`), producing
`339846ea6`. That merge changed only `tests/gate.sh` and
`tests/gate_measurements.json`. All production sources and the Makefile still
match REF `5b3d9c4292bf8b332d493beb485266ecc5a289aa`.

Builds used `taskset -c 112-127`, `make -j16`, the original Makefile flags,
jemalloc, link order and database namespaces. Serverless checks inherited those
CPUs. No server, load generator, gate, PMU, timed performance experiment, or
network workload was run. No push was made.

**Client field and ownership proof.** `uint8_t wb_deferrals_ = 0` consumes byte
72 of the existing padding between `Session` and the ROB. It is initialized at
construction and belongs only to the connection's IO owner. It is neither an
executor publication nor part of `connection_flags_`/`op_route_flags()`.

| Member/region | REF | d1/d2 |
| --- | --- | --- |
| `atomic_groups_io_` | 64..67 | unchanged |
| `session_` | 68..71 | unchanged |
| padding before ROB | 72..127 | counter at 72; padding 73..127 |
| `rob_` | 128..319 | unchanged |
| executor-facing line | 1920..1983 | unchanged |
| `connection_flags_` / `tls_slot_` | 55 / 1980 | unchanged |
| `sizeof(Client)` | 1984 | 1984 |

New assertions pin counter offset 72, ROB offset 128 and the counter to cache
line 1. Every pre-existing layout assertion still compiles. GDB's DWARF member
audit compares all **41 pre-existing Client member offsets and widths**, in
both `tomo` and `tomo_db0`; only the new one-byte member is added.
`build/wbhybrid2/layout.json` and the six `*-layout.txt` files contain the proof.
Physical-path fixtures also compile the full locks: Op 336, Client 1984,
ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624.
d0 uses the original Client declaration exactly.

**Rule and lifetime.** Let c be the deferrals accumulated since the last serve
or FIFO removal. A successful completion-mode deferral increments c once;
half-mode deferrals add zero. Consequently the counter saturates at D and
cannot wrap even if the head remains unfinished for thousands of visits.

| n | d0 | d1 | d2 |
| --- | --- | --- | --- |
| 0 or 1 | ordinary serve | ordinary serve | ordinary serve |
| 2..16, c=0 | n | n | n |
| 2..16, c=1 | n | ceil(n/2) | n |
| 2..16, c>=2 | n | ceil(n/2) | ceil(n/2) |
| 17..64, any c | ceil(n/2) | ceil(n/2) | ceil(n/2) |

D=0 names the plain predecessor hybrid, **not immediate fallback**. D1 defers
once for completion, then uses half on the next visit; D2 defers twice before
falling back. Fallback still requires the half prefix or the existing byte or
scatter exit. It does not retire an unfinished head or force a send with fewer
Done replies than the half rule accepts. This bounds the extra completion wait
in visits, not the underlying command's execution time or wall-clock latency.

The existing captured FIFO budget is unchanged. Deferral rotates the connection
to the tail while keeping `serve_pending` set. A later visit consumes the next
unit of this connection's wait budget; gathering more scratch chunks cannot
revisit a connection in the same captured FIFO pass.

Both removal sites in `wb_rule::Phase2` clear the counter immediately before
clearing `serve_pending`: `gather()` and `serve()`. This covers successful
admission, policy 0, n<=1, bytes, scatter, closing-but-live clients and dead
entries. Nothing resets on tail rotation. `io_loop.h` and the `reorder.cc`
envelope continue to call the same Phase2 implementation, without source edits.
Migration already requires `!serve_pending`; it cannot carry an outstanding
wait lifetime to another owner. No count, clock, allocation or retry was added
to operation execution or retirement.

The essential d1/d2 change to the predecessor rule is:

```diff
+inline constexpr unsigned kDeferVisits = D; // separate compiled arms: 1 or 2
-const unsigned threshold = n <= kSmallPipe ? n : ceil_half;
+const volatile bool complete = n <= kSmallPipe && c.wb_deferrals() < kDeferVisits;
+const unsigned threshold = complete ? n : ceil_half;
 // Existing acquire walk, reply-byte accounting and exits are unchanged.
 if (prefix >= threshold) return false;
+c.wb_deferrals() += complete;
 return true;
 // At BOTH Phase2 FIFO exits, before set_serve_pending(false):
+client->wb_deferrals() = 0;
```

The temporary predicate occupies a stack byte for this visit only. This prevents
the compiler from keeping another register live through integer reply encoding,
which otherwise introduces spills per scanned integer reply. The permanent
count remains the single Client byte. The checked receipts below lock the
extra work to the visit boundary for empty, GET, OK and integer replies.
There is one logical count comparison and one byte addition on a deferral;
the assembly also contains predicate materialization, stack accesses and
branches. It is not a claim of literally two additional machine instructions.
The reset is one byte store per admitted/removed connection. Half-mode
deferrals perform an add of zero to the IO-private byte.

Policy 0, n<=1, staged/reply 512 B exits, submitted-byte exclusion, acquire
semantics and Done MGET scatter exits are preserved. S=16 is the owner's
already-measured small-pipe cutoff. D is in connection visits; no machine-time
constant, new configuration grammar, ownership rule or per-operation retry is
introduced.

**Proofs (a)–(f).** Raw receipts live in `build/wbhybrid2/`; the committed digest
ledger is `tests/wbhybrid2_evidence.json`. The final audit rehashes every executed
witness, delivered arm and PAD, and compares generated source against the
committed generator.

| Proof | Result |
| --- | --- |
| (a) Decision table | REF/d0/d1/d2/PAD1/PAD2, both database compilations: n=0..64, every Done prefix, counts 0..3, ROB starts 0 and 61, policies 0/1. 17,160 table cells per binary. Exits cover staged and Done 511/512 bytes, submitted sends, Done/Issued scatter and holes. Real Phase2 gather and serve lifetime checks cover next-pipe reset, FIFO rotation, all bypasses, dead removal and 1,024 consecutive deferrals. 48 positive invocations. |
| (b) Existing witnesses | Unchanged wb_rule/wbland suites: 248 strict outcomes, 162 positive and 86 required assertion failures. Unchanged wbhybrid fixture: REF and predecessor d0, plus the half-behavior PADs, both namespaces; 16 positives and two S+1 controls. No existing test assertion changed. |
| Physical envelopes | 80 invocations: d0/d1/d2/PAD1/PAD2 × databases=1/4 × fused FIFO/R7 and split coarse/natural/shallow, with read-local off/on. Each sweeps depths 2/4/5/8/16/17/32/64, policies 0/1 and 96 clients across four visits; then completes them and checks the SAME connections' next pipe. Real ROB/WB/Phase2, synthetic SQ, no worker/listener/kernel SEND. Closing/dead exits are included. |
| (c) Negative controls | D-1 and D+1 fail `bounded decision table`; no-reset fails `served connection completes again next pipe` in BOTH real Phase2 entry points. Each mutation is checked for d1/d2 and both database namespaces: 16 exact exit-1 failures. Crash, timeout or an unrelated assertion is rejected. |
| (d) Identity | All production source bytes outside wb_rule.h and the Client field/accessors/assertions match REF. All 44 objects outside their complete include closure are whole-file byte-identical. d0 .text is byte-identical to predecessor hyb16. Each PAD differs from its candidate by exactly two immediate bytes. Strict identity of every other compiler-emitted body is NOT a pass; details below. |
| (e) SHA-256 | Six measurement arms sealed in the arm table and binaries.json. No build-ID equality is substituted for SHA-256. |
| (f) Instructions | 896 single-step defer receipts: 28 fixtures × counts 0..3 × four arms × two namespaces. Another 144 receipts price GET/OK/integer encodings. Setup excluded; no clocks, PMU, sockets or rate measurements. Early policy-0/n<=1/staged-512 exits have zero delta. Per-reply growth is unchanged from d0 for the tested encodings. Exact fixed costs are below. |

Total correctness outcomes: **410/410**, including **104 required failures**.
The 1,040 instruction receipts are additional, not counted as correctness rows.

**Byte-audit scope and limitation.** The inherited build selector compared
dependency spellings literally and missed includes written with `../`.
The new builder normalizes paths and rebuilds all 40 affected objects in each
arm; 44 untouched objects are reused and sealed. Both the Client constructor
and any inline rule consumer therefore see the same candidate definition.
The extra rebuilds leave d0's entire 7,564,433-byte .text identical to the
predecessor's frozen hyb16.

The complete function audit compares instruction bytes and resolved relocation
targets, including cold functions and TLS relocations. Native code generation
also changes unrelated bodies within those affected translation units. For
example, d0 itself changes `cfg_parse_memory` and `kvobj_external_bytes`, even
though its .text matches the predecessor exactly. Thus source isolation and
outside-include-closure byte identity pass, but a stronger claim of all
unrelated emitted bodies matching REF would be false. The complete inventory
is `code-identity.json`; it includes intended rule/reset/constructor changes
as well as compiler fallout. `strict_all_body_identity` is explicitly false
in the committed ledger. Do not mark this stronger form of proof (d) green.
The exact candidate/PAD pair holds all this native code generation constant;
PAD-versus-REF remains part of the acceptance decision.

| Native arm vs REF | Compared emitted bodies in rebuilt objects | Changed bodies | Added/removed |
| --- | ---: | ---: | ---: |
| hyb16-d0 | 12,071 | 33 | 0 |
| hyb16-d1 | 12,073 | 180 | 3 |
| hyb16-d2 | 12,073 | 180 | 3 |

**Arms and exact-layout controls.** All measurement arms use policy 1. PADs are
kind **A: behaviour twins**: PRE half-rule behavior in each candidate's exact
code shape/layout. The same decoded selector immediate as in the predecessor
is patched from 16 (`0x10`) to 1 (`0x01`). n<=1 has already returned, so every
remaining selector chooses half. The counter then adds zero and its resets
remain present. DWARF line information, function boundaries, opcode bytes and
the following unsigned conditional branch identify each site. Every other
ELF byte, address and section size is identical to its candidate. Build IDs
are deliberately retained; identify arms by SHA-256.

| Arm | .text bytes | SHA-256 |
| --- | ---: | --- |
| `build/tomokv-wbhybrid2-ref` | 7,564,593 | `70f51c094e2971219ea53fd056caa1d1fd7736045cbb9a81dea909fcbefb3e34` |
| `build/tomokv-hyb16-d0` | 7,564,433 | `649ee2e19105fcfd4565b972f08e6b07cbd90808a0f0080d4ab4f47af57cf67c` |
| `build/tomokv-hyb16-d1` | 7,564,609 | `18f4d74a9ee8a7be8cd258938387a54c48144a1c0b6be9c2e1953dd3b12c47f6` |
| `build/tomokv-hyb16-d1-pad` | 7,564,609 | `2ff77003403d7bca3c847f9f8b075f4a0d8ef62e39e3d255fa7984034687f2db` |
| `build/tomokv-hyb16-d2` | 7,564,609 | `e2c6860b1fdcc1bc68291d5f1ed46f1b8076c69c3687f9c8c8352642bcb637e5` |
| `build/tomokv-hyb16-d2-pad` | 7,564,609 | `d13a3586c3f020314c3ed6989a77cb339f1791f3e69e8404419df42ce1c40f1a` |

| PAD | Namespace | Selector address | File byte offset | Patch |
| --- | --- | --- | --- | --- |
| tomokv-hyb16-d1-pad | tomo | `0x421177` | `0x42117a` | `10 → 01` |
| tomokv-hyb16-d1-pad | tomo_db0 | `0xa6037` | `0xa603a` | `10 → 01` |
| tomokv-hyb16-d2-pad | tomo | `0x421177` | `0x42117a` | `10 → 01` |
| tomokv-hyb16-d2-pad | tomo_db0 | `0xa6037` | `0xa603a` | `10 → 01` |

Every arm retains `.tdata=112`, `.tbss=480`. Native text changes are small;
no inverse-control PAD B is supplied. All binaries are in this worktree's
`build/`, and the three generated patches are `build/wbhybrid2/hyb16-d{0,1,2}.patch`.

**Instruction receipts.** Counts include the same one-call wrapper boundary.
The complete table is costs.json; real encoder checks are code-costs.json;
both database variants are checked. Server disassemblies are the eight
`{ref,hyb16-d0,hyb16-d1,hyb16-d2}-{multi,db0}-defer.asm` files.

| n / Done / staged bytes / policy / scatter / count | REF | d0 | d1 | d2 |
| --- | ---: | ---: | ---: | ---: |
| 1 / 0 / 0 / 1 / 0 / 0 | 12 | 12 | 12 | 12 |
| 64 / 1 / 0 / 0 / 0 / 0 | 7 | 7 | 7 | 7 |
| 64 / 0 / 512 / 1 / 0 / 0 | 34 | 34 | 34 | 34 |
| 8 / 0 / 0 / 1 / 0 / 0 | 66 | 65 | 74 | 74 |
| 8 / 1 / 0 / 1 / 0 / 0 | 92 | 91 | 100 | 100 |
| 8 / 4 / 0 / 1 / 0 / 0 | 160 | 169 | 178 | 178 |
| 8 / 4 / 0 / 1 / 0 / 1 | 160 | 169 | 166 | 178 |
| 8 / 4 / 0 / 1 / 0 / 2 | 160 | 169 | 166 | 166 |
| 8 / 8 / 0 / 1 / 0 / 0 | 160 | 263 | 267 | 267 |
| 16 / 16 / 0 / 1 / 0 / 0 | 264 | 471 | 475 | 475 |
| 17 / 1 / 0 / 1 / 0 / 0 | 92 | 93 | 101 | 101 |
| 32 / 1 / 0 / 1 / 0 / 0 | 92 | 93 | 101 | 101 |
| 64 / 1 / 0 / 1 / 0 / 0 | 92 | 93 | 101 | 101 |
| 8 / 1 / 0 / 1 / 1 / 0 | 70 | 69 | 75 | 75 |

| Reply encoding, n=8 / Done / count=0 | REF | d0 | d1 | d2 |
| --- | ---: | ---: | ---: | ---: |
| OK, Done=1 | 96 | 95 | 104 | 104 |
| OK, Done=2 | 126 | 125 | 134 | 134 |
| GET, 71 reply bytes, Done=1 | 92 | 91 | 100 | 100 |
| GET, 71 reply bytes, Done=2 | 118 | 117 | 126 | 126 |
| integer 12345, Done=1 | 136 | 132 | 141 | 141 |
| integer 12345, Done=2 | 206 | 199 | 208 | 208 |

Completing a small pipe intentionally scans more Done slots than half. Those
extra visits are included, not subtracted as selector overhead. An empty/GET
reply adds 26 instructions per scanned Done slot, OK adds 30, and the integer
12345 fixture adds 67 under d0/d1/d2. The integer REF walk adds 70; that
predecessor-versus-REF code-generation difference is preserved. The new d1/d2
work does not grow with Done-prefix length in any of these encoder fixtures.
These receipts explain work, not rate or cycles/op; only the mainline's matched
load measurements can decide whether the fixed visit cost is worthwhile.

**Exact mainline request, in priority order.** Use all six named arms above:
REF, d0, d1, d2, PAD1 and PAD2. Retain each arm's individual samples and matched
REF observations. Keep candidate-versus-REF, candidate-versus-own-PAD and
PAD-versus-REF comparisons. Preserve the predecessor's seeds, population,
waveform and geometry. Never pool different floors or reorder states.

| Priority/class | Cells and repetitions | Deciding number and pass condition |
| --- | --- | --- |
| 1. Deciding bursts | Floor 0.4; reorder 0/1; 9:1 GET:BITCOUNT; mean 931K/s; up to 64 outstanding; off phase 372K/s, saturated on phase 1.49M/s. **Eight samples per arm/state**, including both PADs and REF. Same predecessor FLOOR-BURST duty/period, keys and seeds. | Short p99 and p99.9 must be within the contemporaneous PAD-versus-REF spread in BOTH reorder states, while retaining most of d0's p50 improvement. Report overall and long-class distributions and achieved rate too. A repeated same-sign excess is a loss, not an outlier to discard. |
| 2. Other bursts | Floors 0 and 0.7, each reorder 0/1; otherwise identical population/waveform. Four samples per arm/state, matching the predecessor's initial battery. | No p50/p99/p99.9 regression against half beyond the matched PAD/null spread. |
| 3. Low load | Closed-loop rate-limited GET p32@256K and p8@512K, the existing MIDLOAD geometry: 512 connections, 24 memtier instances. Three rounds per cell/arm. | Share within 0.2 ms, higher better, with achieved/offered rate and per-round spread. d1/d2 must retain the completion gains rather than falling back before useful batching. Keep <=0.5/1 ms as diagnostics. Compare directly with d0, not only REF. |
| 4. Saturation | Exactly the 14 generic cells in tests/wbhybrid2_cells.txt, parsed offline with abbagate.read_cells. Gate ABBA instrument, its current qualified pins and contemporaneous null. | Retain p8 GET/SET gain, p32 parity and no losing cell class. Report matched-load rate, cycles/op, IPC, instructions/op and commands/send. p1 rows use the existing latency score. |
| 5. NIC-LAT | calib/nic-latency.sh: GET/SET × p8/p32 × 60%/80% of the SAME fixed wire saturation references. 25GbE two-netns rig; 512 connections; ABBA ×2, four samples per candidate/REF pair. All five non-REF arms versus REF. | Retain the p8 p99 improvement of roughly 14–17%, plus p50/p99.9; no p32 loss. Preserve matched achieved load and commands/send evidence. Do not derive a different offered rate from each candidate's own saturation. |

The 14 generic IDs are h05, h06, p8g, p8s, d1g_l0, d1s_l0, m8g_l0,
v1g_l0, d128g_l0, d32g_l1, d8s_l1, d32s_l1, x9_32_l1 and x9_32_l0.
Their existing generic geometry is server 0–31, loaders 32–111, without SMT.
The NIC script owns server 0–31/loaders 64–127. Mainline alone runs these;
the lane's CPU restriction applies to its builds and serverless work.

The NIC script's fixed saturation references are GET p32=27.44M, GET p8=15.10M,
SET p32=25.66M, SET p8=14.88M. Keep its 512-way per-connection integer rate-limit
rounding, 10 s warm-up plus 25 s collection, and its stated percentile method
(mean of eight loader percentiles over the full run). Those are instrument
conventions, not claims of a globally pooled percentile.

Pass bar for any hardcode: never worse than half on any class, including
floor-0.4 short p99/p99.9, while retaining p8 saturation, low-load and wire gains.
For each D, report tail cost versus REF, p50 gain retained versus d0, low-load
attainment gain, p8 rate and wire p99. If neither D passes the entire map, return
that trade curve to the owner; do not choose a winner, invent a tolerance or
add a runtime mode. Mainline must additionally verify live boot/correctness in
1s/2s and databases=1/>1. Gate reproduction remains 16 shards and its configured
6-IO/2-EX geometry, not a default server boot.

All runtime PRE/POST cells are **PENDING**. No tail, rate or wire improvement
is claimed for these new arms. Record results in `MEASURE-RESULT`.

**Reproduction and gate accounting.** A clean REF build must log all compilation
and link commands; an incremental "nothing to do" log is insufficient.

```sh
mkdir -p build/wbhybrid2
taskset -c 112-127 make -j16 CXX='g++ -MMD -MP' all > build/wbhybrid2/ref-build.log 2>&1
taskset -c 112-127 python3 tools/wbhybrid2_artifacts.py builds
taskset -c 112-127 python3 tools/wbhybrid2_artifacts.py pads
taskset -c 112-127 python3 tools/wbhybrid2_artifacts.py identity
taskset -c 112-127 python3 tools/wbhybrid2_artifacts.py layout
taskset -c 112-127 python3 tools/wbhybrid2_artifacts.py proofs
taskset -c 112-127 python3 tools/wbhybrid2_artifacts.py paths
taskset -c 112-127 python3 tools/wbhybrid2_artifacts.py costs
taskset -c 112-127 python3 tools/wbhybrid2_artifacts.py code_costs
taskset -c 112-127 make -j16 CXX='g++ -MMD -MP' wbland-units
taskset -c 112-127 python3 tools/wbhybrid2_artifacts.py legacy
taskset -c 112-127 python3 tools/wbhybrid2_artifacts.py legacy_hybrid
taskset -c 112-127 python3 tools/wbhybrid2_artifacts.py code_identity
taskset -c 112-127 python3 tools/wbhybrid2_artifacts.py audit
```

`identity` also reads the predecessor's frozen
`/home/user/Projects/cx-wbhybrid/build/tomokv-hyb16`; it never edits that worktree.
The constructor and rule include closures are determined from normalized GCC
dependency files, and each artifact records its source/input hashes.

Gate row delta: **0 quick / 0 full**. No row is added or retired on either side
of the quick-tier exit. This lane did not edit EXPECT_QUICK or EXPECT_FULL;
the required mainline merge imported the existing 446/463 values unchanged.

Requested `git diff 018d23a4cac8f32a4eb56915ca394d80576b5883 --stat`
(includes the required mainline merge):

```text
 MEASURE-REQUEST               |   46 +-
 MEASURE-REQUEST-wbhybrid2.md  |  313 ++++++++++
 tests/gate.sh                 |    2 +-
 tests/gate_measurements.json  |    8 +-
 tests/wbhybrid2_cells.txt     |   15 +
 tests/wbhybrid2_codes.cc      |   19 +
 tests/wbhybrid2_evidence.json | 1274 +++++++++++++++++++++++++++++++++++++++++
 tests/wbhybrid2_paths.inc     |   86 +++
 tests/wbhybrid2_unit.cc       |  190 ++++++
 tools/wbhybrid2_artifacts.py  |  556 ++++++++++++++++++
 10 files changed, 2483 insertions(+), 26 deletions(-)
```
