wbhybrid2b — extend the frozen S=16 visit-bound curve to D=3 and D=4.
Performance verdict: PENDING MAINLINE.

The new arms and their exact-layout PAD A twins are delivered below. The literal
ordinary-path instruction requirement, +/-1 versus REF, is **not satisfied** by
the inherited D2 template. The receipts disclose that cost; D3/D4 preserve D2's
instruction counts on equivalent branches. Removing the inherited cost would
change more than the requested D immediates, so this study preserves the template.

Launch HEAD was `ae6b78bf8`. First, fetched and merged `origin/cpp` at
`2a9e48403`, producing merge commit `92bdd252e`. The merge imports the unrelated
read-reply cleanup in `src/core/ex_loop.h`. Production source and Makefile match
that mainline revision; this lane adds no production source changes. The frozen
`build/tomokv` remains byte-identical to the landed half-rule REF measured on
October 1 (`90ba908d3`, server source equivalent to `5b3d9c429`). It was neither
rebuilt nor replaced with a study arm.

All builds and offline checks ran under `taskset -c 112-127`. No server,
benchmark, load generator, gate, PMU experiment, or push was run.

**Construction and byte identity.** `tools/wbhybrid2b_artifacts.py` copies the
frozen `build/wbhybrid2/hyb16-d2` source, changes only its D constant, and uses
the original reference compile commands, flags, libraries and link order.
Each native build recompiles the complete 40-object rule include closure and
copies 44 other D2 objects with whole-file SHA checks. The original source name
is `kDeferVisits`; it is the `kCompleteVisits` D in the task. Keeping that name
preserves the original template exactly.

The native builds are retained at
`build/wbhybrid2b/hyb16-d{3,4}/build/tomokv`. The audit independently compared every
allocated ELF section, including `.text`, data, TLS, unwind tables and section
geometry, against frozen D2 with only the two decoded D immediates changed,
excluding only the linker build-ID note. All those comparisons pass. The
delivered measurement files retain D2's non-runtime debug metadata and build ID
so that **only** those two bytes differ across the entire ELF. The native builds retain
their correct source paths and D constants for debugging. Use SHA-256 to identify
measurement arms; the retained build ID and D2 DWARF constant do not identify D.

The final file comparison restores only the declared bytes and then compares
the entire ELF with D2, including file length. Each candidate differs at exactly
two bytes; each PAD differs from its candidate at exactly two further bytes.

| Compared files | Namespace | Instruction address | ELF file offset (decimal) | .text-relative offset | Byte change |
| --- | --- | --- | --- | --- | --- |
| hyb16-d3 vs D2 | tomo_db0 | `0xa61d0` | `0xa61d3` (680403) | `0x88b73` | `01 -> 02` |
| hyb16-d3 vs D2 | tomo | `0x421310` | `0x421313` (4330259) | `0x403cb3` | `01 -> 02` |
| hyb16-d4 vs D2 | tomo_db0 | `0xa61d0` | `0xa61d3` (680403) | `0x88b73` | `01 -> 03` |
| hyb16-d4 vs D2 | tomo | `0x421310` | `0x421313` (4330259) | `0x403cb3` | `01 -> 03` |
| tomokv-hyb16-d3-pad vs arm | tomo_db0 | `0xa6037` | `0xa603a` (679994) | `0x889da` | `10 -> 01` |
| tomokv-hyb16-d3-pad vs arm | tomo | `0x421177` | `0x42117a` (4329850) | `0x403b1a` | `10 -> 01` |
| tomokv-hyb16-d4-pad vs arm | tomo_db0 | `0xa6037` | `0xa603a` (679994) | `0x889da` | `10 -> 01` |
| tomokv-hyb16-d4-pad vs arm | tomo | `0x421177` | `0x42117a` (4329850) | `0x403b1a` | `10 -> 01` |

The D instruction is `cmpb $(D-1),0x48(%rdi)` followed by unsigned `setbe`.
Thus D3 selects completion for counts 0..2 and D4 for counts 0..3. Its Client
operand remains byte 72. The PAD selector is the same decoded `cmp $0x10,%r10d`
as D1/D2, patched to `0x01`. Since n<=1 has already returned, every remaining
PAD visit selects half. PADs are **kind A, behaviour twins**: PRE half-rule
behaviour with the candidate's exact text size/layout and counter/reset code.
Text size is unchanged from D2, so no inverse-control PAD B is needed.

**Arm table.** Paths below are relative to this worktree. All arms retain
`.tdata=112`, `.tbss=480`; each new arm has the same `.text` size as D2, which is
16 bytes larger than REF. D0 is the unbounded predecessor (D=infinity).

| Arm | .text bytes | SHA-256 |
| --- | ---: | --- |
| `build/tomokv-wbhybrid2-ref` | 7,564,593 | `70f51c094e2971219ea53fd056caa1d1fd7736045cbb9a81dea909fcbefb3e34` |
| `build/tomokv-hyb16-d0` | 7,564,433 | `649ee2e19105fcfd4565b972f08e6b07cbd90808a0f0080d4ab4f47af57cf67c` |
| `build/tomokv-hyb16-d1` | 7,564,609 | `18f4d74a9ee8a7be8cd258938387a54c48144a1c0b6be9c2e1953dd3b12c47f6` |
| `build/tomokv-hyb16-d1-pad` | 7,564,609 | `2ff77003403d7bca3c847f9f8b075f4a0d8ef62e39e3d255fa7984034687f2db` |
| `build/tomokv-hyb16-d2` | 7,564,609 | `e2c6860b1fdcc1bc68291d5f1ed46f1b8076c69c3687f9c8c8352642bcb637e5` |
| `build/tomokv-hyb16-d2-pad` | 7,564,609 | `d13a3586c3f020314c3ed6989a77cb339f1791f3e69e8404419df42ce1c40f1a` |
| `build/tomokv-hyb16-d3` | 7,564,609 | `3dbda9de78305fe8f005c0fc50d19be34d2b2d1bd1d423d999a1d15b98f9a77d` |
| `build/tomokv-hyb16-d3-pad` | 7,564,609 | `b18c3fefbf3d3e66dee38f2cb04bca3725e4f514f3a9457da724f253965907a6` |
| `build/tomokv-hyb16-d4` | 7,564,609 | `fd81176c632d8392a0e6a3e567ab99ef3195fa2c93ac95de94ad5361bf18d295` |
| `build/tomokv-hyb16-d4-pad` | 7,564,609 | `8b0290e3bdbf07d00d1fcac9029b096e0157dbf5d7c166ac75eee104fcf951eb` |

**Decision and lifetime witnesses.** The existing fixture's count sweep now
reaches `max(3,D+1)` instead of stopping at 3. This is necessary for D4's fallback
and late off-by-one control to be tested. Assertions are preserved; the stalled
head now also checks exact saturation after each of 1,024 consecutive visits.

| In-flight n / count c | D3 | D4 |
| --- | --- | --- |
| 0 or 1 / any c | ordinary serve | ordinary serve |
| 2..16 / c=0,1,2 | complete (threshold n) | complete (threshold n) |
| 2..16 / c=3 | half (ceil(n/2)) | complete (threshold n) |
| 2..16 / c>=4 | half (ceil(n/2)) | half (ceil(n/2)) |
| 17..64 / any c | half (ceil(n/2)) | half (ceil(n/2)) |

A successful completion deferral increments the counter once; a half deferral
adds zero. Starting from zero it saturates at D without wrapping. Both real
Phase2 removal paths, `gather()` and `serve()`, reset it immediately before
clearing `serve_pending`. Rotation preserves it; the next pipe starts fresh.
The unfinished head still requires the existing half-prefix, byte or scatter
exit. D bounds additional completion waiting in visits, not execution time.

The native Client DWARF audit passes in `tomo` and `tomo_db0`: all 42 member
offsets and widths match D2, `wb_deferrals_` remains `[72,1]`, ROB `[128,192]`,
and `sizeof(Client)=1984`. No object layout or lifetime mechanism changed.

| Offline check | Result |
| --- | --- |
| Decision table | D3: 21,450 cells per witness; D4: 25,740. n=0..64, every Done prefix, ROB starts 0/61, policies 0/1, counts through D+1; candidates and PADs, both namespaces. REF: 17,160 per namespace. 223,080 table cells total. |
| Exits | Staged/Done 511 and 512 bytes, submitted-send exclusion, Done/Issued scatter, and Done slots behind a head hole pass for both arms and PADs. |
| Lifetime | Real gather/serve, FIFO rotation, bypass and dead removal, reset before the same connection's next pipe, and 1,024 unfinished-head visits pass. |
| D-1 controls | Required decision-table failure at n=2, Done=1, count=2 for D3 and count=3 for D4, in both namespaces. |
| D+1 controls | Required decision-table failure at n=2, Done=1, count=3 for D3 and count=4 for D4, in both namespaces. |
| No-reset controls | Required `served connection completes again next pipe` failure in both Phase2 entry points for both arms/namespaces. |

Correctness outcomes: **56/56**, comprising 40 positive invocations and 16
required exit-1 failures. Crashes, timeouts or unrelated assertions do not count
as successful negative controls. Raw outputs and hashes are in
`build/wbhybrid2b/proofs.json`; the committed ledger is
`tests/wbhybrid2b_evidence.json`.

**Instruction receipts and the unmet REF requirement.** The standard 28
fixtures were rerun for REF, D0, D2, D3 and D4 in both namespaces, with counts
through `max(3,D+1)`: 1,288 receipts. Another 234 receipts cover actual OK, 71-byte
GET and integer-12345 replies at zero, one and two Done slots, before/at/after the
D boundary. Ptrace single-steps one wrapper/defer call; setup is excluded and
all counted instructions stay in the executable. These are instruction counts,
not cycles, latency or rate measurements.

| n / Done / staged bytes / policy / scatter / count | REF | D0 | D2 | D3 | D4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 / 0 / 0 / 1 / 0 / 0 | 12 | 12 | 12 | 12 | 12 |
| 64 / 1 / 0 / 0 / 0 / 0 | 7 | 7 | 7 | 7 | 7 |
| 64 / 0 / 512 / 1 / 0 / 0 | 34 | 34 | 34 | 34 | 34 |
| 8 / 0 / 0 / 1 / 0 / 0 | 66 | 65 | 74 | 74 | 74 |
| 8 / 1 / 0 / 1 / 0 / 0 | 92 | 91 | 100 | 100 | 100 |
| 8 / 4 / 0 / 1 / 0 / 0 | 160 | 169 | 178 | 178 | 178 |
| 8 / 4 / 0 / 1 / 0 / 2 | 160 | 169 | 166 | 178 | 178 |
| 8 / 4 / 0 / 1 / 0 / 3 | 160 | 169 | 166 | 166 | 178 |
| 8 / 8 / 0 / 1 / 0 / 0 | 160 | 263 | 267 | 267 | 267 |
| 16 / 16 / 0 / 1 / 0 / 0 | 264 | 471 | 475 | 475 | 475 |
| 17 / 1 / 0 / 1 / 0 / 0 | 92 | 93 | 101 | 101 | 101 |
| 32 / 1 / 0 / 1 / 0 / 0 | 92 | 93 | 101 | 101 | 101 |
| 64 / 1 / 0 / 1 / 0 / 0 | 92 | 93 | 101 | 101 | 101 |
| 8 / 1 / 0 / 1 / 1 / 0 | 70 | 69 | 75 | 75 | 75 |

D4 at count 4, n=8, Done=4 returns to 166 instructions (half); D3 at count
3 and D2 at count 2 also take 166. All table counts agree across namespaces.

| Encoding / Done / count=0 (n=8) | REF | D0 | D2 | D3 | D4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| OK / 1 | 96 | 95 | 104 | 104 | 104 |
| OK / 2 | 126 | 125 | 134 | 134 | 134 |
| GET, 71 bytes / 1 | 92 | 91 | 100 | 100 | 100 |
| GET, 71 bytes / 2 | 118 | 117 | 126 | 126 | 126 |
| integer 12345 / 1 | 136 | 132 | 141 | 141 | 141 |
| integer 12345 / 2 | 206 | 199 | 208 | 208 | 208 |

All **672** overlapping standard REF/D0/D2 receipts exactly reproduce the prior
ledger. D3/D4 equal D2 on every equivalent threshold branch; the only changes in
when the cost occurs follow the new D boundary. Policy-0, n<=1 and staged-512
bypasses have zero instruction delta versus REF. Additional Done replies cost
26 instructions for empty/GET, 30 for OK, and 67 for integer 12345 in D0/D2/D3/D4;
there is no new per-reply growth from D3/D4.

The requested +/-1 bar applies to the predecessor D0 selector, but **does not
hold for the counter-bearing D2 template or D3/D4**: an ordinary n=17/32/64,
Done=1 half-rule visit takes 101 instructions versus REF's 92 (+9); n=8,
Done=1, count=0 takes 100 versus 92 (+8). Across the standard ordinary/same-prefix
fixtures, the complete set of deltas is 0, +4, +5, +8, +9 and +11. These are full-call receipts, with no
counter bookkeeping subtracted. The exact-D-only condition and the literal
REF +/-1 condition cannot both be true on the supplied D2 artifact. The ledger
marks `ordinary_within_one_instruction_of_ref=false`. No production change or
performance claim is made to conceal that conflict.

**Mainline measurement request.** Measure the four new arms D3, PAD3, D4, PAD4
against the frozen REF above, retaining D2 as an in-session curve comparator.
Use policy 1 for every arm. Keep candidate-versus-REF, candidate-versus-own-PAD,
PAD-versus-REF and D3/D4-versus-D2 results separately. Historical D0/D1 results
are curve anchors, not substitutes for contemporaneous REF/null observations.

| Priority | Cells / repetitions | Deciding number |
| --- | --- | --- |
| 1. Saturated bursts | Floor 0.4, reorder 0 and 1; **8 samples per arm/state**, including each PAD and matched REF. Preserve the October 1 FLOOR-BURST waveform, seeds, population and geometry: 9:1 GET:BITCOUNT, mean 931K/s, up to 64 outstanding, off phase about 372K/s and saturated on phase about 1.49M/s. | Short p99 and p99.9 must stay within the contemporary same-binary band versus half in both reorder states. Among passing D values, compare p50 improvement retained and gain over D2. Keep achieved rate plus overall/long-class distributions. The prior cell's band was about +/-3% p50 and +/-5..7% tails; re-establish it in this session. |
| 2. Low load | Closed-loop, rate-limited GET **p32@256K and p8@512K**, 512 connections, 24 memtier instances, **3 complete rounds per cell/arm**. Preserve MIDLOAD's per-connection rate rounding and HDR aggregation. Check that hyphenated arm names and every completed round are parsed. | Share within **0.2 ms**, higher better; report percentage-point gain versus REF and D2, each round, achieved/offered rate, and <=0.5/1 ms diagnostics. The earlier p8 noise was about +/-5 points; a gain inside it does not locate the knee. |
| 3. Generic cells | Exactly the **14 rows in `tests/wbhybrid2_cells.txt`**, verified by `abbagate.read_cells`. Use the gate's ABBA instrument, qualified pins and contemporary null. Existing geometry is server 0-31 / loaders 32-111 without SMT; mainline schedules it. | Matched-load rate, cycles/op, IPC, instructions/op and commands/send for every cell. Preserve p8 gains, p32 parity and no losing class. The p1 rows retain their latency score. |

The generic IDs are `h05`, `h06`, `p8g`, `p8s`, `d1g_l0`, `d1s_l0`,
`m8g_l0`, `v1g_l0`, `d128g_l0`, `d32g_l1`, `d8s_l1`, `d32s_l1`,
`x9_32_l1`, `x9_32_l0`. Their source file is unchanged.

Use the measured curve to locate the largest useful D before burst tails leave
the band; extra completion gain alone is insufficient. The launch results put
D1/D2 inside the tail band and D0 outside it, while low-load gains rise with D.
No D3/D4 runtime result is claimed here. Append measurements as `MEASURE-RESULT`;
mainline owns performance judgment, live 1s/2s verification, gating and merging.

**Reproduction and accounting.** Preserve the frozen October 1 inputs under
`build/wbhybrid2/`; the builder validates their committed hashes before use.
Commands below are offline and do not boot any measurement arm.

```sh
taskset -c 112-127 python3 tools/wbhybrid2b_artifacts.py builds
taskset -c 112-127 python3 tools/wbhybrid2b_artifacts.py images
taskset -c 112-127 python3 tools/wbhybrid2b_artifacts.py proofs
taskset -c 112-127 python3 tools/wbhybrid2b_artifacts.py costs
taskset -c 112-127 python3 tools/wbhybrid2b_artifacts.py layout
taskset -c 112-127 python3 tools/wbhybrid2b_artifacts.py audit
```

Native build logs, source patches, raw proofs, instruction receipts, disassembly
and layout/identity checks are retained in `build/wbhybrid2b/`. Gate rows added
or retired: **0 quick / 0 full**. `tests/gate.sh`, `EXPECT_QUICK=446` and
`EXPECT_FULL=463` are unchanged; no count adjustment is needed.
