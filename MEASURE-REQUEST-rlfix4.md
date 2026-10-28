## rlfix4

The candidate removes redundant work from read-local GET admission. All 16 bounded
GET parser scopes are below the October 11 anchor's instruction counts; all 228
PRE/POST execution, admission and GET parser comparisons are unchanged or lower.
This is an instruction result, **not a throughput claim or a landing verdict**.
Correctness is **not fully green**: a RENAMENX failure matches the registered
AT4-WOUND-1 defect, reproduced deterministically in PRE and POST in both modes and
namespaces. One idle-wake ceiling failure also remains in the first-attempt record;
fresh isolated PRE/POST repeats passed without changing the ceiling.

Branch `cx-rlfix4`, PRE `a214652ec`, final production change `18f0ceb8b`. Later
commits contain proof and documentation. No push. The exact production file hashes
are in [final-source.json](docs/rlfix4/final-source.json). All commands use CPUs
32–47; correctness listeners use 20300–20399. Builds use `make -j16`.

### Changes and retained obligations

1. The complete RESP frame already has argument zero. Pass `op->arg(0)` to command
   lookup instead of calling `cmd_name()` and repeating its empty-frame check.
   `ParseResult::Empty` still returns before this point. Regenerate the R7 envelope
   from the same parser source; `r7shadow_sync.py` checks synchronization.
2. In fused parsing (including the split-local instantiation), skip the AOF-failure
   probe for the registry's GET/MGET class. `AofManager::deny_command` can reject a
   metadata write or PING; neither GET nor MGET qualifies. Every other command keeps
   the live probe, including writes queued inside MULTI. Ordinary split parsing
   retains its probe. This changes neither AOF refusal nor transaction queue errors.
3. Mark the scalar-only `FlatStore::hash_key` helper `no_stack_protector`. The DB0
   R7/default hash had inherited a canary from GCC outlining SipHash's reference-
   capturing round. Both hash arms have scalar locals, bounded reads and fixed
   eight-byte loads, with no local array or variable-width store. The hash
   algorithms and their existing inlining choices stay intact. This removes seven
   default-hash instructions per call where that frame was emitted.
4. Adjust only normal `rl2s.o`'s `large-unit-insns` budget, 164621 → 164637. Without
   this +16 correction, the registry guard makes armed MSET admission six
   instructions longer. +16 and +32 pass the count matrix and preserve unrelated
   HOT bodies; +64 changes `erase_in_read_local` and +256 changes scheduling bodies.
   The discrete trial receipts are in
   [rl2s-budget-selection.json](docs/rlfix4/rl2s-budget-selection.json).

No record layout, shard ownership, epoch, RYOW conflict rule, notification rule or
tracking certificate is changed. No reader retry, seqlock or mutable local-read
record is introduced. The required GET-miss, TTL deadline and tracking fixes remain.
The isolated 32-GET drain remains 30 instructions above the anchor in normal and
29 above it in DB0: +32 for the miss-capable resolver, +6/+5 for tracking, and −8
from completion folding. Restoring that body byte-for-byte would discard required
correctness work. POST's complete parser-plus-drain scopes are below the anchor.

The correctness rerun also exposed a setup race in `persistfix2.py`: it capped the
AOF file before establishing the transactions that the test says were queued
before the error. Previously buffered setup writes could then trigger MISCONF on
that setup SET. Queue all three pre-error transactions first, then cap the file and
issue the existing 200 KB failing write. All refusal and durability assertions stay.
The original failure is retained in
[aof-setup-race.json](docs/rlfix4/aof-setup-race.json), with its earlier candidate SHA.

### Instruction method and historical census

[tests/rlfix4_scope.cc](tests/rlfix4_scope.cc) links the actual release objects first,
in production order, and the fixture last. It renames only the DB0 `main`, calls
emitted parser/executor/local-read entries, and uses no sockets or worker threads.
Normal is the 16-database namespace; DB0 is the specialized one-database namespace.
Fixtures use 16 shards, eight logical threads (split 6:2, fused eight), 64-byte
values and eight-key scatter/gather commands. Batch size is commands, not keys.

The native ptrace counter bounds a command scope, counts production instructions,
steps over external-library callees, fixes clock returns and counts REP once (raw
trap counts are retained separately). It requires a real successful fixture exit.
It includes the five executed instructions in the unnamed `.rlfence` retirement
assembly; a function-symbol-only census would incorrectly omit them. Native/GDB
controls, a REP control and a deliberate post-scope failure control are recorded in
[native-gdb-controls.json](docs/rlfix4/native-gdb-controls.json) and
[tracer-selftest.json](docs/rlfix4/tracer-selftest.json).

`local` measures actual bounded drain; `parse` includes ordinary admission plus
that drain; `r7parse` uses the R7 envelope. The parser's normal per-pass FLIP snapshot
is set before entering the scope. `mix` is the read-local half after pending,
disjoint writes: one GET after one pending SET at batch one, and 29 GETs after three
pending SETs at batch 32. A completed warm read first arms RYOW. `parsemix`/`r7mix`
include parsing those writes, but do not include their owner execution. These are
command-scope counts, not an entire 90/10 workload or a cycles/op measurement.
Exact replies, completions, local-hit increments and unresolved writes are asserted.

Historical counts below come from the current hash-bound per-case records, not
stale intermediate result aggregates. The complete 984-case evidence is in
[final-counts.csv](docs/rlfix4/final-counts.csv) and
[final-counts.json](docs/rlfix4/final-counts.json).

| namespace | batch | scope | 991d48f65 | 05a5e01a9 | 3700b51d7 | a214652ec |
|---|---|---|---|---|---|---|
| normal | 1 | local | 931 | 938 | 938 | 930 |
| normal | 1 | mix | 931 | 938 | 938 | 930 |
| normal | 1 | parse | 2387 | 2402 | 2408 | 2393 |
| normal | 1 | parsemix | 2248 | 2263 | 2269 | 2254 |
| normal | 1 | r7parse | 2422 | 2441 | 2447 | 2431 |
| normal | 1 | r7mix | 2281 | 2298 | 2304 | 2288 |
| normal | 32 | local | 21391 | 21429 | 21429 | 21421 |
| normal | 32 | mix | 19411 | 19446 | 19446 | 19438 |
| normal | 32 | parse | 48535 | 48455 | 48647 | 48788 |
| normal | 32 | parsemix | 48433 | 48347 | 48533 | 48639 |
| normal | 32 | r7parse | 49251 | 49182 | 49374 | 49234 |
| normal | 32 | r7mix | 49222 | 49171 | 49360 | 49240 |
| db0 | 1 | local | 919 | 925 | 925 | 917 |
| db0 | 1 | mix | 919 | 925 | 925 | 917 |
| db0 | 1 | parse | 2300 | 2313 | 2319 | 2304 |
| db0 | 1 | parsemix | 2161 | 2174 | 2180 | 2165 |
| db0 | 1 | r7parse | 2323 | 2339 | 2340 | 2343 |
| db0 | 1 | r7mix | 2182 | 2198 | 2199 | 2200 |
| db0 | 32 | local | 20573 | 20610 | 20610 | 20602 |
| db0 | 32 | mix | 18671 | 18705 | 18705 | 18697 |
| db0 | 32 | parse | 45131 | 44986 | 45178 | 45505 |
| db0 | 32 | parsemix | 45137 | 44986 | 45178 | 45424 |
| db0 | 32 | r7parse | 45556 | 45476 | 45539 | 45952 |
| db0 | 32 | r7mix | 45626 | 45540 | 45600 | 46018 |

### Attribution

Wave 7's ordinary clean GET adds exactly six instructions per command (+192 at
batch 32) for the AOF-failure check. It is `persistfix2`, source `66f4a3c04`, integrated
by `f0d647b37`, then re-budgeted by `f941716b1`. Normal R7 also adds 192. DB0 R7 adds
only 63 net: the same probe is offset by 129 instructions of compiler-generated
savings. The local drain's executed bodies and counts do not change from wave 6 to
wave 7; the rlfix3 INFO counters are not entered by these scopes.

The earlier required costs are: GET-miss resolution, rlfix `3676d3cae` merged by
`d1f5fe0bc` (+1/read); tracking certification, trackfix `c97c118a2` merged by
`08d964975` (+6 normal / +5 DB0 per drain); and clockcut's exact TTL boundary
`5cd136502`, merge `4c692daf4` (cold-branch body change here). RESP resume,
`873b71047` / `39a4bd9b2`, changes the parser signature and caller code while saving
256 normal / 320 DB0 callee instructions per 32 complete requests. Netfix
`24c828243` adds four query-limit accounting instructions per pass. Wave-5
integration `323bbd770` outlines `flip_dispatch_paused` (seven instructions with the
actual per-pass snapshot). WATCH's null path keeps its count: txnorder
`a400d1f23` moves the cold `MultiSession` fields; atomfix5 `d64accaca`, merge
`033be1114`, changes cold logical-WATCH traversal.

Wave 8's latencyfix integration `81a7ec066` is the first compiled boundary to emit
the DB0 R7 hash canary (+224/32), the extra DB0 `cmd_name` call site (+384/32 in
ordinary parsing), and additional ordinary lane-room calls. The preceding
`60725691c`, readability `3fece28eb` and Lua `7cdc95318` images do not have that
canary. The ordinary DB0 clone already had that seven-instruction canary at
the anchor (2912 versus 2688 hash instructions per 32 commands); POST removes it
there too. That extra saving is not attributed to the October regression. The
same integration folds completion into a 17-instruction closure from
a 25-instruction `notify_sender` path (−8/drain). IO3 `ea28a43a6` changes the normal
parser again. Normal R7 begins calling `touch_worker` at iofix integration
`f49beb99e`; DB0 R7 gains that call at latencyfix `81a7ec066` (+20 in the mixed
batch). The latter also adds the normal mixed R7 storage-destructor call (+15).
Those helper bodies already existed; the change is which caller enters them.
The subsequent wave-8 and wave-8b identity budgets are part of the
cause, rather than being treated as source-neutral metadata.

For the clean batch-32 wave7 → PRE comparison, the exact additive ledger is:

| Envelope / namespace | Additions and removals | Net |
|---|---|---:|
| ordinary / normal | lane-room +434, parser −285, completion −8 | +141 |
| ordinary / DB0 | lane-room +434, command-name +384, parser −483, completion −8 | +327 |
| R7 / normal | parser −132, completion −8 | −140 |
| R7 / DB0 | hash +224, command-name +384, parser −187, completion −8 | +413 |

[function-deltas.json](docs/rlfix4/function-deltas.json) gives the exact additive
function ledger for every singleton/batch/mix/envelope transition; each ledger is
checked to sum to its case delta. The 45 changes to bodies actually entered by
fused GET are listed in
[visited-body-transitions.json](docs/rlfix4/visited-body-transitions.json), including
cold branches in otherwise hot functions. Unentered clones are excluded.
[source-sites/](docs/rlfix4/source-sites/) maps every historical parser PC to its
DWARF inline frames and source-line commit. That is source provenance; it is not a
claim that `git blame` alone identifies the integration that caused GCC to outline
an old line. Compile-boundary recipes and body hashes are recorded separately in
[boundaries/](docs/rlfix4/boundaries/), and the exact Makefile flags at each kept
integration are in [inlining-budget-history.json](docs/rlfix4/inlining-budget-history.json).

<!-- BODY_ATTRIBUTION_BEGIN -->
The completed [body-by-body index](docs/rlfix4/body-attribution.md) maps all 45
entered-body/set changes to source, caller and compiler events. There are 82
historical integration snapshots through wave 7, additional wave-8 merge/budget
snapshots, and 40 budget/source flag snapshots. The compile-only `-g0` control
matches 88 selected PRE bodies against the original `-g` objects. The
[source-origin ledgers](docs/rlfix4/source-origin-deltas.json) account for all 72
historical endpoint deltas. The only changed toolchain-origin bucket is normal R7
mix: six inline destructor instructions become fifteen in an outlined helper
(+9), at `81a7ec066`. The five anonymous ROB retirement instructions are unchanged.
Each source-origin and per-function ledger sums exactly to its command-scope delta.
<!-- BODY_ATTRIBUTION_END -->

### PRE versus POST and other commands

| Namespace | Batch | Scope | October 11 | PRE | POST | POST − PRE |
|---|---:|---|---:|---:|---:|---:|
| normal | 1 | parse | 2387 | 2393 | 2383 | -10 |
| normal | 1 | parsemix | 2248 | 2254 | 2244 | -10 |
| normal | 1 | r7parse | 2422 | 2431 | 2421 | -10 |
| normal | 1 | r7mix | 2281 | 2288 | 2278 | -10 |
| normal | 32 | parse | 48535 | 48788 | 48468 | -320 |
| normal | 32 | parsemix | 48433 | 48639 | 48331 | -308 |
| normal | 32 | r7parse | 49251 | 49234 | 48914 | -320 |
| normal | 32 | r7mix | 49222 | 49240 | 48929 | -311 |
| db0 | 1 | parse | 2300 | 2304 | 2285 | -19 |
| db0 | 1 | parsemix | 2161 | 2165 | 2146 | -19 |
| db0 | 1 | r7parse | 2323 | 2343 | 2320 | -23 |
| db0 | 1 | r7mix | 2182 | 2200 | 2177 | -23 |
| db0 | 32 | parse | 45131 | 45505 | 44897 | -608 |
| db0 | 32 | parsemix | 45137 | 45424 | 44828 | -596 |
| db0 | 32 | r7parse | 45556 | 45952 | 45340 | -612 |
| db0 | 32 | r7mix | 45626 | 46018 | 45418 | -600 |

The full nonincrease proof covers 116 execution scopes (GET/SET/INCR/MGET/MSET,
batch 1/32, both modes and namespaces, local and owner paths, armed/disarmed owner
paths, and MSET atomic 0/1), 16 GET parser scopes above, and 96 additional admission
scopes for all five commands. Owner admission scopes stop after actual parsing
and verify pending work and metadata; owner execution is counted independently.
Armed GET/MGET admission also drains and checks exact response bytes. MGET uses the
production one-command fence and repeats parse/drain for a batch, rather than
pretending the parser admits 32 MGETs in one turn.

| Scope family | GET | SET | INCR | MGET | MSET |
|---|---:|---:|---:|---:|---:|
| execution cases | 28 | 16 | 16 | 24 | 32 |
| execution delta range | 0 | 0 | 0 | −1792 to 0 | −1792 to 0 |
| admission cases | 16 | 16 | 16 | 16 | 32 |
| admission delta range | −632 to −4 | −504 to −2 | −504 to −1 | −3936 to −4 | −3680 to 0 |

Ranges are totals per bounded case, not per-operation averages. Every individual
result is in [final-deltas.json](docs/rlfix4/final-deltas.json). The DB0 eight-key
owner MGET/MSET saving is seven hash instructions per key (56 per command); local
MGET saves 55 per command with its caller adjustment. Normal execution is unchanged.

An earlier candidate (`45c2bd1a…`) passed execution-only counts but increased some
MGET/MSET admission cases by 2–7 instructions. It was rejected, the admission proof
was added, and the final registry-class guard and +16 budget were selected.
[rejected-case-counts.json.gz](docs/rlfix4/rejected-case-counts.json.gz) preserves the
rejected counts and binary hashes; superseded probes and trace files are removed.
No earlier candidate's correctness result is substituted for the final POST.

Every counted function body is bound to its same-arm linked server using the gate's
strict instruction normalizer, extended only to resolve actual literal values,
bounded byte-switch destinations and the real `.rlfence` section. Opcode, register,
member offset, source-line immediate and branch-condition changes remain visible.
Negative controls reject changed operands/targets; see
[normalizer-controls.log](docs/rlfix4/normalizer-controls.log) and the `binding-*.json`
receipts. This is a counted-body check, not a claim that the whole binary is identical.

### Artifacts and PAD-A

| Arm | Path | SHA-256 |
|---|---|---|
| pre | `build/tomokv-rlfix4-pre` | `2ffc953c8820419009929629e985b517d02787a461493edd81ce79571b030e5c` |
| post | `build/tomokv-rlfix4-post` | `5a903fd856e7cccfcb27df13da666be6381f3c0ae3a0a9428bb01f542ab0cb97` |
| pad-a | `build/tomokv-rlfix4-pad-a` | `88a45e76757236ef402721884f56de59aba01fef1f51b7c14e79403592c4e10d` |
| post-layout | `build/tomokv-rlfix4-post-layout` | `091a70220da1967f5b9fbda573f9c3b47ff877bcc4e5f7a29588907968d8cf93` |

The fixed merit anchor is
`/home/user/Projects/bench-bins/tomokv-headline-991d48f65`, SHA-256
`9f74d92965a0fcf10c59d00aaf5e09a9f05dfd64d509152f8e18aca7737efe3d`.
The locally rebuilt historical image has a separate hash and is used for instruction
work; [baseline-arms.json](docs/rlfix4/baseline-arms.json) distinguishes them.

**PAD kind (A), behaviour twin:** PRE behavior in the same common text layout as
POST-layout. Affected translation units are compiled with function sections and
linked in production order into max(PRE,POST) slots; padding is unreachable.
Natural POST is a separate artifact. Compare **POST-layout against PAD-A** for the
layout control, not natural POST against PAD-A. The common pair has all 10,421
function entries equal and identical executable-section addresses, offsets, sizes
and alignments. A changed-entry negative control fails. All 456 paired command
cases preserve totals and per-function counts: PAD-A=PRE, POST-layout=POST.
See [layout/addresses.json](docs/rlfix4/layout/addresses.json),
[layout/counts.json](docs/rlfix4/layout/counts.json), and the exact compile/link
recipes in [layout/build.json](docs/rlfix4/layout/build.json).

Natural `.text` changes from 8,457,095 to 8,457,799 bytes (+704). The control pair
uses a common 10,971,600-byte slotted section plus a 1,844,679-byte ordinary text
section. No inverse PAD-B is used; the requested behaviour twin is the comparison
that isolates changed behavior at matched function addresses. The source/object
scratch trees are removed after their counts, hashes and recipes are recorded.
Final `build/` usage is about 14 GB. The delivery hash/freshness and stopped-process
checks are recorded in [delivery.json](docs/rlfix4/delivery.json).

### Correctness receipts

<!-- CORRECTNESS_BEGIN -->
All requested correctness families ran through `tests/gate.sh`'s selected-job
interface. [correctness-index.json](docs/rlfix4/correctness-index.json) inventories
149 selected job names, exact run receipts, engine legs and frozen differential
plans. The final POST hash is `5a903fd8…`; later documentation commits did not change
its production source. The jobs use eight server cores, 16 shards and ratio 6:2,
except where an existing job explicitly exercises another geometry. CPU placement
and ports are recorded in every receipt. The following are **partial-job row
counts**, with overlapping coverage; they must not be summed into a full-gate tally.

| Run receipt in `docs/rlfix4/jobs/` | Result | Coverage / exception |
|---|---:|---|
| `final2-main.json` | 481 OK, 0 FAIL | Read-local, RYOW, notification/tracking, transaction ordering, atomics, writeback, production units, ASAN, parser and compatibility jobs |
| `final2-epoll-legs.json` | 274 OK, 1 FAIL | Counterpart epoll legs; bare RENAMENX failed in `fused-1` |
| `final2-fused-uring.json` | 58 OK, 1 FAIL | Explicit fused release/atomic/ASAN/debug/notification/script legs; idle ceiling failed |
| `final2-fused-epoll.json` | 59 OK, 0 FAIL | Same explicit fused legs on epoll |
| `final2-feature-multidb-evict.json` | 68 OK, 0 FAIL | 35 feature cells; full multidb mode/local/atomic and eviction matrices |
| `final2-atomic-extra.json` | 20 OK, 0 FAIL | Mover, hash-expiry and dispatch units/legs |
| `final2-differ-uring.json` | 6 OK, 0 FAIL | Standard split/armed atomic 0/1 suites plus mode equivalence |
| `final2-differ-epoll.json` | 6 OK, 0 FAIL | Same differential matrix on epoll |
| `final2-live-pad-a.json` | 11 OK, 0 FAIL | Read-local, AOF refusal and mode equivalence on PAD-A |
| `final2-live-post-layout.json` | 11 OK, 0 FAIL | Same directed checks on POST-layout |
| `final2-idle-repeat-{pre,post}.json` | 9 OK, 0 FAIL each | Fresh isolated whole release-battery jobs, original threshold |
| `final2-txnnx-{pre,post}-{1,2,3,4}.json` | 10 OK, 0 FAIL each | Four fresh whole `fused-1` epoll jobs per arm; no failures discarded |

The differential runs used all standard suites and permanent seeds **7/19/20/23**,
with rotating seed **27 on io_uring** and **26 on epoll**, including the standard
multi/atomic-1/seed-19 repeats and mode-equivalence streams. The gate's existing
armed-sort exclusion is retained; split 6:2 runs that suite. Redis oracle 7.4.10's
binary and digest are recorded in [oracle.json](docs/rlfix4/oracle.json).

`python3 tests/gates_test.py` passed **73 tests** on the final source, with
`GATE_TEST_PORT=20397`; see [gates-test-final2.json](docs/rlfix4/gates-test-final2.json).
`make -j16 all` and every `job_production_units` build target completed. All **48
freshness checks** passed: `all`, the 45 named unit targets, `mdbqsbr-live-arms`, and
the blockfix helper/digest check. See
[production-freshness-final.json](docs/rlfix4/production-freshness-final.json). Generated R7
synchronization, tracer failure/REP controls, strict normalizer negative controls,
and merit-cell grammar checks also passed. Earlier candidate/setup failures and
an earlier harness-test timeout remain recorded; they are not final-POST passes.

**Inherited correctness defect — AT4-WOUND-1.** In the epoll `fused-1` job, bare
RENAMENX iteration 1666 returned `[ERR no such key, 1]` while MGET showed
`[winner-a, nil, winner-b]`: the losing source still existed. The original log is
preserved in [txn-nx-first-failure.json](docs/rlfix4/txn-nx-first-failure.json).
The maintainer's `REGISTER.md:460` (2026-10-26) already assigns this symptom and
publication window to woundfix/P9. The relevant four production files are byte
identical in this lane's PRE and POST.

The registered deterministic fixture from `fc8528675`, copied verbatim to
[tests/rlfix4_wound_window.cc](tests/rlfix4_wound_window.cc), reproduces it in **all
eight PRE/POST × normal/DB0 × 1s/2s runs**. Every run exits 1 with
`read_done=1 pre_epoch=0 aborted=1 no_such_key=1 source_present=1 commit_accepted=1`.
These are defect reproductions, not passing tests. Recipes, binary hashes, stdout
and nonzero exits are in [wound-diagnostic.json](docs/rlfix4/wound-diagnostic.json);
source identities and registration provenance are in
[wound-inherited.json](docs/rlfix4/wound-inherited.json).

The path is `txn_wound`'s Placing→Wounded CAS before its cancellation-epoch CAS.
Another owner can finish the wounded source without materializing its image;
`finish_phase1` then selects NoSuchKey, while `txn_group_decide` accepts the still-zero
epoch. This violates the D2 wound-wait/atomic-decision guarantee. The deterministic
window explains the observed symptom; the live failing interleaving was not
traced. Four fresh whole-job lifetimes per arm (32,768 bare and 32,768 transactional
rounds each) passed, but do not clear this confirmed inherited defect. Its assigned
woundfix is outside this performance lane's diff.

**Idle ceiling.** One fused io_uring release-battery attempt observed 73 wakes
(29 sent + 44 received) against the unchanged limit of 64, with zero spins, while
other correctness jobs overlapped. Fresh isolated PRE and POST whole-job repeats
both passed. This establishes non-reproduction in those controls, not a proven
cause for the first failure. The original sample and repeat links are in
[idle-ceiling-first-failure.json](docs/rlfix4/idle-ceiling-first-failure.json).
<!-- CORRECTNESS_END -->

No row is added or retired: **DQ=0, DF=0**. `EXPECT_QUICK=807` and
`EXPECT_FULL=824` are unchanged. The existing quick exit is at `tests/gate.sh:5778`;
there is no row-count change on either side of that line.

Performance jobs, the full `tests/gate.sh iteration`, ABBA and load generators are
**NOT RUN**: the lane's runtime authorization is for correctness only. Selected
atomic batteries use the gate's existing `GATE_PROOF_NO_RATES=1` partial-job option;
the rate assertion explicitly prints SKIP while all overlap/ordering witnesses run.
These are partial-job receipts, not a claim of a complete gate iteration.

### Maintainer measurement request

Run on the quiet box with the gate's own instrument, replaying the placements,
shard counts and load envelope of the maintainer's section-70 reference runs.
The correctness geometry above must not silently replace that benchmark geometry.
The current instrument records a 32-thread **16:16** split ABBA shape, deriving
128 shards for split and 256 for fused; it has no reviewed eight-thread ABBA split.
Its explicit paper-image setting is **`--databases 1`**. Record the exact geometry
in each result and keep it identical between arms. The lane's CPUs 32–47 and ports
20300–20399 were used only for its authorized correctness/build/instruction work;
the wider benchmark placement remains the maintainer's separately scheduled work.
See [measurement-geometry.json](docs/rlfix4/measurement-geometry.json).
Verify artifact SHA-256s first. Record **three separately identified ABBA blocks**
for `d32g_l1` and `x9_32_l1` from
[tests/rlfix4_readlocal_cells.txt](tests/rlfix4_readlocal_cells.txt), for each pair:

- natural POST versus PRE;
- POST-layout versus **PAD-A (A: PRE behavior, matched candidate-control layout)**;
- natural POST versus the fixed headline anchor `991d48f65` above.

Also run the 14 generic cells plus the four 2s GET/SET p1/p32 null cells in
[tests/rlfix4_merit_cells.txt](tests/rlfix4_merit_cells.txt), natural POST versus PRE.
The file uses the gate's 15-field cell grammar. Keep offered load, placements,
connection counts and pipeline depths matched between arms. Record rate,
cycles/op, instructions/op and IPC per cell and block. Rate at matched offered load
is the merit verdict; instructions and IPC explain it. The two target cells must
improve consistently, the layout-controlled comparison must support the same
behavioral conclusion, and the other command cells must remain level or improve.
An instruction saving by itself is not acceptance. No measured rate is asserted
by this report; the maintainer records the result in `MEASURE-RESULT`.
