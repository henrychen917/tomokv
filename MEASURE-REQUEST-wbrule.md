TomoKV wbrule — mainline handoff, 2026-09-24

Production code commit: `17bc1ed4b` on `cx-wbrule`, based on `3e734cf2e`.
The delivered `build/tomokv` implements the measured **w4-c12** rule in physical
**1s only**, with the existing parse/EX widths **32/32** and ROB window **64**.
The mainline owns merit, live correctness, both-mode boots, and the gate. None
was run here; **a green gate or a new performance result is not claimed**. Nothing
was pushed. Compiler and executable-unit commands used `taskset -c 112-127`;
make used `-j16`.

The supplied mainline measurements justify selecting c12: h05/h06 +6.4/+11.8%,
p8 GET/SET +22.9/+20.4%, with the known MGET-8 p8 loss of 2.1%. They describe the
previous measured artifact. The new binary, particularly its changed text layout,
still requires the merit re-check below.

**Diagnosis and implementation.** A fixed 16-connection fused serve allowance
interrupts consolidation independently of available reply bytes and contiguous
completion. `src/core/wb_rule.h` owns the replacement: the staging accessor,
coded/direct/spill/borrow byte lengths, acquire walk, captured FIFO traversal,
deferral rotation, and ordinary fused writeback invocation. The dimensionless
`kPolicyFraction` is the single named `std::ratio<1,2>` policy constant, with the
competition record section 39 citation. The byte threshold is the existing
`kWbufInline` (512 bytes), derived from staging. No knob, timer, count floor,
per-operation store, completion bookkeeping, or Client/ROB sidecar was added.

After the unchanged AOF gate, the fused helper captures the FIFO length, visits
each captured entry at most once, removes dead entries, and ordinarily serves
`in_flight <= 1`. It counts fill bytes plus unsent send/segment bytes when no
send is outstanding. It next acquire-walks Done slots from `flush_id()`, stopping
at the first hole, and opens at either the byte threshold or `ceil(n/2)` Done
commands. A deferred pointer rotates with its lifetime pin retained; eligible
younger connections pass it, callback arrivals cannot extend the captured pass,
and remaining work prevents parking. Retirement and send continuation remain in
WbEngine. Existing deque rotation can recycle/allocate a deque block; the rule
adds no persistent allocation or byte counter.

The accessor reuses `Client::buffered_output_bytes()` only with no send in flight;
otherwise it returns fill size. At valid writeback frontiers its remaining-send
term equals the measured accessor's `send_buf().size() - wsent()`. It excludes
submitted segment bytes too. Reply fields are read only after Done acquire;
negative retire-state markers do not contribute borrowed payload bytes.

A mode-boundary defect was caught during the port: **Fused is also the reader
capability tag of 2s read-local IO**. Testing only `if constexpr (Fused)` would
silently enable c12 in its overlap=0 PHASE 2. The existing `SplitLocal` tag now
travels through the coarse and idle-sweep call sites to `flush_ready`; the policy
condition is `Fused && !SplitLocal`. This adds no runtime selector. The extra IO
and generated R7 changes are that call-site plumbing and the fused helper call.
The original split loop remains in the other compile-time branch. Parser/R7
parser bodies, EX batching, read-local execution, atomics, and database code are
unchanged. Neither split overlap schedule is enabled for the composite rule.

**Byte and source identity.** `tools/wb_rule_artifacts.py` verifies **40/40 split
PHASE 2 instances**, including physical 2s read-local, and **158/158 audited
split stage/caller and GET/SET function bodies** (16 of those are GET/SET).
It compares opcode bytes and resolved relocation targets. It maps only the newly
forwarded SplitLocal template argument to the old callee identity; it does not
normalize instructions, register choices, constants, or internal branches. The
40 complete PHASE 2 bodies match, not merely their branch conditions. No compiler
budget change was needed or retained. Layout locks compile in both namespaces:
Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144, Config 624; `.tdata=112`, `.tbss=480` remain unchanged.

The same tool compares `code_bytes`, `reply_bytes`, and the eligibility walk with
`tools/window4/window4_study.h`, specializing only c12's fraction=2,
unless-long=0, ratio=0 and normalizing the testable template type spelling.
It also checks both ordinary-serve copies and the unchanged split loop tokens.
No ROB/128, unless-long, ranked, busy, ratio-floor, boot-selector, or study PAD
machinery is included in production.

The source-of-truth generated patch is preserved at
`build/drainall/window4-source.patch`, SHA-256
`d05fabc5a0b58232e10afa72ad1258514e6bade690af9446b769b4ef2e2251ff`.
`build/wbrule-vs-window4-phase2.diff` shows the PHASE 2 adapter changes explicitly;
`build/wbrule-artifacts.json` binds the canonical clause hashes, measured inputs,
function identities, binary digests, and positive/negative witness receipts.
The PRE build's complete `.text` equals `/home/user/Projects/cx-final/build/tomokv`
(SHA-256 of the section: `fca3ad2635d76f685a086f6f86f2e23741db0d4744a237574747973d1f1f7fdc`).

To reproduce the serverless evidence and inspect the measured patch:

```sh
cd /home/user/Projects/cx-wbrule
taskset -c 112-127 make -j16 all wb-rule-units
for group in policy phase stages; do
  taskset -c 112-127 python3 tests/wb_rule_checks.py check "$group"
done
taskset -c 112-127 python3 tests/r7shadow_sync.py
taskset -c 112-127 python3 tools/wb_rule_artifacts.py
sha256sum build/drainall/window4-source.patch
# The patch contains the measured helper and adapter; the normalized clause audit
# specializes its c12 constants and emits the focused PHASE 2 diff.
cat build/wbrule-vs-window4-phase2.diff
git diff 3e734cf2e -- src/core/io_loop.h src/core/wb_rule.h src/core/reorder.cc
```

**Witnesses and controls.** **93/93 strict outcomes passed: 62 positives and 31
expected assertion failures.** Policy: 36/36; PHASE 2: 32/32; stages: 25/25.
The parser, default split EX entry (masked/unmasked/timed), ordinary and armed R7
fused PHASE 2, and both database namespaces are exercised. Fixtures declare eight
in-memory threads and 16 shards, including split 6 IO + 2 EX. The kernel SQ boundary
is intercepted; no listener, worker loop, server workload, or real SQ submission
runs. The tiny SQ proves that serving continues across more than one submission.

The fraction witness exhausts every prefix for n=1..64 (2,144 cases per namespace)
with real ROB wrap starting at 61. Byte cases cover below/equal/above threshold,
combined sources, direct/spill/borrow+CRLF/coded output, segments and send remainder,
submitted-byte exclusion, and poisoned state markers. The read-observing
specialization executes the same eligibility template and rejects every reply-field
read before the exact acquire of Done. The real split EX witness invokes
`drain_tasks<>`, and observes batch frontiers at real GET handlers; specifying 32
only in the test call cannot accidentally certify a widened default.

Every control below compiles an isolated altered production header under build/,
uses the same test and expected answer, and must exit **1** with the shown
assertion. Crashes, timeouts, missing markers, and unexpectedly passing controls
fail the checker. The normal header passes the corresponding assertions.

| Removed/broken clause (control) | Assertion that failed | Negative result |
|---|---|---|
| `fastpath` | fast path reads no staging or slots | exit 1, exact assertion matched |
| `staged-clause` | staged byte threshold | exit 1, exact assertion matched |
| `staged-source` | staged fill/send remainder/segments | exit 1, exact assertion matched |
| `submitted` | submitted bytes excluded | exit 1, exact assertion matched |
| `done-bytes` | Done prefix byte threshold | exit 1, exact assertion matched |
| `spill` | spill/direct/borrow including CRLF | exit 1, exact assertion matched |
| `direct` | spill/direct/borrow including CRLF | exit 1, exact assertion matched |
| `borrow` | spill/direct/borrow including CRLF | exit 1, exact assertion matched |
| `crlf` | spill/direct/borrow including CRLF | exit 1, exact assertion matched |
| `no-sum` | Done prefix bytes accumulate across slots | exit 1, exact assertion matched |
| `floor` | ceil half for every n=1..64 and prefix | exit 1, exact assertion matched |
| `whole` | ceil half for every n=1..64 and prefix | exit 1, exact assertion matched |
| `hole` | first hole stops fraction and bytes | exit 1, exact assertion matched |
| `marker` | retire-state poison is not payload | exit 1, exact assertion matched |
| `code` | coded lengths match production encoder | exit 1, exact assertion matched |
| `relaxed` | Done load must acquire | exit 1, exact assertion matched |
| `pre-read` | reply field read before Done acquire | exit 1, exact assertion matched |
| `walk-tail` | walk exits at successful fraction | exit 1, exact assertion matched |
| `budget` | exact mode-specific budget | exit 1, exact assertion matched |
| `rotation` | deferred rotation preserves order | exit 1, exact assertion matched |
| `head` | younger eligible passes deferred head | exit 1, exact assertion matched |
| `pin` | deferred lifetime pins kept | exit 1, exact assertion matched |
| `capture` | callback cannot extend captured visit count | exit 1, exact assertion matched |
| `visit` | deferred rotation preserves order | exit 1, exact assertion matched |
| `dead` | dead entry removed and unpinned | exit 1, exact assertion matched |
| `work` | deferral alone is positive work | exit 1, exact assertion matched |
| `split-policy` | 2s never applies fused eligibility | exit 1, exact assertion matched |
| `split-local` | 2s reader capability never enables fused writeback | exit 1, exact assertion matched |
| `split-budget` | exact mode-specific budget | exit 1, exact assertion matched |
| `split-ex` | default split EX chunk remains 32 | exit 1, exact assertion matched |
| `parse` | unchanged parser quantum | exit 1, exact assertion matched |

The FIFO tests additionally assert unretired deferred prefixes, pin-based enqueue
deduplication, release after completions with no fresh arrival, and p1's refusal
to retire Issued work. The capture fixture actually arms a retire callback; the
split-selector control includes enough eligible tails to terminate at its budget
and fail an assertion instead of hanging. Split read-local is explicitly armed
and checked through both direct PHASE 2 and the idle sweep.

Witness executable digests:

| File | SHA-256 |
|---|---|
| `build/wb-rule-unit` | `5d8b83622636d5732f6e9c970fe6c9bf0132d1f4a939688e8f5f10584c01275d` |
| `build/wb-rule-db0-unit` | `c13246fce97246ccd5875d1d56cc87dab308404b89f7951afd9d760472feb00b` |
| `build/wb-rule-phase-unit` | `5ec7711cec0c4575dd3ea6eb485f45badbae51a15318aac456a78204c1c06a6e` |
| `build/wb-rule-db0-phase-unit` | `2acda7734f59c88c0cbdd92216626900225d347eb981f7d8cab5fbe51df222a0` |

**Deletions.** Locations in the first column refer to the launch tree
`3e734cf2e`, so a removed line has an unambiguous address.

| Deleted item | Replacement/current location |
|---|---|
| `src/core/genthread_pipeline.h:12`: `kGenthreadWbBatchConns = 16` | No fused connection allowance remains; `src/core/wb_rule.h:80` captures the FIFO. |
| `src/core/io_loop.h:5159`: fused arm of the shared serve-budget selector, and its 16-connection loop bound | Physical 1s calls the feature at `src/core/io_loop.h:5157`; only the split branch uses `kServeBudget`. |
| `src/core/reorder.cc:1321`: generated R7 copy of that fused selector/bound | Regenerated fused feature call at `src/core/reorder.cc:1318`. |
| `src/core/io_loop.h:5140` and `src/core/reorder.cc:1302`: comments claiming PHASE 2 universally serves at most the fixed budget | Comments now distinguish fused composite and split budget. |

`kServeBudget` remains at `src/core/io_loop.h:5570`, **for 2s only**, including its
read-local capability path. Split overlap=1 keeps its existing gather/scratch
schedule. The launch production tree contained no window4 selector/PAD scaffolding
to delete; none was imported. `rg` finds no `kGenthreadWbBatchConns`,
`TOMO_WINDOW4`, `window4_study`, or `TOMO_DRAINALL` in production sources/Makefile/gate.

**MGET-8 p8 diagnosis and separate candidate.** A cross-shard MGET uses **one ROB
slot per command**, while owners complete its per-key sub-operations in
ScatterState. Done publishes the command. WbEngine invokes the retire hook before
generic staging (`src/net/wb.h:802`); `assemble_mget`
(`src/cmd/xshard_commands.inc:1707`) then constructs the multibulk header and value
segments. Before retirement, negative `zc_shard` is a state marker, and `zc_len`
is not a payload length. A successful Done descriptor can therefore contribute
zero to c12's visible byte estimate.

Eight 64-byte values eventually encode 572 RESP2 bytes (4 + 8*71), above the
512-byte threshold, but c12 can still defer a prefix of one, two, or three such
Done commands at n=8 until the **fourth command** completes. Per-key sub-operations
do not occupy ROB slots or create separate prefix holes. With a zero-byte prefix
of length 1/2/3, the walk performs 2/3/4 acquire probes respectively, including
the first hole; at a successful four-command prefix it performs four probes.
For each Done slot it loads/sums the ordinary reply descriptors, excludes the
negative marker's payload, then WB walks the prefix again. In general the walk is
bounded by `ceil(n/2)` or prefix+one-hole, with earlier byte success. It never
walks sub-operations. Local-fast/materialized MGET replies are already visible
and can open the byte clause normally. This explains the undercount and added
work; it is **not a profile attributing the measured -2.1% entirely to them**.

There is no assembled multibulk length to count once at Done without new
publication or walking the private values. The cheap alternative implemented
separately returns to ordinary serve at the first **acquired Done scatter marker**.
It reads no ScatterState, changes no publication or retirement order, and leaves
assembly in WB. It applies to scatter commands generally, including small replies;
that deliberately changes coalescing and needs an independent verdict.

That change is isolated on branch `cx-wbrule-mgetfix`, commit `306e0ef5d9e85a3bfd2ba40962335d74c0b5070a`.
It is **absent from cx-wbrule and build/tomokv**. Its only production change is in
`src/core/wb_rule.h`; test expectations and a clause-removal control accompany it.
The independent binary is `build/tomokv-mgetfix`, with its patch at
`build/wbrule-mgetfix.patch`. **94/94** strict serverless outcomes pass (the same
suite plus its missing-scatter-exit control). It remains a later landing only if
mainline measurements show it pays.

**Artifacts and text size.** PRE was built from an archive of `3e734cf2e` under
`build/wbrule-pre-src`. Relinking its exact objects/flags reproduces its complete
SHA-256. The physical-role distinction requires separate template instances for
1s and 2s read-local; the new executable is consequently larger than the historical
study c12 artifact. There is no claim of identical whole-executable placement.

| Artifact | .text bytes | Delta vs reference | SHA-256 |
|---|---:|---:|---|
| `/home/user/Projects/cx-final/build/tomokv` | 7,445,436 | +0 | `08814d7099be2ff96c05715ebbbb5ef7a1569746485980fab0c49f02d042f8e7` |
| `build/wbrule-pre/tomokv` | 7,445,436 | +0 | `bc5c805eb712ce6e906b96e199770bd473464b2be50ec2fd7e6c69417d709b8a` |
| `build/tomokv` | 7,550,604 | +105,168 | `f1b97161338c14083352bb3016031e3bea98a1ac5e1e1e2bc07b8bbacf8e26d4` |
| `build/tomokv-pad` | 7,550,604 | +105,168 | `b4e00a827c7dacc52ceb6cef816163955f72f9f2242af5e7a8998053a4ace38f` |
| `build/tomokv-mgetfix` | 7,550,988 | +105,552 | `72a79bd346512e96d452b8c9c9187fb0ce09c19c4d43d5287d75e88407047e44` |

PAD is **A: behaviour twin**: PRE behaviour with unreachable padding matching the
candidate's aggregate `.text` size exactly. It does not match individual function
addresses or internal layout. Its receipt is `build/tomokv-pad.json`. No PAD or
selector code enters the release source. The MGET candidate is +384 text bytes
relative to c12 and is kept in its own file. All three final candidate/control
binaries retain `.tdata=112` and `.tbss=480`.

```
f1b97161338c14083352bb3016031e3bea98a1ac5e1e1e2bc07b8bbacf8e26d4  build/tomokv
72a79bd346512e96d452b8c9c9187fb0ce09c19c4d43d5287d75e88407047e44  build/tomokv-mgetfix
```

**Gate accounting.** The task-specific requirement 5 explicitly requested the
EXPECT update, overriding the shared background's usual maintainer-only rule.
`EXPECT_QUICK`: **438 -> 441**; `EXPECT_FULL` (including iteration correctness):
**454 -> 457**. There are exactly **three added rows**, one per checker group.
They are collected at `tests/gate.sh:2709`, **before** the quick-tier exit at
`tests/gate.sh:2838`; therefore +3 quick and +3 full, with no rows retired and
none added after the quick exit. Build readiness uses the complete control-binary
stamp. Gate syntax and generated R7 envelopes pass. Final compile logs contain
no warnings/errors, and both builds are up to date. The full/iteration gate was
not run by this lane; the required mainline acceptance is **0 gating FAIL**.

**Exact mainline commands.** The committed `tests/wb_rule_cells.txt` preserves the
seven requested workloads and IDs from the existing headline/window studies,
including source-file digests, with eight loaders explicit in every cell. The
headline load-floor metadata can otherwise select a different loader count.
Run serially on the quiet box with matched offered load. The wrapper below uses
the gate's ABBA instrument and its existing PMU diagnostic API, retaining the real
QuietMonitor and all workload checks. The normal CLI has no profile switch.
Record per-cell cycles/op, instr/op and IPC for the PRE/POST ledger; an
instruction-count-only verdict is insufficient.

```sh
cd /home/user/Projects/cx-final
abba_with_counters() {
  taskset -c 0-111 python3 -c '
import sys
sys.path.insert(0, "tests")
import abbagate as abba
raise SystemExit(abba.main(abba.parse_args(),
                          diagnostic_monitor=abba.QuietMonitor,
                          diagnostic_profile=1))
' "$@"
}
# Three independent ABBA blocks, including an A behaviour twin against the same reference.
for block in 1 2 3; do
  for arm in POST PAD; do
    if [ "$arm" = POST ]; then
      candidate=/home/user/Projects/cx-wbrule/build/tomokv
    else
      candidate=/home/user/Projects/cx-wbrule/build/tomokv-pad
    fi
    abba_with_counters \
      --cells /home/user/Projects/cx-wbrule/tests/wb_rule_cells.txt \
      --only h05,h06,p8g,p8s,m8g_l0,v1g_l0,d128g_l0 \
      --candidate-binary "$candidate" \
      --reference-binary /home/user/Projects/cx-final/build/tomokv \
      --build-reference 0 --server-cores 0-31 --server-smt '' \
      --load-cores 32-111 --load-smt '' --max-instances 8 \
      --ports 7933-7940 \
      --output "/home/user/Projects/cx-wbrule/build/merit-wbrule-${block}-${arm}"
  done
done

# Separate optional hypothesis: compare the MGET exit against c12 itself.
abba_with_counters \
  --cells /home/user/Projects/cx-wbrule/tests/wb_rule_cells.txt \
  --only h05,h06,p8g,p8s,m8g_l0,v1g_l0,d128g_l0 \
  --candidate-binary /home/user/Projects/cx-wbrule/build/tomokv-mgetfix \
  --reference-binary /home/user/Projects/cx-wbrule/build/tomokv \
  --build-reference 0 --server-cores 0-31 --server-smt '' \
  --load-cores 32-111 --load-smt '' --max-instances 8 \
  --ports 7933-7940 \
  --output /home/user/Projects/cx-wbrule/build/merit-wbrule-mgetfix

# Gate the primary branch only after its merit passes; this does not include the MGET branch.
cd /home/user/Projects/cx-wbrule
tests/gate.sh iteration
```

The `--only`/profile merit runs are scoped diagnostics, not a full-gate receipt;
their diagnostic completion is PARTIAL/exit 3. Inspect every measurement-validity
result, including failures. Preserve the instrument's null/spread and saturation
checks. Every scored c12 cell must
meet the stable reference except the known MGET-8 p8 exception; PAD staying flat
while POST moves supports mechanism attribution. A new loss is not averaged away.
For MGETFIX, require an MGET improvement against c12 with no new losses in the
other cells before considering its separate commit. The gate must still finish
with zero gating failures; no EXPECT relaxation or benchmark tolerance is proposed.

PRE versus POST ledger — **mainline to fill from this binary's merit re-check**.
Each tuple is **(rate, cycles/op, instr/op, IPC)** at matched offered load, with
`cycles/op = instr/op / IPC`. Prior rates are supplied historical context only.

| Cell | Supplied prior c12 rate delta | PRE tuple | POST tuple | Re-check decision |
|---|---:|---|---|---|
| h05 | +6.4% | PENDING | PENDING | PENDING |
| h06 | +11.8% | PENDING | PENDING | PENDING |
| p8g | +22.9% | PENDING | PENDING | PENDING |
| p8s | +20.4% | PENDING | PENDING | PENDING |
| m8g_l0 | -2.1% | PENDING | PENDING | Known exception; re-check |
| v1g_l0 | +0.6% | PENDING | PENDING | PENDING |
| d128g_l0 | +0.8% | PENDING | PENDING | PENDING |

Retain commands/send and latency alongside the paired counters, and append the
mainline result as MEASURE-RESULT. No measurement was awaited or scheduled by
this lane.

**Bound receipt digests.**

| Receipt | SHA-256 |
|---|---|
| `build/wbrule-artifacts.json` | `4282689d338445f20fc2d0b7d404906834cb219fd11dd33ebf3232eedbe68c29` |
| `build/wb-rule-policy-proofs.json` | `fe6286aa0b83937ea5a66493a01ed601ce30db82f8dfae7ede3e447f43f83abd` |
| `build/wb-rule-phase-proofs.json` | `6e3d576aca7671d201560553f66a4f1814046d8ea10e4e1b02c6b78a74fb6843` |
| `build/wb-rule-stages-proofs.json` | `c7aede87e5ab8eb4d0c4fa1fd6ae9e5f5e9cafc55d82c9cffdbe3a071e81da84` |
| `build/tomokv-pad.json` | `34c9edf342caa757a2653e149fdad6938d18c701e39d06fb7ff6d4e4f607729a` |
| `build/wbrule-mgetfix-policy-proofs.json` | `2d2c1e0c319b6b3dadd2ee97a6bd8f6c096a1cb79a33726b06b8e7a3219a8d6c` |
| `build/wbrule-mgetfix-phase-proofs.json` | `cc43aaf70eed1c3be0477cf360830943acc2115754c96cb01f781bbcae13a455` |
| `build/wbrule-mgetfix-stages-proofs.json` | `128fe6b342070a52658fd1325b57456d0195047285b8ce91710fab41b23b1747` |
| `build/wbrule-build-mode-guard.log` | `4cc8c827c9e6da217b30c9ba325f32883d491ab699f74c68cb452ce7f5568fca` |
| `build/wbrule-mgetfix-build-final.log` | `50b22a181e14e06ef0cfd0e8d63fc08d0a28486775eb17ae82c1fec772c1de0a` |

`git diff 3e734cf2e --stat` (including this report):

```text
 MEASURE-REQUEST-wbrule.md     | 376 ++++++++++++++++++++++++++++++++++++++++++
 Makefile                      |  27 +++
 src/core/genthread_pipeline.h |   1 -
 src/core/io_loop.h            |  98 +++++------
 src/core/reorder.cc           |  91 +++++-----
 src/core/wb_rule.h            | 130 +++++++++++++++
 tests/gate.sh                 |  31 +++-
 tests/wb_rule_cells.txt       |  12 ++
 tests/wb_rule_checks.py       | 121 ++++++++++++++
 tests/wb_rule_phase_unit.cc   | 345 ++++++++++++++++++++++++++++++++++++++
 tests/wb_rule_unit.cc         | 192 +++++++++++++++++++++
 tools/wb_rule_artifacts.py    | 172 +++++++++++++++++++
 12 files changed, 1497 insertions(+), 99 deletions(-)
```
