# wblandfix — anchored writeback witnesses

Completed on branch `cx-wblandfix`. No performance measurement is requested:
this lane changes tests and evidence only. No server, benchmark, load generator,
or gate was run; nothing was pushed.

`origin/cpp` was merged first, fast-forwarding `90ba908d3` to `2a9e48403`.
The source changes shown in the baseline diffstat below belong to that required
merge (cleanup-readreply), not to wblandfix. The lane's implementation commits are
`2471e9698` (anchored source checks) and `dcc23d365` (source mutation controls and
read-only cross-tree checking). All builds and test executions used
`taskset -c 112-127`; the unit build used `make -j16 build/wbland-units`.

## What source() now proves

The checker no longer invokes `git show` or compares any whole envelope or
`defer()` body to `37eeb5e90`. It tokenizes source while ignoring whitespace and
comments, preserving identifier boundaries and treating literals as opaque.

For each envelope, it extracts every `wb_rule::Phase2::` call, including its
template and ordinary arguments, and compares the complete call multiset to the
explicit expected calls below. It also requires the immediate AOF/FIFO guards
and return statement at the tail of the named method. Extra calls, different
arguments, missing guards, and code inserted after the return fail by name.

Every code reference to `wb_rule::`, `pending_serve_`, `serve_pending`
(including `set_serve_pending`), `kWbufInline`, `kPolicyFraction`, or `defer(`
must fall inside one of the exact, counted fragments. The existing FIFO
lifetime/migration checks and buffer type declarations also use these names,
so they have small explicit anchors listed below. No entire method is exempted
from the remaining-reference scan. Comments and string literals are not code
references.

The detector/publication ban list remains exactly:
`wb_policy_signals_`, `wb_policy_signal(`, `wb_rule::State`, `wb_policy.pass(`,
`wb_policy.publish(`, `wb_adaptive`, `wb_thread_`, `struct Window`,
`struct Published`. It covers the rule, all three envelopes (now explicitly
including `wb.h`), and `server.h`. The original literal bans remain effective;
token matching additionally catches whitespace between tokens.

The clock/allocation bans remain `now_ns(`, `clock_gettime`, `new `, `malloc(`,
`make_unique`, `build_arm` in the rule. They also cover the WB engine's code and
the IO writeback methods `wb_gather`, `wb_observe`, `wb_prefetch`,
`wb_retire_prepare`, `wb_submit_reclaim`, `wb_serve_natural`, `pipeline_pass`,
`flush_ready`, `enqueue_serve`, and R7's `r7_flush_ready`. These are scoped bans:
IO's existing accept/TLS allocations, slowlog clocks and timer clocks are outside
the writeback methods. A blanket ban on those whole IO files would reject the
current tree.

`tests/r7shadow_sync.py` still runs against the tree being checked. It verifies
the generated envelopes against that tree's current ordinary methods. No R7
parity check was removed or weakened.

Unrelated source text, boot tails, comments, and the spelling of the policy
implementation are no longer historical source pins. A rule change must still
update the behavioural tables and mutation controls to establish its new
contract; changing `source()` alone cannot make the existing behavioural
witnesses accept another rule.

## Exact anchors at 90ba908d3

These line numbers document the baseline only; the checker locates methods and
fragments by tokens, not by line number.

| Envelope / method | Guard anchor | Call anchor | Expected expression and count |
| --- | --- | --- | --- |
| `src/core/io_loop.h` / `wb_gather` (definition 4577) | 4578–4593: empty batch/FIFO and AOF gate | 4595 | `wb_rule::Phase2::gather(*this, batch, captured_left)` × 1 |
| `src/core/io_loop.h` / `flush_ready` (definition 4975) | 5190–5202: pending FIFO and AOF gate | 5203 | `wb_rule::Phase2::serve<HasTls, kEp, IoLoop, Fused>(*this)` × 1 |
| `src/core/reorder.cc` / `r7_flush_ready` (definition 1125) | 1341–1353: pending FIFO and AOF gate | 1354 | `wb_rule::Phase2::serve<HasTls, kEp, IoLoop, Fused>(*this)` × 1 |
| `src/net/wb.h` | No policy guard or call | None | Empty call set; no watched references |

The serve sites retain `return work +`; the gather site retains `return`.
The checked guard text is recorded explicitly as `SERVE_GUARD` and
`GATHER_GUARD` in `tests/wbland_checks.py`.

The remaining existing references have these scoped plumbing anchors. Every
fragment occurs once in its named method except the two buffer declarations in
each parser. Repeating even an allowed fragment beyond its expected count fails.

| File | Baseline line(s) | Owning scope and anchored fragment |
| --- | --- | --- |
| `src/core/io_loop.h` | 62 | `friend struct wb_rule::Phase2;` |
| `src/core/io_loop.h` | 1719–1727 | `flip_io_drained`: pending FIFO and other owner queues must drain |
| `src/core/io_loop.h` | 1738–1740 | `flip_io_drained`: coordinator ROB/send/pending/migration guard |
| `src/core/io_loop.h` | 4189, 4254 | `parse_and_dispatch`: `SmallBuf<kWbufInline>& fb = c->fill_buf();` × 2 |
| `src/core/io_loop.h` | 4677 | `ifid_parse_hash`: backstop enqueues only when no serve is pending |
| `src/core/io_loop.h` | 4776–4777 | `ifid_parse_hash`: complete idle predicate including `!c->serve_pending()` |
| `src/core/io_loop.h` | 4958 | `pipeline_pass`: captured-left/FIFO loop guard |
| `src/core/io_loop.h` | 4965 | `pipeline_pass`: remaining captured work increments `work` |
| `src/core/io_loop.h` | 4992 | `flush_ready`: same backstop enqueue guard |
| `src/core/io_loop.h` | 5144–5145 | `flush_ready`: same complete idle predicate |
| `src/core/io_loop.h` | 5207–5209 | `enqueue_serve`: deduplicate, set lifetime pin, append to FIFO |
| `src/core/io_loop.h` | 5549–5552 | `reap_dead`: retain pending/send/recv-pinned corpses |
| `src/core/io_loop.h` | 5572 | `std::deque<Client*> pending_serve_;` |
| `src/core/reorder.cc` | 1143, 1295–1296 | `r7_flush_ready`: backstop enqueue and complete idle predicate |
| `src/core/reorder.cc` | 1776, 1875–1876 | `r7_ifid_parse_hash`: backstop enqueue and complete idle predicate |
| `src/core/reorder.cc` | 3403, 3468 | `r7_parse_and_dispatch`: the same buffer declaration × 2 |

## Behavioural oracle retained

The current rule remains the composite byte-or-ceil-half rule. No C++ witness
table or production mutation was changed:

- `tests/wbland_unit.cc`: every `n=0..64` and every contiguous Done prefix,
  policy 0 and policy 1; finished/staged-only/scatter/511/512-byte exits;
  grammar, default/layout and INFO.
- `tests/wbland_clause_unit.cc` reuses `tests/wb_rule_unit.cc` through a runtime
  policy-1 read: odd/even ceil boundaries and ROB wrap, staging sources,
  submitted-byte exclusion, accumulated spill/direct/borrow bytes and CRLF,
  first holes, scatter and retire markers, coded replies, acquire-before-read,
  and termination at the successful threshold. Both namespaces run all cases.
- `tests/wb_rule_phase_unit.cc`: policy 0/1 retirement, deferred lifetime pins,
  staged-only progress and one serve per admission in fused, R7, split and
  split-local paths, including natural/shallow overlap and more clients than
  one scratch chunk. Both namespaces run all physical schedules.
- The four wbland production mutants, nineteen clause mutants, and three
  policy-bypass path executions still require their named assertion and exit 1.

## Results

All commands below exited 0. They are serverless.

```sh
taskset -c 112-127 make -j16 build/wbland-units
taskset -c 112-127 python3 -B tests/wbland_checks.py check clauses
taskset -c 112-127 python3 -B tests/wbland_checks.py check paths
taskset -c 112-127 python3 -B tests/wbland_checks.py \
  --root /home/user/Projects/cx-cleanup-boot check clauses \
  --proofs /home/user/Projects/cx-wblandfix/build/wblandfix-cleanup-boot-clauses-proofs.json
```

| Check | Passed | Positive | Expected named failures |
| --- | ---: | ---: | ---: |
| Current `check clauses` | 60/60 | 28 | 32 |
| Current `check paths` | 19/19 | 16 | 3 |
| cleanup-boot `check clauses` | 60/60 | 28 | 32 |

The clauses total is the original 49 compiled outcomes plus 11 new source
controls (two positive, nine negative). The source checks and current-tree R7
parity also passed in both trees. All source-control processes run in disposable
copies under this worktree's `build/`; a changed/missing mutation anchor fails
instead of silently skipping its test. Negative outcomes require exit 1 and
the specified assertion, so crashes, timeouts and unrelated failures cannot pass.

Each failure below has the prefix `FAIL wbland source: `.

| Source control | Exit | Required assertion / positive result |
| --- | ---: | --- |
| R7 `serve` argument `Fused` changed to `true` | 1 | `src/core/reorder.cc: Phase2 call set (count/arguments)` |
| Unrelated comment appended to `reorder.cc` | 0 | Source checks and R7 parity pass |
| Extra `gather` call inserted in `io_loop.h` | 1 | `src/core/io_loop.h: Phase2 call set (count/arguments)` |
| `struct Window` restored in `wb_rule.h` | 1 | `src/core/wb_rule.h: banned token struct Window` |
| R7 pending FIFO guard inverted | 1 | `src/core/reorder.cc: r7_flush_ready anchored writeback site` |
| Stray `wb_rule::defer(*c)` added to `enqueue_serve` | 1 | `src/core/io_loop.h: unanchored writeback reference wb_rule` |
| Clock read restored in the rule | 1 | `src/core/wb_rule.h: banned token now_ns(` |
| Allocation added to the rule | 1 | `src/core/wb_rule.h: banned token new` |
| Clock read added to ordinary `flush_ready` | 1 | `src/core/io_loop.h:flush_ready: banned token now_ns(` |
| Clock read added to the WB engine | 1 | `src/net/wb.h: banned token now_ns(` |
| Equivalent rule spelling `n <= 1` → `n < 2` | 0 | Source checks and R7 parity pass; no rule-text equality remains |

The cleanup-boot cross-check used this lane's checker with `ROOT` set by
`--root`, against cleanup-boot HEAD `fab03f469` and its pre-existing serverless
unit binaries. It read cleanup-boot's actual source, R7 generator and helper.
The checker was not copied into or written over that lane; the receipt and all
temporary overlays were written here. Cleanup-boot's tracked status remained
clean before and after the check.

Full stdout/stderr, expected exits, assertion names and binary hashes are in:

| Receipt | SHA-256 |
| --- | --- |
| `build/wbland-clauses-proofs.json` | `082642a893c8e70463697c2354199e5ba0845e66aee508d5951f6ace24895070` |
| `build/wbland-paths-proofs.json` | `d502e16438e7de0f453716ceb69414c12afe30a7d0fc3d828a86f428d5f21b77` |
| `build/wblandfix-cleanup-boot-clauses-proofs.json` | `88dc7f43badba80e30a5be8c478985e4772cece01591dbe6b6015049a34a86f7` |

`tests/wbland_evidence.json` now records these source anchors, control outcomes,
receipt hashes and cross-check under `wblandfix`. Earlier REF/build/object-text
entries are preserved as historical landing evidence; they are not the active
source oracle.

## Gate accounting and scope

No gate rows were added or removed. Both existing wbland rows are emitted by
`tests/gate.sh:1297` (failure at 1299; `row_begin` at 1294), collected at line
2742, before the quick-tier exit at line 2871. Delta: quick 0, full 0.
`EXPECT_QUICK=446` at line 260 and `EXPECT_FULL=463` at line 261 are untouched.
The lane diff against merged base `2a9e48403` contains only this report,
`tests/wbland_checks.py` and `tests/wbland_evidence.json`; no `src/`, Makefile,
gate or witness-table changes.

The requested staging command `git add -A ':!CODEX-OUT.md'` rejected the ignored
`CODEX-OUT.md` path in this checkout. Commits used explicit lane-file pathspecs
instead, leaving `CODEX-OUT.md` excluded.

## git diff 90ba908d3 --stat

This includes the five files inherited from the initial `origin/cpp` merge.

```text
 MEASURE-REQUEST-cleanup-readreply.md | 371 +++++++++++++++++++++++++++++++++++
 MEASURE-REQUEST-wblandfix.md         | 209 ++++++++++++++++++++
 src/core/ex_loop.h                   |  63 +++---
 tests/gate_measurements.json         |   6 +-
 tests/rltopo_unit.cc                 | 148 +++++++++++++-
 tests/wbland_checks.py               | 286 ++++++++++++++++++++++++---
 tests/wbland_evidence.json           | 169 ++++++++++++++++
 tools/readreply_proof.py             | 369 ++++++++++++++++++++++++++++++++++
 8 files changed, 1548 insertions(+), 73 deletions(-)
```
