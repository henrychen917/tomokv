wbhybrid3: production policy 1 is the measured S=16, D=3 bounded completion rule.
Implementation and offline proofs are complete. Production merit, live boot/gate,
and landing remain MAINLINE work; no performance verdict is claimed for this build.

The first read on resume of `/home/user/Projects/WBHYBRID3-CHOSEN-D` returned
**`3`**, selecting **`hyb16-d3`**. Original launch HEAD was
`fce93655edafdb9c656c0d6633cd5f958deb016c`; merge `37654babe` imported
`origin/cpp` at `11b2cbcff`. Resume HEAD was `06af3506b`. That committed rule and
its documentation were reviewed and retained without amendment. Cleanup is
`7b1b31dd4`; the instruction/layout proof ledger is `c9f2ca00a`.

The wblandfix prerequisite passes: both forbidden pin strings have count **0**.
`tests/wbland_checks.py::source()` is unchanged from the merged mainline; its
function-text SHA-256 is
`6518dba98b371b1b50f2db80413d40bf6e47c026ce0a88833449a0989af0a841`.
Only the runner's witness registration and expected assertion name changed.

All builds and serverless checks used `taskset -c 112-127`. No server, benchmark,
load generator, gate, or push was run. An overlapping make invocation was stopped;
incomplete object outputs were then rebuilt before the successful checks below.

**Rule committed for landing.** The actual constants and `defer()` body from
`src/core/wb_rule.h` are:

```cpp
// MEASURED S=16, not derived from a batch size or reply size. Constants ledger
// addendum 12, S=16 KEEP (2026-10-02); PLAN-SERIAL 2026-10-01 16:54 and
// 2026-10-02 06:54: p8 saturation, p8@512K attainment, floor-0.4 bursts.
// See MEASURE-REQUEST-wbhybrid.md: no honest derivation from existing sizings.
inline constexpr unsigned kSmallPipe = 16;
// MEASURED D=3. Constants ledger addendum 12, D=3 DERIVE-BY-MEASUREMENT
// (2026-10-02); PLAN-SERIAL 06:54 D-curve row 3: p8 GET/SET/rl-SET
// +9.4/+10.4/+6.6%, with floor-0.4 p99/p999 inside the same-binary band.
inline constexpr unsigned kCompleteVisits = 3;
// Dimensionless POLICY fraction, not a byte/count/time bound. Competition record
// section 39 (2026-09-23/24), w4-c12: parse 32 / EX 32 / composite 1/2.
inline constexpr std::ratio<1, 2> kPolicyFraction{};

template <class Connection>
inline size_t staged_bytes(Connection& c) {
    return c.send_inflight() ? c.fill_buf().size() : c.buffered_output_bytes();
}

template <class Operation>
inline size_t code_bytes(const Operation& op) {
    switch (static_cast<ReplyCode>(op.reply_code_)) {
    case ReplyCode::Ok: case ReplyCode::Nil: case ReplyCode::NullArray: return 5;
    case ReplyCode::Pong: return 7;
    case ReplyCode::EmptyStr: return 6;
    case ReplyCode::NullResp3: return 3;
    case ReplyCode::True: case ReplyCode::False: return 4;
    case ReplyCode::Int: {
        int64_t v = op.reply_ival_;
        size_t n = 4; // colon, one digit, CRLF
        if (v < 0) { ++n; v = -v; }
        while (v >= 10) { v /= 10; ++n; }
        return n;
    }
    default: return 0;
    }
}

template <class Operation>
inline size_t reply_bytes(const Operation& op) {
    // Caller has acquired Done. Never read reply lengths from an executing op.
    // Negative zc_shard encodes a retire hook/state, not a borrowed value. Its
    // eventual output is unknown here: do not count zc_len as payload in that case.
    return op.reply.size() + (op.reply_code_ ? code_bytes(op) : op.direct_len) +
           (op.zc_ptr && op.zc_shard >= 0 ? size_t(op.zc_len) + 2 : 0);
}

template <class Connection>
inline bool defer(Connection& c, int policy = 1) {
    if (policy == 0) return false; // LATENCY: every ready head on every captured pass
    auto& rob = c.rob();
    const unsigned n = rob.in_flight();
    if (n <= 1) return false; // staged-only, pubsub, and p1 use ordinary serve
    size_t bytes = staged_bytes(c);
    if (bytes >= kWbufInline) return false;
    const auto head = rob.flush_id();
    // Keep this per-visit predicate off the encoder's register set. A live
    // register here spills once per integer reply; one stack byte keeps all
    // additional work at the visit boundary (locked by code-costs receipts).
    const volatile bool complete = n <= kSmallPipe && c.wb_deferrals() < kCompleteVisits;
    const unsigned threshold = complete ? n : (n * kPolicyFraction.num + kPolicyFraction.den - 1) / kPolicyFraction.den;
    unsigned prefix = 0;
    // Both counters belong to IO, but Done can have holes. Neither head/tail nor
    // the threshold slot alone proves a contiguous prefix. At most ROB slots,
    // with early exit once either threshold is satisfied; retirement stays in WB.
    while (prefix < threshold) {
        const auto& op = rob.at(head + prefix);
        if (op.state.load(std::memory_order_acquire) != OpState::Done) break;
        // Separate measured candidate: assembly stays in ordinary WB, in ROB order.
        // A Done scatter's byte size is unknown here; do not traverse its sub-ops.
        if (op.zc_ptr && op.zc_shard == Op::kScatterStateMarker) return false;
        bytes += reply_bytes(op);
        if (bytes >= kWbufInline) return false;
        ++prefix;
    }
    if (prefix >= threshold) return false;
    // One byte update per deferred visit, never per operation. The predicate
    // caps the count at D: a half-rule deferral adds zero, so it cannot wrap.
    c.wb_deferrals() += complete;
    return true;
}
```

There is no S/D knob, auto selector, machine constant, allocation, reader retry,
or new per-operation synchronization. Policy 0, the n<=1 bypass, 512-byte clause,
MGET scatter exit, acquire-before-reply-field reads, FIFO rotation/lifetime pin,
and one visit per captured entry retain the landed behavior. The counter is the
existing study's one IO-owned byte at Client offset 72, before ROB offset 128.
Only a completion deferral increments it; half-rule deferrals add zero. It
saturates at 3. Both Phase2 removal paths reset it before clearing `serve_pending`,
including dead removals; closing connections still drain.

`docs/CONFIGURATION.md` and `tomokv.conf` describe both constants, their measured
basis, the visit bound, and resets. `INFO WRITEBACK` still contains only
`wb_policy`; the existing exact-output witness passes for policies 0 and 1 in
both database namespaces. Configuration still accepts only boot policies 0/1.

**Measured constants and deciding evidence.** These are measurements, not a
derivation from existing batch, reply, cache, ROB, or machine sizes. See
`MEASURE-REQUEST-wbhybrid.md`, “no honest derivation from the proposed existing
sizings.” The constants ledger addendum 12, dated 2026-10-02 and recorded by
PLAN-SERIAL's 07:40 entry, names `S=16 KEEP` and `D=3 DERIVE-BY-MEASUREMENT`.
The source comments cite those rows, dates and deciding cells.

| Constant | Ledger/decision | Deciding cells |
| --- | --- | --- |
| `kSmallPipe = 16` | Addendum 12, `S=16 KEEP`; PLAN-SERIAL 2026-10-01 16:54 and 2026-10-02 06:54 | p8 GET/SET/read-local SET saturation, p8@512K attainment, floor-0.4 burst distributions |
| `kCompleteVisits = 3` | Addendum 12, `D=3 DERIVE-BY-MEASUREMENT`; PLAN-SERIAL 2026-10-02 06:54 D-curve row 3 | Largest consistent mean p8 saturation gain among bounds that keep floored-burst tails in band; D4 ties within scatter, so D3 |

The owner's recorded D3 PRE-half versus POST-study evidence is below. These are
historical mainline measurements, not measurements performed by this lane or
claims about the newly built production executable.

| Deciding cell | D3 versus half-rule REF |
| --- | --- |
| p8 GET / SET / read-local SET saturation | +9.4% / +10.4% / +6.6%; mean +8.8% |
| Other generic saturation cells | All within the mainline instrument's class bands |
| Low load p8@512K, share within 0.2 ms | +4.1 percentage points against that session's REF |
| Low load p32@256K, share within 0.2 ms | -2.2 points; mainline classified as parity within session scatter; no finite-D recovery of the unbounded arm's p32 gain is claimed |
| Floor 0.4, reorder off: p50 / p99 / p99.9 | -17.3% / -2.2% / +3.6% |
| Floor 0.4, reorder on: p50 / p99 / p99.9 | -15.2% / -3.2% / +0.8% |
| D3 wire results | Not measured in the selection ledger; final production NIC-AB/NIC-LAT is requested below |

D2's earlier wire result supports the mechanism but is not a D3 measurement.
The earlier D2 low-load gains also used a different session's REF. The selection
ledger's burst-tail band was about +/-7%; mainline must use contemporary nulls
when judging the final binary.

**Removed scaffolding.** Removed all three arm builders:
`tools/wbhybrid_artifacts.py`, `tools/wbhybrid2_artifacts.py`, and
`tools/wbhybrid2b_artifacts.py`. Removed the selector-driven
`tests/wbhybrid_unit.cc` and `tests/wbhybrid2_paths.inc`; converted
`wbhybrid2_unit.cc` and `wbhybrid2_codes.cc` into production-only
`wb_rule_completion_unit.cc` and `wb_rule_codes.cc`. No `WBHYBRID*` selector
or hyb/PAD build recipe remains. There were already no `build/wbhybrid*`
Makefile targets in the resumed tree. The Makefile now attaches the completion
witnesses and six strict mutation controls to the existing `wbland-units` target.

The ignored generated `build/wbhybrid2/` and `build/wbhybrid2b/` trees, their
source patches, and the nonchosen top-level hyb/PAD arm files were removed after
preserving audited comparison inputs. `build/tomokv-hyb16-d3` remains available
for mainline's null. Frozen REF/D2/D3 witness binaries and the original D3 image
also remain under `build/wbhybrid3/inputs/`, with a SHA manifest. Historical
measurement logs, committed study evidence ledgers, and the unchanged 21-cell
workload file remain as provenance; they do not build or select a policy.
`tools/wb_rule_receipts.py` only audits the production rule against frozen
witnesses and never builds or patches a study arm.

**Exact witness expectation changes.** With a contiguous Done prefix `p`, no
512-byte/scatter exit, and policy 1, defer iff `n > 1 && p < threshold`.
This table specifies every prefix at n=1..64 and counts 0..3, without tolerance:

| n | Before: half, any count | After: count 0 | After: count 1 | After: count 2 | After: count 3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | bypass | bypass | bypass | bypass | bypass |
| 2..16 | ceil(n/2) | n | n | n | ceil(n/2) |
| 17..64 | ceil(n/2) | ceil(n/2) | ceil(n/2) | ceil(n/2) | ceil(n/2) |

For example n=2,3,8,16,17,32,64 had thresholds 1,2,4,8,9,16,32. At counts
0..2 they now have thresholds 2,3,8,16,9,16,32; at count 3 they retain the
old thresholds. Thus exactly the short-pipe prefixes `ceil(n/2) <= p < n`
change from serve to defer before the visit bound. Policy 0, n=0/1, full
prefixes, the 512-byte exits and acquired scatter exits keep their outcomes.

| Existing witness | Before | After and reason |
| --- | --- | --- |
| `wb_rule_unit::fraction`, also included by `wbland_clause_unit` | Every n/prefix checks half | Same exhaustive prefixes plus counts 0..3; checks the threshold table above and retains odd rounding/ROB wrap coverage |
| `wb_rule_unit::markers` | Four Done slots always open p8 | At count 0, non-scatter retire markers wait for completion; at count 3 four Done slots open half. Scatter still exits immediately |
| `wbland_unit::endpoints` | Policy 1 exact half; policy 0 unconditional serve | Policy 1 exact bounded hybrid at every n/prefix/count; policy 0 unchanged and verified not to touch the counter |
| `wb_rule_phase_unit::split_policy` | Half boundaries at depths 2,3,4,7,8,31,32,63,64 | New threshold for counts 0..3; also adds n=16/17 to catch the exact S boundary in coarse/natural/shallow schedules |
| Physical `wbland_policies` | 96 connections at n=32, policy 0/1, one pass | Retains that n=32 half expectation; adds n=2,4,5,8,16,17,64 and four captured visits. Checks exact retirement, relative FIFO order, one visit, counter saturation, reset before the same connection's next p8 pipe, and dead/closing removal |
| Former study completion table | S/D/counter supplied by `WBHYBRID*` macros, including alternative arms | Production constants only, locked at 16/3; counts exactly 0..3. Also checks n=0 and ROB starts 0/61. No configurable oracle or arm selection remains |

Assertion text changes are `ceil half for every n=1..64 and prefix` to
`bounded hybrid for every n=1..64, prefix and count`, and
`policy one is exact landed half` to `policy one is exact bounded hybrid`.
The former p8 marker assertion is split into before-bound and at-bound checks.
The completion fixture reports `wb-completion` instead of `wbhybrid2` internally.
**No gate row label changed.**

The completion table visits **17,160 states per namespace**: n=0..64, every Done
prefix, starts 0/61, and counts 0..3; each state checks policies 0 and 1. Exit
witnesses retain 511/512 staged and Done bytes, exclusion of submitted bytes,
Done versus Issued scatter, and holes. Lifetime witnesses exercise both real
Phase2 removal paths, rotation/pinning and 1,024 unfinished-head visits.

| New negative control | Required failure, both namespaces |
| --- | --- |
| S-1 (`n < 16`) | Decision table, n=16, Done=15, count=0 |
| S+1 (`n <= 17`) | Decision table, n=17, Done=16, count=0 |
| D-1 (`count < 2`) | Decision table, n=2, Done=1, count=2 |
| D+1 (`count <= 3`) | Decision table, n=2, Done=1, count=3 |
| Delete gather reset | `served connection completes again next pipe` |
| Delete serve reset | `served connection completes again next pipe` |

Each negative must exit **1 with its designated assertion**. A crash, timeout,
different assertion or passing test does not qualify. The existing floor/whole,
byte, scatter, acquire/read-order, FIFO pin/rotation/capture and schedule controls
still pass their strict negative expectations.

| Serverless checker group | Positive | Required negative | Total passed |
| --- | ---: | ---: | ---: |
| wb-rule policy | 18 | 19 | 37 |
| wb-rule phase | 24 | 8 | 32 |
| wb-rule stages | 10 | 2 | 12 |
| wb-rule split-phase | 24 | 11 | 35 |
| wb-rule split-overlap | 44 | 20 | 64 |
| wbland clauses | 32 | 40 | 72 |
| wbland paths | 20 | 7 | 27 |
| Total | 172 | 107 | **279** |

These are witness invocations, not gate rows. `tests/gate.sh` is unchanged:
**0 added, 0 retired, 0 renamed rows; EXPECT_QUICK=446 and EXPECT_FULL=463 remain
unchanged.** The existing wbland row labels are constructed at line 1295 and
collected at line 2747, before the quick-tier exit at line 2876. No count change
is requested.

**Proof (a): instruction-receipt alternative.** Whole `.text` identity does not
hold: production has 7,553,681 bytes versus the frozen D3 study's 7,564,609,
a difference of -10,928 bytes. The frozen study predates the merged mainline
cleanups. These differences cannot honestly be called only removed scaffold
sections. The permitted fallback is therefore used: freshly compiled production
`defer()` receipts equal the chosen study's on all **22 standard fixtures x 4
counts x 2 namespaces = 176 comparisons**. Ten additional half-boundary/scatter
fixtures and real reply encodings bring the equality proof to **328 comparisons**.
There are **1,312 raw receipts** across REF, D2, D3 and production. Every receipt
counts one wrapper/defer call, excludes setup, and has zero library instructions.
No cycle, rate, latency or PMU measurement was performed.

All ELF sections with differing file bytes are:
`.data`, `.data.rel.ro`, `.debug_abbrev`, `.debug_aranges`, `.debug_info`,
`.debug_line`, `.debug_line_str`, `.debug_loclists`, `.debug_rnglists`,
`.debug_str`, `.dynamic`, `.dynsym`, `.eh_frame`, `.eh_frame_hdr`, `.fini_array`,
`.gcc_except_table`, `.gnu.hash`, `.gnu.version`, `.got`, `.init`, `.init_array`,
`.note.gnu.build-id`, `.plt`, `.plt.got`, `.plt.sec`, `.rela.dyn`, `.rela.plt`,
`.rodata`, `.strtab`, `.symtab`, `.text`.
Sections with geometry-only differences are `.bss`, `.comment`, `.dynstr`,
`.fini`, `.gnu.version_r`, `.shstrtab`, `.tbss`, `.tdata`; NOBITS sections have
no file payload. No section was added or removed. All remaining sections match.
The committed ledger lists changed fields, sizes, offsets, addresses and hashes.

Standard fixtures below start at count 0; both namespaces have identical counts.
The ledger contains every count 0..3, including D2's earlier fallback at count 2.

| Fixture n / Done / staged / policy / scatter | REF | study D2 | study D3 | production |
| --- | ---: | ---: | ---: | ---: |
| 1 / 0 / 0 / 1 / 0 | 12 | 12 | 12 | 12 |
| 64 / 1 / 0 / 0 / 0 | 7 | 7 | 7 | 7 |
| 64 / 0 / 512 / 1 / 0 | 34 | 34 | 34 | 34 |
| 8 / 0 / 0 / 1 / 0 | 66 | 74 | 74 | 74 |
| 8 / 1 / 0 / 1 / 0 | 92 | 100 | 100 | 100 |
| 8 / 8 / 0 / 1 / 0 | 160 | 267 | 267 | 267 |
| 16 / 0 / 0 / 1 / 0 | 66 | 74 | 74 | 74 |
| 16 / 1 / 0 / 1 / 0 | 92 | 100 | 100 | 100 |
| 16 / 16 / 0 / 1 / 0 | 264 | 475 | 475 | 475 |
| 17 / 0 / 0 / 1 / 0 | 66 | 75 | 75 | 75 |
| 17 / 1 / 0 / 1 / 0 | 92 | 101 | 101 | 101 |
| 17 / 17 / 0 / 1 / 0 | 290 | 294 | 294 | 294 |
| 32 / 0 / 0 / 1 / 0 | 66 | 75 | 75 | 75 |
| 32 / 1 / 0 / 1 / 0 | 92 | 101 | 101 | 101 |
| 32 / 32 / 0 / 1 / 0 | 472 | 476 | 476 | 476 |
| 33 / 0 / 0 / 1 / 0 | 66 | 75 | 75 | 75 |
| 33 / 1 / 0 / 1 / 0 | 92 | 101 | 101 | 101 |
| 33 / 33 / 0 / 1 / 0 | 498 | 502 | 502 | 502 |
| 64 / 0 / 0 / 1 / 0 | 66 | 75 | 75 | 75 |
| 64 / 1 / 0 / 1 / 0 | 92 | 101 | 101 | 101 |
| 64 / 64 / 0 / 1 / 0 | 888 | 892 | 892 | 892 |
| 64 / 1 / 0 / 1 / 1 | 70 | 76 | 76 | 76 |

| n=8, Done=4, no bytes/scatter | REF | D2 | D3 | Production |
| --- | ---: | ---: | ---: | ---: |
| count 0 or 1 | 160 | 178 | 178 | 178 |
| count 2 | 160 | 166 | 178 | 178 |
| count 3 | 160 | 166 | 166 | 166 |

For the ordinary n=17/32/33/64, Done=1 visit, production remains **101 versus
REF's 92 (+9 instructions per captured connection visit)**, exactly the accepted
D2/D3 cost. Policy-0, n<=1 and staged-512 bypasses have zero delta. Whole short
prefixes intentionally scan more replies; their higher counts are included
without subtraction. Actual OK/GET-71B/integer-12345 encodings also equal D3:
one Done costs 104/100/141 versus REF 96/92/136; two Done cost 134/126/208 versus
126/118/206. The volatile predicate preserves the study's once-per-visit
bookkeeping instead of adding a spill for each integer reply.

**Proof (b): build and layout.** A forced full `taskset -c 112-127 make -B -j16`
successfully compiled and linked all 84 production objects. The requested
`taskset -c 112-127 make -j16` then passed with no work pending.
The phase witnesses instantiate fused/split paths in both database variants,
with `databases=1` for `tomo_db0` and `databases=4` for `tomo`. Both modes'
runtime entry code is present in the linked binary. This is compile/serverless
proof, not a claim that a live server was booted.

| Compile / serverless configuration | Op | Client | ThreadCtx | Shard | FlatStore | Rob<64> | AtomicEntry | Config |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1s, databases=1 | 336 | 1984 | 1408 | 1440 | 944 | 192 | 144 | 624 |
| 2s, databases=1 | 336 | 1984 | 1408 | 1440 | 944 | 192 | 144 | 624 |
| 1s, databases=4 | 336 | 1984 | 1408 | 1440 | 944 | 192 | 144 | 624 |
| 2s, databases=4 | 336 | 1984 | 1408 | 1440 | 944 | 192 | 144 | 624 |

The native static assertions and offline GDB DWARF audit agree. All **42 Client
member offsets and widths** match the frozen chosen study in both namespaces;
`wb_deferrals_` is `[72,1]`, ROB is `[128,192]`. TLS remains `.tdata=112`,
`.tbss=480`. GDB only read types and never started the executable.

**Proof (c): binaries delivered.** Use SHA-256, not the frozen study's build ID
or D constant in DWARF: its delivered D3 image retains D2 debug metadata, as
documented by wbhybrid2b. The preserved instruction witnesses are native D3 builds.

| Binary | SHA-256 |
| --- | --- |
| `build/tomokv` and frozen copy `build/tomokv-wbhybrid3-production` | `565d9f1af0e3065afe2a24de5d3eaecefa1960563695ca61a6cea493f19d608f` |
| Chosen `build/tomokv-hyb16-d3`, also `build/wbhybrid3/inputs/tomokv-study-d3` | `3dbda9de78305fe8f005c0fc50d19be34d2b2d1bd1d423d999a1d15b98f9a77d` |
| Historical half REF `build/tomokv-wbhybrid2-ref`, also `build/wbhybrid3/inputs/tomokv-ref` | `70f51c094e2971219ea53fd056caa1d1fd7736045cbb9a81dea909fcbefb3e34` |

The historical half REF is the October 1 `90ba908d3` artifact (source equivalent
to `5b3d9c429`). Mainline should also retain the identity of its current REF;
do not silently substitute one reference generation for the other.

**MAINLINE measurement request.** Run two separately attributed comparisons:
production versus the preserved chosen D3 study (same rule, expected null), and
production versus mainline's half-rule REF (preserve the measured gain and no
losing class). Use the gate's own qualified ABBA instrument, matched offered
loads, pins and contemporary same-binary null. Policy is **1** for every arm.
No PAD arm is requested or delivered by this cleanup; the frozen study's prior
PAD-A evidence remains historical provenance.

The unchanged `tests/wbhybrid_cells.txt` parses as exactly **21 cells** with
`abbagate.read_cells`: 14 generic + 5 reorder-on + 2 at 4096 connections.

| Set | Exact cell IDs |
| --- | --- |
| Generic 14 | h05, h06, p8g, p8s, d1g_l0, d1s_l0, m8g_l0, v1g_l0, d128g_l0, d32g_l1, d8s_l1, d32s_l1, x9_32_l1, x9_32_l0 |
| Reorder-on 5 | h05r1, h06r1, p8gr1, p8sr1, x9_32_l0r1 |
| 4096-connection 2 | c4kg, c4ks (GET/SET p32) |

Keep the gate instrument's cell-specific rate/latency scores. Report PRE/POST
rate at matched offered load, cycles/op, IPC, instructions/op, commands/send,
and latency distributions. The standard prior geometry was 32 real server
cores (0-31), loaders 32-111, no SMT; mainline schedules the box and supplies
qualified placement. Those are mainline measurement instructions, not lane
execution permissions.

The deciding result for production versus D3 is parity within the contemporary
same-binary band in every cell. Against REF, retain p8 GET/SET/read-local SET
gains and require no losing class, including p1, p32, MGET, read-local, reorder
and 4096 connections. Instruction-count equality explains the rule; it does
not establish whole-program rate/latency parity across the merged source bases.

As required by the D3 selection ledger, also run the 25GbE two-netns NIC-AB
and NIC-LAT landing sweep versus REF. Preserve the prior wire cells, including
p8 GET/SET saturation and p8 p50/p99 at 60%/80% offered load, and contemporary
nulls. Require no loss beyond the class band; D2's historical wire numbers are
not a substitute. Then run **`tests/gate.sh iteration`**, verify both modes and
database configurations, and land only after mainline's merit/gate decision.
Append results as `MEASURE-RESULT`; they are pending here.

**Offline reproduction and receipts.** The committed machine ledger is
`tests/wb_rule_completion_evidence.json`. Raw logs/JSON, binary preservation
manifest, section audit and GDB output are under `build/wbhybrid3/`; the seven
strict witness receipts are `build/{wb-rule-*,wbland-*}-proofs.json`.

```sh
taskset -c 112-127 make -j16
taskset -c 112-127 make -j16 build/wbland-units
taskset -c 112-127 python3 tests/wbland_checks.py check clauses
taskset -c 112-127 python3 tests/wbland_checks.py check paths
for group in policy phase stages split-phase split-overlap; do
    taskset -c 112-127 python3 tests/wb_rule_checks.py check "$group" || exit
done
taskset -c 112-127 python3 tools/wb_rule_receipts.py identity
taskset -c 112-127 python3 tools/wb_rule_receipts.py costs
sha256sum build/tomokv
```

The receipt tool requires the preserved manifest-checked fixture binaries; it
does not recreate the retired study scaffolding if those inputs are absent.

**Requested launch diff.** `git diff fce93655edafdb9c656c0d6633cd5f958deb016c --stat`
includes the mandatory origin/cpp merge as well as this lane. The lane-only
change can be reviewed with `git diff 37654babe --stat`.

```text
 MEASURE-REQUEST-cleanup-boot.md                    |   464 +
 MEASURE-REQUEST-cleanup-flipreport.md              |   378 +
 MEASURE-REQUEST-cleanup-iotemplates.md             |   246 +
 MEASURE-REQUEST-cleanup-probeadapter.md            |   193 +
 MEASURE-REQUEST-cleanup-ringmarker.md              |   412 +
 MEASURE-REQUEST-cleanup-tlsserve.md                |   395 +
 MEASURE-REQUEST-nullpublish.md                     |   339 +
 MEASURE-REQUEST-nullpublish2.md                    |   238 +
 MEASURE-REQUEST-nullpublish3.md                    |   328 +
 MEASURE-REQUEST-nullrefresh.md                     |   242 +
 MEASURE-REQUEST-nullrefresh2.md                    |   163 +
 MEASURE-REQUEST-nullrefresh3.md                    |   203 +
 MEASURE-REQUEST-nullrefresh4.md                    |   206 +
 MEASURE-REQUEST-nullrefresh5.md                    |   224 +
 MEASURE-REQUEST-wbhybrid3.md                       |   503 +
 MEASURE-REQUEST-wblandfix.md                       |   209 +
 Makefile                                           |    28 +-
 docs/CONFIGURATION.md                              |    23 +-
 src/cmd/multi.h                                    |     2 -
 src/cmd/multi.inc                                  |     8 -
 src/core/boot_support.h                            |    86 +
 src/core/flipctl.cc                                |     1 -
 src/core/flipctl.h                                 |     2 +-
 src/core/genthread.cc                              |    31 +-
 src/core/io_loop.h                                 |   123 +-
 src/core/reorder.cc                                |   127 +-
 src/core/rl2s.cc                                   |    33 +-
 src/core/wb_rule.h                                 |    22 +-
 src/main.cc                                        |    48 +-
 src/net/conn.h                                     |    10 +
 src/net/uring.h                                    |     5 -
 src/net/wb.h                                       |   228 +-
 src/persist/aof.cc                                 |     2 -
 src/snapshot/snapshot.cc                           |     2 -
 src/store/flatstore.h                              |    84 +-
 tests/_abba_test_fixtures.py                       |    17 +
 tests/_nullrefresh_test.py                         |  1137 +
 tests/abba_binaries.py                             |   469 +
 tests/abba_ceiling.py                              |    79 +
 tests/abba_evidence.py                             |   226 +-
 tests/abba_instrument.py                           |    94 +-
 tests/abba_null_sampling.py                        |    81 +
 tests/abba_reorder_control.py                      |   240 +
 tests/abba_saturation.py                           |    11 +
 tests/abbagate.py                                  |   238 +-
 tests/boot_failures.py                             |   425 +
 tests/boot_support_checks.inc                      |   181 +
 tests/config_parser_test.cc                        |     2 +
 tests/core_concurrency_unit.cc                     |     5 +-
 tests/fixtures/nullpublish-campaign6-compact.json  |   383 +
 tests/fixtures/nullrefresh-ledger-labels.json      |   482 +
 tests/flipctl_unit.cc                              |     5 +
 tests/flipreport_checks.inc                        |    87 +
 tests/gate.sh                                      |    36 +-
 tests/gate_ledger_fixture.py                       |   306 +
 tests/gate_measurements.json                       | 27782 ++++++++++++++++++-
 tests/gate_measurements.py                         |   107 +-
 tests/gate_receipt.py                              |   441 +-
 tests/gates_test.py                                |    89 +-
 tests/load_calibration.py                          |   117 +-
 tests/multidb_boundary_unit.cc                     |     2 +-
 tests/multidb_db0_unit.cc                          |     5 +-
 tests/multidb_unit.cc                              |    15 +-
 tests/netcmd_unit.cc                               |     2 +
 tests/nullpublish_refreeze_test.py                 |   153 +
 tests/probeadapter_checks.h                        |   160 +
 tests/r7shadow_sync.py                             |    37 +-
 tests/rehash_waits_unit.cc                         |     6 +-
 tests/reorder_engagement_unit.cc                   |    92 +-
 tests/reorder_noop.py                              |    17 +
 tests/tlsserve_checks.inc                          |   312 +
 tests/wb_rule_checks.py                            |    10 +-
 tests/{wbhybrid2_codes.cc => wb_rule_codes.cc}     |     8 +-
 tests/wb_rule_completion_evidence.json             |  3384 +++
 ...bhybrid2_unit.cc => wb_rule_completion_unit.cc} |    37 +-
 tests/wb_rule_phase_unit.cc                        |    83 +-
 tests/wb_rule_unit.cc                              |    20 +-
 tests/wbhybrid2_paths.inc                          |    86 -
 tests/wbhybrid_unit.cc                             |   103 -
 tests/wbland_checks.py                             |   297 +-
 tests/wbland_evidence.json                         |   169 +
 tests/wbland_unit.cc                               |    11 +-
 tomokv.conf                                        |    10 +-
 tools/boot_support_artifacts.py                    |   262 +
 tools/boot_support_controls.py                     |    84 +
 tools/flipreport_proof.py                          |   331 +
 tools/iotemplates_proof.py                         |   503 +
 tools/nullpublish_refreeze.py                      |   197 +
 tools/probeadapter_proof.py                        |   311 +
 tools/ringmarker_proof.py                          |   225 +
 tools/tlsserve_proof.py                            |   384 +
 tools/wb_rule_receipts.py                          |   154 +
 tools/wbhybrid2_artifacts.py                       |   556 -
 tools/wbhybrid2b_artifacts.py                      |   378 -
 tools/wbhybrid_artifacts.py                        |   441 -
 95 files changed, 43938 insertions(+), 3555 deletions(-)
```
