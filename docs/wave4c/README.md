# wave4c command-body budget audit

The requested exact restoration was **not achieved** by these compile-only trials.
No production source, compiler budget, layout, or identity normalizer is changed.
The forced four-unit rebuild produces the same full ELF SHA-256 as the incoming
merge: `3dfe9e510917cc12e320e6e31ca9f22f8ac498c2e5353ce162ff273b2f01f8e5`.
The reported MGET regression remains unresolved; this work makes no rate claim.
The executable change in this lane is the ABBA **harness** row budget and its
wiring assertions, documented in [timing/README.md](timing/README.md).

## References and what differs

[reference-policy.json](reference-policy.json) names the reference for every
one of the ten command-path residual groups. The existing strict linked-body
normalizer remains the authority; diagnostic observations below do not reclassify
any group.

| Groups | Required comparison | Finding |
|---|---|---|
| Both `store_xstring_selected` copies | headline | Instruction encodings after existing relocation masking already match. The remaining difference is the compiler's `CSWTCH` serial label. |
| Four `cmd_xshard_only_impl` copies | headline | Encodings match under the same existing masking. Remaining operands name the switch table and anonymous scalar data through different labels/offsets. |
| DB0 `xshard_execute` and its cold fragment | moverfix POST | Moverfix intentionally changes mover dispatch. POST still outlines `std::mutex::lock` where the frozen moverfix body inlines it; the main and cold sizes differ. |
| Both armed `cmd_set_prebuilt<true>` copies | clockcut POST, with compat2 retained | Clockcut changes absolute-deadline `<=` to `<`; compat2 changes the inlined expiry-notification guard. No supplied single-lane binary contains both fixes. Relative to compat2, the two current bodies differ only in seven deadline branch opcodes per namespace. Exact equality to either single-lane reference would discard the other lane's intended semantics. |

The clockcut reference is the semantic comparison for SET's direct deadline
change, not a claim of exact equality or a waiver of compat2. The headline and
moverfix bodies lack both SET fixes. The DB0 dispatch reference is moverfix
because its dispatch change must survive, regardless of other lanes' changes in
callees/compiler context. Exact unified differences against every frozen arm are
in [reference-diffs-3dfe9e51.json.gz](reference-diffs-3dfe9e51.json.gz).

[literal-proof.json](literal-proof.json) separately reads and compares the actual
ELF read-only bytes at every disputed table/scalar reference in the six label-only
groups. They match, including both four-byte tables and both eight-byte scalar
values. This is additional evidence about the residual's cause, not a relaxed
identity rule. [mutex-inline-reason.txt](mutex-inline-reason.txt) records GCC's
DB0 decision: the mutex call is frequency zero and rejected because the call is
unlikely and code size would grow, not because the per-unit budget was exhausted.

## Compile-only trials and selection

[budgets.py](budgets.py) builds with `make -j32`, swaps one object into the whole
linked candidate, and checks every function group against all frozen references.
It never runs a candidate. There are **104 configurations, 102 distinct compiler
commands, and 98 distinct stripped object bodies**. Deduplicated bodies reuse the
same linked score; the original command and object digest remain in each record.
All tools inherit CPUs within 64–111.

The sweep covers normal xshard unit budgets 128600–129100, DB0 126500–128000
(including dense 127780–127844 trials), L4 budgets 10000–14000 with growth zero,
and the compiler defaults. It also varies automatic-inline limits 12–20,
cold-size limits 1–10, and early-inline limits 4–8 on the relevant DB0 boundary.
The exact sampled values, compiler commands, full changed-body lists, newly lost
matches, and hot scores are in [budgets/scan.json](budgets/scan.json),
[budgets/refine.json](budgets/refine.json), and [budgets/cold.json](budgets/cold.json).
This is a bounded search, not proof that no compiler configuration can succeed.

| Object | Starting IPA unit size | Retained large-unit-insns | Retained inline-unit-growth |
|---|---:|---:|---:|
| `src/cmd/xshard.o` | 101128 | 128705 | 0 |
| `db0/src/cmd/xshard.o` | 99819 | 127713 | 0 |
| `src/cmd/l4prebuild.o` | 7614 | 10000 (compiler default) | 40 (compiler default) |
| `db0/src/cmd/l4prebuild.o` | 7508 | 10000 (compiler default) | 40 (compiler default) |

Explicit L4 growth-zero/budget-14000 trials also reproduce the current linked
bodies, so adding those flags would not restore a group. None of the 104 trials
restores **any** of the original ten command residuals, even when another residual
is introduced. [selection.json](selection.json) retains this check and all trials'
trade lists. The selection preserves all 8,536 existing reference matches; the
minimum hot-union residual count under that constraint remains 27.

If that constraint were discarded, normal xshard budget 129032 gives the best
observed hot-union count, 26, and full residual count 108. It still restores no
requested command body and changes an already-matching DB0 CONFIG body. Its full
seven-group change list is:

| Changed group | Trial result |
|---|---|
| `tomo::FlatStore::projected_bytes` | Restores headline |
| `tomo::multi_handle_io` | Restores headline |
| `tomo::multi_handle_io [clone .cold]` | Restores headline |
| `tomo_db0::cmd_config` | Loses its previous reference match |
| DB0 `FlatStore::scan_home<cmd_scan lambda>` | Restores clockcut |
| `tomo::IoLoop::on_cqe<true,true,true>` | Restores headline; sole hot-count gain |
| `tomo::reply_double<Op::Sink>` | Restores headline |

Because no target is restored and the task protects every prior match, this
incidental link-layout trade is rejected. All other candidates' exact symbol
names and trade lists remain in the machine-readable trial records.

## Rebuild and identity

The four relevant production objects were forcibly rebuilt and the merged POST
relinked. `identity.py` and `residuals.py` were rerun. The regenerated inventory
payloads equal the incoming ones, so their original gzip headers were retained
to avoid timestamp-only changes. The command-path inventory was also regenerated.
[identity-summary.json](identity-summary.json) records the fresh digests and counts.

| Inventory | Groups | Headline-identical | Lane-identical | Residual |
|---|---:|---:|---:|---:|
| All bodies, PRE and POST | 8649 | 7932 | 604 | 113 |
| Historical hot selector, PRE and POST | 489 | 394 | 78 | 17 |
| Expanded command paths, PRE and POST | 77 | 50 | 17 | 10 |

The historical hot selector and command selector overlap in 12 already-matching
groups. Their union is 554 groups with 27 residuals; the ten command residuals
were never part of the historical 17. Both counts remain explicit.

[production-build.json](production-build.json) records `make -k -j32 all`, all
37 exact `job_production_units` targets, the additional MDB live arms, and **39/39**
individual `make -q` checks. The build passed. Compressed build and regeneration
logs are alongside this file. Final gate-owned job receipts and limitations are
recorded in the wave4c section of `MEASURE-REQUEST-wave4.md`.
