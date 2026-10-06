# ccfix3 — round-1 restoration and explicit compatibility deviations

**Work in progress; not a shipping receipt.** The requested upstream composition is
not available yet: repeated `git fetch origin cpp` leaves `origin/cpp` at
`9d957b9fbb7a6eadace068b9615eef81b0dd6686`, without the anticipated psfix, cmdmeta,
or storesize5 landing commits. The two remaining ordinary-body differences in
`db0/src/main.o` also prevent acceptance. The restored code and completed proofs
are committed; this is not a claim that ccfix3 is shippable. Nothing is pushed.

## Production scope

Commit `49499a826` restored **all of `src/` and Makefile** to `bd4a20ebf`, then
removed the unsupported `failed_calls` field from the INFO emitter. The exact
`git diff bd4a20ebf -- src Makefile` is preserved in
[round1-production.diff](docs/ccfix3/round1-production.diff): it contains only that
emitter edit. CC11's sink classifier, CC12's flag order, CC13's `ERR ` prefix, and
the round-1 counter storage were not rewritten.

The next commit, `8a0dccd46`, restored the existing mainline changes inherited by
the earlier ccfix2 merge. A normal merge cannot restore files reverted from its
common ancestry. The reconstruction reapplied the complete round-1 patch onto
the actual `origin/cpp` production tree, with the emitter exception, preserving
the already landed cdfix/respcompat/at15 work. `git merge origin/cpp` reports
already up to date. This does **not** claim the three anticipated lanes landed.
[Mechanism hashes](docs/ccfix3/round1-mechanisms.json) confirm the five CC11/12/13
and counter-header files still equal `bd4a20ebf` byte for byte.

The owner supplied the round-1 performance ruling: production `bd4a20ebf`, binary
`ff58fe0503a9032bf754d4714078f9f9760b4b62b15e40659b60dca0ec852084`, was within the
existing band on all fourteen generic cells, with 1,486/1,486 selected hot bodies
identical and a zero-instruction disabled-notifications witness. That ruling is
the acceptance context for the restored mechanism, not a measurement of this
rebuilt tree.

## Emitter contract and shelved work

The complete emitted row is now:

```text
cmdstat_<name>:calls=<n>,rejected_calls=<n>\r\n
```

There are no `usec`, `usec_per_call`, or `failed_calls` fields. This is an explicit
Redis INFO surface deviation. Real executed-error accounting is absent; the
unused round-1 failed-counter storage remains because the production restoration
permits only the emitter change. Rejection-only rows and RESETSTAT remain covered.
The retained rejection scope is the round-1 ACL/NOAUTH sites, not a claim of
complete Redis rejection, script, or MULTI accounting.

ccfix2 remains shelved in history (`622b9969f`, `8ae728d6e`, `467798e09`, receipt
`0eed75dff`). Its evidence is unchanged. Reproduce its historical runner from
`0eed75dff`; the current tests deliberately assert the restored deviations instead.

- [Original report](MEASURE-REQUEST-ccfix2.md) records incomplete Lua forwarded-error
  semantics, missing nested command-call accounting, and MULTI queue-time counting.
- [Body inventory](docs/ccfix2/final-audit/changed-bodies.json) lists the 466 changes
  beyond error-call targets, including 41 command-handler occurrences and ordinary
  APPEND/GETEX/HLEN/dispatch/store changes.
- [Instruction comparison](docs/ccfix2/instruction-comparison.json) retains the
  `note_command` regression, 700,038 to 700,039 instructions.
- [Pending-record unit receipt](docs/ccfix2/atomic-unit-2s.log) proves what its
  now-removed scatter hook did. It is not evidence that this candidate emits those
  notifications. The shelved hook also added disabled-path work.

The differential now requires `(calls,rejected_calls)=(0,1)` after denied GET,
`(1,1)` after executed WRONGTYPE GET, and `(2,1)` after successful missing GET.
Its target parser requires exactly the two named fields in that order.
`EXPECTED-DEVIATION` checks assert that failed_calls is absent after actual GET,
EXEC, and Lua errors, while the oracle reports failures. Serverless checks also
assert that the production error paths leave the internal failed counters zero.

CC11 ordinary source/destination checks explicitly select atomic=0, then restore
the harness's original setting. Retained atomic records can otherwise select the
pending lookup even after a command completes. On atomic=1, separate checks hold
a cross-owner MSET undecided, prove source records/predecessor reads and exclusion
of localfast, then require **zero** target keymiss frames versus Redis's 1/2/2 for
COPY/SINTERSTORE/BITOP. The serverless fixture proves the same gap in both modes;
removing its arming fails. Missing windows and notifications are never skipped.

Publication markers can precede deferred notification delivery. The ordinary
fixture now checks the exact producer-counter delta and waits for both the marker
and every expected frame, with a bounded connection timeout. Extra frames fail.
Initial wire failures are retained under [wire-attempts](docs/ccfix3/wire-attempts).

## Integration and compiler budgets

`tests/differ.py` retains every existing suite, including ccfix and cmdmeta, with
one name per line. The future psfix merge must keep its additional suite as well.
`tests/notify.py`'s old `AKEn -> AKEn` expectation is corrected to `AKEn -> AKE`.
INFO shape assertions in `tests/differ.py` and `tests/infofix.py` require two fields.

The current root main.o keeps round-1's 146401 budget. The current db0 main.o
keeps 146215 provisionally. Tested db0 values 146213–146220 and 146270 do not
reproduce all current PRE bodies; their full differences are retained as
`docs/ccfix3/budget-main-*-db0.json`. 146214 also fails, so dropping the ccfix
increment is not justified. These are experiments against 9d957b9fb, **not** a
claimed resolution of the unavailable storesize5 composition or its 146270 budget.

Removing failed_calls from the emitter perturbs the db0 t_server inlining budget.
31520 reproduces all its checked nonadministrative command-handler bodies;
31500/default does not. The
comparison is [budget-server-31520-db0.json](docs/ccfix3/budget-server-31520-db0.json).
Production commit `ca316d37e` commits 31520. There is exactly one db0 main.o
override; it remains the explicitly unresolved 146215, not a layered combination
with storesize's 146270. [All budget experiments](docs/ccfix3/budget-search.json)
retain the disallowed bodies for each tried value.

## Final binaries and body audits

Both namespace variants were rebuilt with GCC 13.3.0 and the repository Makefile:

```sh
git archive origin/cpp | tar -x -C build/ccfix3/pre-src
taskset -c 112-127 make -C build/ccfix3/pre-src -j8 BUILD_ROOT="$PWD/build/ccfix3/PRE" all
taskset -c 112-127 make -j16 BUILD_ROOT=build/ccfix3/POST all
```

PRE is the actual fetched upstream `9d957b9fb`; POST production is `ca316d37e`.
[Build manifest](docs/ccfix3/build-manifest.json) includes complete source and
binary identities, compiler, all 88 production objects, and section sizes.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/ccfix3/PRE/tomokv` | `c9d0b98dc4c26449a60313db0378eae30e013297a649c0e6fed006bc3742a180` |
| POST | `build/ccfix3/POST/tomokv` | `b61beaedf67259aafb3de40c610b1ecff2831f06fe40f378c417732dc5fbbfdd` |
| Review copy | `build/tomokv` | `b61beaedf67259aafb3de40c610b1ecff2831f06fe40f378c417732dc5fbbfdd` |

`cmp` confirms POST and the review copy have the same bytes. GNU size text is
8,816,785 → 8,818,557 (+1,772); `.text` is 7,797,900 → 7,799,068 (+1,168);
data remains 89,720; BSS is 1,146,456 → 1,146,584 (+128). Locked instance layouts
are unchanged, including both namespaces' complete exported layout arrays.

The unchanged `tools/ccfix_audit.py` runs **without** `--error-callees`:
16,858/16,940 object-function occurrences match. All 1,208 ordinary handler
occurrences match; the five differing handler occurrences are CONFIG/INFO roots
and their cold clones. However, only **1,490/1,492 selected hot bodies match**;
the audit correctly exits 1. The two unacceptable bodies, both in db0/main.o, are:

```text
tomo_db0::WbEngine::serve_impl<false, true, false, true, false, false>(tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const  [537 -> 824 bytes]
tomo_db0::WbEngine::serve_impl<false, true, true, true, false, false>(tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const  [824 -> 537 bytes]
```

GCC swaps which specialization inlines `Client::append_static_segment`. These
are actual instruction changes, not label normalization. The full inventory
drops no bodies. [Every one of the 82 changed/added/removed occurrences and its
reason](docs/ccfix3/changed-bodies.md), [machine-readable list](docs/ccfix3/changed-bodies-with-reasons.json),
and [strict summary](docs/ccfix3/final-audit/summary.json) are retained.

Unmodified `r7shadow_noop.py --inventory splitlocal` remains **391/396,
strict_noop=False**. Its five label-only differences have identical switch bytes
or in-function case destinations under the existing `tools/ccfix_tables.py`:
[exact proof](docs/ccfix3/linked-data-proof-final.json),
[complete linked inventory](docs/ccfix3/splitlocal-final.json.gz).
That supplemental proof does not waive the separate writeback-body failures.

## Proofs and remaining acceptance work

All lane builds and proofs use CPUs 112–127. Server geometry is 112–119, sixteen
shards, split 6:2 or armed fused; correctness clients use 120–127. No throughput,
ABBA, NIC, or full-gate measurement is run.

- `python3 tools/ccfix3_prove.py units`: original flag/classifier/storage checks,
  executed-error deviation checks, PRE flag negative control, both-mode pending
  and Lua/MULTI deviation fixtures, and the no-arm negative control pass.
- `python3 tools/ccfix3_prove.py instructions`: the complete final serial run
  is byte-equal PRE/POST in both namespaces. Raw CSVs and
  [comparison](docs/ccfix3/instruction-comparison.json) are retained.
- `python3 tools/ccfix3_prove.py layouts`: every exported layout matches PRE in
  both namespaces; all eight locked sizes remain unchanged.
- `tools/ccfix3_wire.sh`: eight focused Redis 7.4.10 legs pass, across split and
  armed fused, atomic 0/1 and seeds 7/19. Each atomic=0 leg has 210 exact
  comparisons; each atomic=1 leg has 222. The runner imports the unmodified
  `differ_gate.sh` ownership/boot/stop helpers and asserts the oracle version.
  These are focused proofs, not complete differential-matrix receipts.
- The final unmodified splitlocal audit reports 391/396. The five differences
  are the same switch-label/jump-table address class as round 1; the exact data
  proof passes. Neither result waives the two separate changed writeback helpers.
- The requested selected gate is running with
  `GATE_ONLY_JOBS='netcmd_units auth acl_recheck notify'`. Its final receipt is pending.

| Interval, 100,000 calls | PRE | POST | db0 PRE | db0 POST |
|---|---:|---:|---:|---:|
| off/keymiss | 1,800,053 | 1,800,053 | 1,800,053 | 1,800,053 |
| off/string | 1,800,053 | 1,800,053 | 1,800,053 | 1,800,053 |
| save-only/keymiss | 2,000,053 | 2,000,053 | 2,000,053 | 2,000,053 |
| save-only/string | 2,400,053 | 2,400,053 | 2,400,053 | 2,400,053 |
| note_command | 700,038 | 700,038 | 700,038 | 700,038 |

The first final-build instruction run overlapped the wire proofs and **failed**
exact equality: normal-namespace POST was +11 on save-only/keymiss, +67 on
save-only/string and +10 on note_command. Its
[complete raw readouts](docs/ccfix3/instructions-final-attempt/instruction-comparison.json)
and [failed assertion](docs/ccfix3/instructions-final.log) remain committed.
After the wire proofs ended, one complete serial rerun produced the table above;
no instruction, tolerance, rounding, or witness-loop change was introduced.
The initial-build complete run also matched. These are the observed outcomes,
not a claim that the failing run was proved to be measurement noise. They do not
waive the independently failing body audit.

Gate rows are **+0 quick / +0 full**. `tests/gate.sh` is untouched, including its
499/516 constants. Existing differential rows are at lines 3380 and 3391, after
the quick-tier exit at line 3348. No count adjustment is requested.

Once the missing upstream composition and ordinary-body equality are resolved,
the maintainer can run the gate's unchanged fourteen generic cells
`h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64` at matched offered load,
notifications off, using PRE versus POST and the established per-cell acceptance
band. Record rate, cycles/op, instructions/op and IPC separately for every cell;
no average may hide a failed cell. There is no PAD arm: no locked layout changed.
Do not spend a null measurement accepting the currently failing body audit.
