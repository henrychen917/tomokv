TomoKV wbland — production handoff, 2026-09-29

Branch `cx-wbland`, base `9c4717da03b9340377926277f8eb99cea9f5ab5a`.
Production commit `fe2afd2de`; witnesses/artifact tooling `4024bdbef`.
The requested adaptive linear winner is now the ordinary `--wb-policy -1`
default in fused mode. Split AUTO deliberately retains the landed half rule
until its signal is measured; a separate frozen probe enables the same detector
there. Nothing was pushed or merged. All builds and serverless checks used
`taskset -c 112-127`, with `make -j16`. No server executable, listener, worker
loop, load generator, benchmark or gate was run.

Implementation and detector

`src/core/wb_rule.h` owns the feature, including the common acquire walk,
window, owner-local dial and optional diagnostic publication. Config, run-loop,
INFO and gate edits only wire it into existing surfaces. The measured reference
is `/home/user/Projects/cx-wbmode`, arm `build/tomokv-pol2-k1` (SHA-256
`7df8c94a99728144d2ef1db230a12a4394e23da5f93f91d464bc753477a8c710`),
as described by that lane's `MEASURE-REQUEST-wbmode.md` detector/window sections.
This is its linear fraction mechanism, not its AUTO policy-switch candidate.

At IO tenure entry the dial is zero. The first already-paid `tenure.pass()` cut
seeds wall and `sig.idle_ns`; no clock was added. A complete block contains
`W = max(1, self_->clients().size())` pass intervals. W stays fixed throughout
that block; its closing boundary selects W for the next block. The current
and previous complete blocks are combined by duration. After two blocks:

```
B = floor(256 * ((wall_current + wall_previous)
                - (idle_current + idle_previous))
              / (wall_current + wall_previous))
f = B / 256
threshold = ceil(in_flight * B / 256)
```

The dial holds between block boundaries. This is pol2-k1's two-block numerical
smoothing/history, with no separate switching band or zero-idle engage rule.
Unsigned 128-bit products execute only at a block boundary. At stable ownership
N, the decision spans `2*max(1,N)` passes and updates every `max(1,N)` passes.
A new IO tenure starts fresh; ownership changes cannot shorten an open block.
Zero-duration blocks provide no new observation. The signal is existing
wall-minus-idle, not thread CPU time or executor utilization. Delayed publication
of `sig.busy_ns` does not affect the input: the detector consumes wall cuts and
idle directly. Idle span boundaries and callbacks are unchanged from 9c4717da0.

At f=0, policy selection bypasses the walk completely. Otherwise it still
admits on staged/reply bytes >= `kWbufInline` (512 B), `in_flight <= 1`, a complete
contiguous Done pipe, or a Done MGET scatter marker. Submitted bytes remain
excluded; holes stop the scan; every reply-field inspection follows an acquire
load of Done. At f=1, the fraction clause waits for the full contiguous pipe,
while all byte/marker/fast-path exits remain. At f=1/2, ceil(n*128/256) equals
the reference's ceil(n/2) for every legal n, with the same slots/bytes inspected.
The one captured FIFO visit, lifetime pins, callback bound, overlap chunking,
AOF send gate, suppression, TLS and epoll handling are retained.

`State` lives on the IO run-loop stack. Its countdown and fraction are private;
an IoLoop tail pointer binds it once per tenure and is cleared on exit. No
completion-path store or per-pass shared policy store was added. Dynamic fused
AUTO alone allocates cache-line-separated `Published` rows (the split probe
also does). Fixed 0/1, PAD and production split AUTO allocate none. INFO sees
an atomic busy/fraction/active packet on the existing `sample_depth` beat
(100 us), plus tenure exit; window counters are independent diagnostic snapshots.
INFO has no retries and never reads the owner stack. All eight locked layouts
remain: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144, Config 624. Config uses four formerly reserved bytes. IoLoop
and Server each gain a tail pointer; their unlocked layout/text cost is why the
exact-layout PAD is supplied. No shard-owner structure, write ownership, QSBR,
read-local replacement, RYOW, scatter execution or ROB retirement law changes.

Knob documentation

The CLI and conf file accept exactly `-1`, `0`, `1`; no names, fractional values,
extra curves or quota settings. The default is `-1`. CONFIG GET/REWRITE preserve
the value; CONFIG SET rejects it as boot-only. Text is in the table at
`docs/CONFIGURATION.md:66`, with an annotated `tomokv.conf` entry and CLI help.

| Value | Meaning and measured interpretation |
| --- | --- |
| `0` | Flush all captured ready connections each pass; no detector/diagnostic allocation. Competition anchor loses 10–22% throughput at saturation. |
| `1` | Fixed composite, f=1/2, matching 9c4717da0 PHASE 2 behavior. No detector/diagnostic allocation. This new binary must measure null against 9c4717da0. |
| `-1` | AUTO, adaptive linear f=IO owner's windowed busy fraction, zero at idle to one at saturation. Competition winner on tail and p8; 2s currently uses policy 1 pending signal measurement. |

The source no longer has `kPolicyFraction`. The literal half fraction is only
the fixed policy 1 setting, including the explicit split/PAD/outside-tenure
fallback; it is not a tunable or AUTO threshold. No study exponent, ranking,
static quota or auto-switch surface was imported.

Deletions/replacements (line numbers in the frozen base unless marked current):

| Location | Removed/replaced |
| --- | --- |
| `9c4717da0:src/core/wb_rule.h:3` | `<ratio>` dependency. |
| `9c4717da0:src/core/wb_rule.h:8` / `:10` | Global POLICY-fraction comment and `kPolicyFraction` constant. |
| `9c4717da0:src/core/wb_rule.h:57` | Universal compile-time half threshold, replaced by the selected runtime fraction. |
| `9c4717da0:src/core/wb_rule.h:87` / `:111` | Unconditional half-policy calls in gather/serve, replaced by the same owner fraction in both. |
| `9c4717da0:src/core/config.h:426` | Four of the 80 reserved bytes, consumed by the signed boot knob. |
| current `tests/wb_rule_checks.py:31` | Old fraction-constant mutation spellings replaced with the equivalent runtime-expression sites; controls retained. |

The competition-only `wbmode.h` switch, sqrt/square tables, quota/ranking
vectors, f45 and static percentages never existed at this base, so they are
omitted rather than claimed as deletions from mainline. The linear window and
selection are consolidated into the existing feature header.

Historical PRE/POST motivation supplied at launch (2026-09-27/28)

PRE in this table is the landed half composite in that campaign. These are
competition results, not measurements of the newly built wbland artifacts.

| Cell | Linear POST vs PRE | Relevant control/context |
| --- | --- | --- |
| 9:1 burst 931K, reorder 0 | short p99 -15.3%, p999 -16.2%, p50 +4.1% | Layout twin p99 +6.5%, p50 +1.1%. |
| 9:1 burst 931K, reorder 1 | short p99 -10.0%, p999 -11.1%, p50 +1.1% | Layout twin p99 +4.2%, p50 +0.7%. |
| Loopback GET/SET p8 | +4.4% / +7.3% throughput | p32 within twin spread. |
| 25GbE GET/SET p8 | +14% / +14% throughput | Wire GET/SET p32 -1.1% / +2.9%. |
| 4096 connections; below-knee ladders | Flat | No invented below-knee cost to recover. |

The byte clause is unchanged: the competition's 4 KiB/16 KiB variants doubled
burst tail (+109..+126% p99). Absolute finished-amount quotas and nonlinear
curves are not production alternatives here.

Witnesses and controls

`tests/wbland_evidence.json` retains all strict outcomes, hashes and byte-audit
receipts. Each negative must exit **1 with the exact named assertion**. A crash,
timeout, missing marker or unexpected pass fails. Every production-path fixture
uses eight allowed CPUs and sixteen shards, split 6 IO + 2 EX, with no workers
started. Its only kernel submission boundary is wrapped. This reproduces the
gate geometry in memory without running the gate.

| Battery | Positive invocations | Required negative failures | Result |
| --- | ---: | ---: | --- |
| wbland detector | 18 | 15 | 33/33 |
| wbland runtime-derived clauses | 18 | 19 | 37/37 |
| wbland PHASE 2 paths | 28 | 3 | 31/31 |
| Original wbrule policy 1 policy/phase/stages/split-phase/split-overlap | 120 | 60 | 180/180 |

New detector cases cover every n=0..64 and prefix at idle/half/full endpoints;
trickle f=1/256; zero-idle saturation f=1; tiny idle rounding; uneven-pass up/down
ramp; duration weighting; connection-count changes; empty owner; new tenure;
zero-duration blocks; wide arithmetic; fixed/PAD/split fallback; INFO publication;
finished-pipe, nothing-in-flight, MGET and exact 511/512-byte boundary; and grammar.
The ramp reaches each 0/32/64/128/192/256/192/128/64/32/0 busy step after two blocks,
with monotonic boundary movement and no intra-block change. It ends after 22
complete blocks at zero. The **windowless mutant** replaces `window.due()` with
`true` and fails `ramp holds dial between full block boundaries`, exit 1.
Other controls force idle/busy, replace linear with SWITCH or reverse it, remove
history/ownership-derived width/duration weighting, break 0/1/full behavior,
remove finished/empty exits, arm split AUTO prematurely, or raise bytes to 4 KiB.

The original clause suite is reused through an AUTO dial derived at runtime
from two half-busy blocks; its original nineteen deletion controls are rebuilt
through the same wrapper. It observes acquire ordering and forbids speculative
reply-field reads, including discarded reads, and checks holes, marker payloads,
submitted bytes, odd ceilings and ROB wrap. Policy 1 also reruns all 180 original
outcomes. It is a PHASE 2 **behavior identity** claim, not a claim that adding the
knob preserved PHASE 2 opcodes or end-to-end performance.

Physical paths cover fused FIFO/reorder, split coarse/natural/shallow, split
read-local, and the split adaptive probe, in both database namespaces. Each
uses 96 partial/finished pipes plus staged-only output, crosses the overlap
scratch bound, and checks exact retirement, retained pins and one visit per
admission. Thus policy 0's uncapped service and every auto fraction are observed
in real production PHASE 2 bodies. Existing AOF, lifetime, closing/dead and
capture controls remain in the reused suite. All locked-size assertions compile
in both namespace variants. Additional checks passed: config parser, real
serverless CONFIG GET/SET rejection/REWRITE, generated R7 envelope parity,
unchanged idle-span tokens, and **16/16 GET/SET opcode + relocation identities**
against the locally rebuilt 9c4717da0. Ordinary release builds have no warnings;
intentional mutant deletions produce unused-variable/indentation warnings.

Reproduction (only builds and serverless fixtures):

```sh
taskset -c 112-127 make -j16 all wbland-units build/config-parser-test build/netcmd-unit
taskset -c 112-127 build/config-parser-test
taskset -c 112-127 build/netcmd-unit config
for group in detector clauses paths; do
  taskset -c 112-127 python3 tests/wbland_checks.py check "$group"
done
for group in policy phase stages split-phase split-overlap; do
  taskset -c 112-127 python3 tests/wb_rule_checks.py check "$group"
done
taskset -c 112-127 python3 tools/wbland_artifacts.py identity
taskset -c 112-127 python3 tools/wbland_artifacts.py arms
```

The local PRE was built by archiving 9c4717da0 into `build/wbland-pre-src` and
running pinned `make -j16 all` there. It is used for source/object comparison;
the requested mainline performance reference is the frozen bench-bins binary.

Gate rows and EXPECT arithmetic

`tests/gate.sh:1275` defines three adaptive rows: detector, clauses and paths.
`collect_job wbland_units` is at **line 2726**, before the quick exit at **line
2855**. The production-units builder owns their prerequisites. No old row was
retired; the CONFIG regression extends an existing row. Therefore quick is
**441 + 3 = 444**, full is **459 + 3 = 462** (plus the existing optional NIC row
arithmetic). **EXPECT_QUICK=441 / EXPECT_FULL=459 were not edited.** The
maintainer must change them before running the requested gate. Both physical
modes' live boots and the gate remain unrun, rather than counted as passes.

Frozen arms and PAD

All five images are produced from one ordinary linked build by changing only
the two namespaces' cold `wb_rule::build_arm()` immediates. Every other byte,
section size and symbol address is verified equal. There is no runtime study
knob. SHA-256 identifies arms; they intentionally retain the linked ELF build ID.
Do not pass `--wb-policy` to override a named arm's default during the campaign.
The study probe is an artifact, not the production split default.

**PAD kind A: behavior twin** — PRE's half-composite behavior with AUTO's exact
text and layout, detector/publication disabled. It retains the new common
fixed-policy dispatch, so **pol1 vs 9c4717da0 must be null** before attributing
the auto gain. No inverse-control B is claimed. Exact-layout A already separates
the active mechanism from the +33,756-byte text change; pol1/PAD versus PRE
prices the common code/layout cost. PRE .text = 7,577,489 B; every new arm
.text = 7,611,245 B. `.tdata=112`, `.tbss=480` in all arms and PRE.

| Artifact | SHA-256 |
| --- | --- |
| `/home/user/Projects/bench-bins/tomokv-headline-9c4717da0` | `84ddb8abba4d8c32196edadb860da45114379490432a900dfee76efb71bfdd72` |
| `build/wbland-pre-src/build/tomokv` | `e2dbc007f39aab291f824a3872d3c01747423e12ce9caf1cc601555991b4c189` |
| `build/tomokv` | `3ced0605f055a4dd9e780f68c1490fcaada17635b591d588a617a1c8a9a376f3` |
| `build/tomokv-pol0` | `2f7e51745fa46c65a2f05786bea839b0389c2b73088ce3a52414f6fff8874753` |
| `build/tomokv-pol1` | `80579dc393be8cb62e1f5dc0f11044d43a03bafde074a8116a18f2b62a20343a` |
| `build/tomokv-pad` | `a9a0ba03d62dc1423ca50d32317d140e08b0f5b2f9e0d448e782611e861fc254` |
| `build/tomokv-auto2s-probe` | `2455238e30f2401ac1db3f51ca321ffd7ef1547c7c80b0c7a00a5b64b106e182` |

`build/wbland-artifacts.json` records selectors, section sizes and exact-byte proof.

Mainline measurement campaign — not executed by this lane

Use frozen `/home/user/Projects/bench-bins/tomokv-headline-9c4717da0` as PRE.
Run the gate's own instrument, fresh nulls and interleaved ABBA blocks; at least
three valid paired blocks for deciding rate cells, and extend any comparison
inside spread. Record offered and achieved rate, short p50/p90/p99/p999, long
p50/p99, commands/send, per-cell cycles/op, instructions/op and IPC, arm spread,
CPU/connection geometry and hashes. Compare rates at matched offered load as
well as proven saturation. Instructions alone do not decide a win. Untrusted
saturation, contention, a failed witness or >2% identical-arm spread leaves the
cell unresolved. Do not average away a regression.

1. **14-cell merit, AUTO and pol1 versus PRE.** Use the exact rows in
   `tests/wbland_merit_cells.txt`: h05/h06 (GET/SET p32), p8g/p8s,
   d1g_l0/d1s_l0, m8g_l0 (MGET-8 p8), v1g_l0 (1 KiB GET), d128g_l0,
   d32g_l1, d8s_l1/d32s_l1, x9_32_l0/x9_32_l1. Geometry: 32 server
   cores 0–31, loader pool 32–111, row-specific loader count (4 at p1,
   otherwise 8), 512 connections, atomic=1, with each row's read-local,
   overlap and reorder settings. Preserve the instrument's load ladder and
   saturation proof. **pol1 must be null in every cell.** AUTO must preserve
   the winning p8 benefit and stay within measured spread of pol1 in every
   other saturated cell. If the common pol1 build regresses, diagnose it
   before attributing AUTO-vs-PRE gains.
2. **4096 connections.** `tests/wbland_4096_cells.txt` supplies GET/SET
   p1/p8/p32, all six in each physical mode. Run AUTO and pol1 versus PRE,
   and pol0 as the flush-all anchor where needed. Same 0–31/32–111 pools,
   eight loaders; split is 16 IO + 16 EX. Preserve p1 latency and saturation
   throughput at deeper pipes. Required verdict: pol1 null, AUTO within
   spread of pol1; no hidden high-connection regression.
3. **931K 9:1 burst, reorder 0 and 1.** Run PRE, AUTO, pol1, pol0 and PAD,
   separately for both reorder values. Reuse the established competition's
   tailgen burst timing, GET:BITCOUNT long-operation distribution, keyspace,
   pipeline/connections, warmup/duration and CPU geometry unchanged. Retain
   at least three interleaved repetitions per arm, extending if inside
   spread. Match **931,000/s offered** and report achieved load, short p50,
   p99 and p999, long p99 and commands/send. AUTO must beat the half rule on
   short p99 and p999 with the gain exceeding the PAD/null spread, while its
   p50 cost stays consistent with the winning linear competition rather
   than the discarded switch's +13.5%. Reproduce the reported -15.3/-10.0%
   p99 and -16.2/-11.1% p999 direction; a new materially larger p50 cost or
   lost tail benefit is a landing failure, not an averaged merit pass.
4. **Both steady ladders.** GET:BITCOUNT 9:1 and 8:2, each at 700K/800K/880K
   offered, for PRE, AUTO, pol1, pol0 and PAD. Keep the mainline drainall-knee
   geometry and instrument, warmup 5 s, duration 20 s, at least two
   interleaved rounds and further repeats near spread. Run fused reorder
   0/1 and split overlap 0/1 (split reorder remains unavailable). Record all
   short/long quantiles and achieved rate. AUTO must be within measured
   spread of pol0 below the knee; pol1 must be null versus PRE. These are
   separate cells from the burst, with no claimed below-knee recovery.
5. **Single-process signal ramp.** Keep each server and its connections
   alive through offered 500/600/700/800/880/900/931/950/1000K and reverse,
   then genuine idle, in both 9:1 and 8:2 shapes. Run fused AUTO and the
   fixed anchors, then the split probe described below. Collect `INFO
   WRITEBACK` and existing LB signal snapshots at the same low cadence
   across arms; record each active owner's ownership population, busy256,
   f256, window_passes and increasing windows. Windows must close and the
   linear dial must follow **observed** demand toward idle/full endpoints;
   a 1M mixed workload is not itself proof of busy=1. Preserve enough time
   per step for at least two full ownership-sized blocks. Do not restart
   between steps or replace per-owner evidence with a rollup. Monotonicity
   is exact for the deterministic fixture, conditional on the measured
   busy signal for noisy live samples; no windowless flapping is acceptable.
6. **25GbE A/B.** Use the established two-netns NIC rig and the competition's
   server/loader placement, connections and NIC tuning. Run GET and SET at
   p8 and p32 for PRE, AUTO, pol1 and PAD, with fresh nulls and ABBA blocks;
   add pol0 at p8 as the flush-all anchor. Record commands/send and matched-
   load cycles/op, instructions/op and IPC along with achieved throughput.
   pol1 must be null. AUTO should retain the wire p8 win (historically
   +14%/+14%) and remain within the qualified twin spread on p32 (historical
   GET -1.1%, SET +2.9%). A loopback-only result cannot pass this send-path
   check. Run the NIC burst/tail A/B on the same 931K shape if the established
   instrument supports it; do not substitute it for the required loopback
   burst.
7. **2s signal qualification, separately scored.** Production AUTO keeps
   policy 1: both normal split and split read-local use it, including coarse,
   natural/shallow overlap and idle sweeps. The signal definition is shared,
   but an IO-only owner can spin on deferred partial replies while its EX
   owner is busy. That time is demand here without measuring EX utilization;
   it can feed back into the fraction. There is no new reclassification of
   deferred work as idle. The supplied evidence does not establish that
   this IO-only pressure means the same thing as fused pressure.

   Run `build/tomokv-auto2s-probe` versus production AUTO, pol1, pol0 and PRE
   on the GET/SET p1/p8/p32 rows, the six split 4096 rows,
   MGET/MSET p8 and tails in `tests/wb_rule_2s_cells.txt`, plus the two
   steady ladders and signal ramp above. The split throughput geometry is
   16 IO + 16 EX on cores 0–31. Repeat h21/h22, w2g8/w2s8 and deciding tails
   with overlap 0 and 1 and read-local 0 and 1; request reorder 0/1 for a
   split null check. INFO reports `wb_split_probe:1` only in the study image.
   Compare IO busy with EX busy and actual completed work. If deferred work
   keeps f high below the knee or IO stays idle at an EX saturation point,
   record that discrepancy rather than fitting a threshold to it. Enable
   split adaptation only after it clears the same per-cell throughput,
   below-knee and tail bars. This handoff deliberately leaves it at half.
8. **PAD attribution and then gate.** Measure PAD versus PRE/pol1/AUTO on
   every deciding merit, 4096, burst and NIC cell; all arms have identical
   candidate layout. A real mechanism gain moves AUTO while PAD remains
   within the pol1/null envelope. Preserve the independent pol1-versus-PRE
   common-cost check. Once the maintainer updates the two EXPECT constants
   and accepts the performance evidence, run **`tests/gate.sh iteration`**
   with its normal eight-core `GATE_CORES=0-7`, `--shards 16`, split 6 IO +
   2 EX (`GATE_RATIO`), then its own ABBA tier. Confirm both modes boot and
   explicit policies 0/1/-1 in both modes, including reorder/read-local and
   overlap coverage. Do not use the 32-core merit geometry to reproduce a
   failing correctness row.

Example **mainline-only** merit invocation (the lane did not execute it):

```sh
taskset -c 0-111 python3 tests/abbagate.py \
  --cells tests/wbland_merit_cells.txt \
  --candidate-binary "$PWD/build/tomokv" \
  --reference-binary /home/user/Projects/bench-bins/tomokv-headline-9c4717da0 \
  --build-reference 0 --server-cores 0-31 --load-cores 32-111 --load-smt '' \
  --ports 7933-7940 --output build/merit-wbland-auto
```

Repeat with `build/tomokv-pol1` and a separate output directory, then the 4096
cell file. Named artifacts freeze policy defaults; the same source still
accepts explicit `--wb-policy 0/1/-1` for the live correctness matrix.

| New-build comparison | Deciding result | Status |
| --- | --- | --- |
| pol1 vs frozen 9c4717da0 | Null per rate/latency cell; common dispatch/layout cost bounded | Pending mainline |
| AUTO vs pol1/PRE/PAD | p8 and burst benefit survives; no per-cell regression | Pending mainline |
| Both below-knee ladders | AUTO matches pol0 within spread | Pending mainline |
| 25GbE GET/SET p8/p32 | Send-path benefit, qualified p32 neutrality | Pending mainline |
| Split adaptive probe | Per-owner signal + same performance bars; no feedback latch | Pending; production remains half |
| Live boot + iteration gate | Both modes; 444 quick / 462 full row accounting | Pending mainline |

Append raw paired rates, quantiles, cycle/instruction/IPC evidence, INFO dials,
spread, exact hashes and gate receipts as `MEASURE-RESULT`. This report stops
at the committed code, built arms and serverless evidence; it claims no new
quiet-box result or gate pass.
