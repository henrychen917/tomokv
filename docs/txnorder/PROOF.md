# txnorder proof receipt index

**Acceptance is blocked by a reproduced writer-mark/WATCH deadlock.**
[The reproduction](writer-cycle/README.md) includes the precise owner-turn
schedule, final production result, and an unapplied ranking proposal. A
successful falsifier run means the defect was reproduced, not that the server
passed. The owner decision is pending; no permission was inferred from silence.

No server, gate, benchmark, oracle or load generator was run. All builds and
serverless checks used CPUs 48–63 (owner-turn fixtures and GDB execution use
48–55 for eight-core geometry). This report makes no throughput claim.

## Completed checks

| Check | Result | Receipt |
|---|---|---|
| `make all`, every `job_production_units` target, `mdbqsbr-live-arms` | Build exit 0; all 31 freshness checks exit 0 | [Build](build-final/result.json) |
| Gate self-tests | 66 tests passed | [Log](gates-test-final.log) |
| Directed/owner-turn regressions | 28/28 passed; F1/F2/F4/F5/F6/F8, claims, placement, one cut, group/wound/retirement, WATCH, script and related controls | [Final units](units-final/results.json) |
| F1/F4/F6 negative controls | Intended PRE assertions fail | [Step 1](step1/) |
| F2 before APPLY-yield change | Intended failure reproduced before the change | [Step 3](step3/) |
| F5/F8 negative controls | Intended assertions fail on frozen merged PRE | [PRE controls](f5-f8-pre/results.json) |
| `lbstall_artifacts.py compare` | 601/601 + 603/603 canonical hot bodies equal | [Hot inventory](identity-final/hot.json) |
| `ccfix_audit.py` selected hot set | 1208/1208 equal | [Summary](identity-final/full/summary.json) |
| Full ccfix exit status | Exit 1: intended DEBUG changes are outside the checker's unchanged CONFIG/INFO/ACL exception | [Commands](identity-final/commands.json) |
| `linked_bytes.py` | Exit 1: runtime sections differ; no whole-binary identity claimed | [Linked sections](identity-final/linked.json) |
| Scatter constructor/destructor/destroy | All 12 named bodies/clones equal, both namespaces | [Inventory](identity-final/scatter/inventory.json) |
| Layout | All locked sizes/offsets and TLS equal; reservation 88, ScatterState 896, script intent 32, pending state 1352 | [Layout](layout/result.json) |
| INFO schema and documentation self-tests | Passed | [INFO](infofields-final.log), [docs](docs-drift-final.log) |
| Label fixture | All 656 source declarations match; checker refuses protected EXPECT_FULL=642 | [Ledger](ledger-final.json), [log](ledger-check-final.log) |

The full changed-function list is [function-changes.md](identity-final/function-changes.md),
with [all 389 canonical changes](identity-final/full/changed-bodies.json) and both
body inventories retained. Intentional cold counter growth changes
`TxnOwnerCounters` 128→192 and `Server` 133376→141568 bytes. `MultiRetryNode`
shrinks 32→24; its lane stays 64. These are outside the locked layouts and
are disclosed in the layout inventory. The normal CONFIG handler also changes
7393→7347 bytes through compiler mutex inlining; it was not silently called
identical. Source changes do not touch ex_loop.h, io_loop.h or AOF staging.

## Instruction evidence and limits

The production-object fixtures retain each executed instruction, including
NOPs, and compare both namespaces and modes. They do not start workers or
listeners. These are named-function counts, not whole-operation instructions/op
or rates. The 264 txnfix3 fixture pairs are repeated, plus four atomic-1 MSET
pairs covering installation, completion and commit flush. See
[final trace summary](paths-final/summary.json). Raw GDB logs and trace maps
are compressed without dropping instructions. The trace guard recorded a
relink of build/tomokv, which these fixtures never link or execute. Every one
of their 200 production object inputs stayed unchanged; the
[reconciliation](paths-final/relink-reconciliation.json) binds those objects
to the stable final identity audit and POST digest.

The first complete audit passed selected hot identity but failed DB0 MGET by
one instruction per fragment. That rejected receipt remains in [identity](identity/STATUS.md).
Compiler-isolation trials and disassemblies remain in [codegen-trials](codegen-trials/).
The selected source keeps the normal claim helper cold and restores the DB0
owner argument's stack residence; the instruction fixture counts that store.
No main-command gain is claimed from those counts.

The complete family is not a zero-increase result for every named function:
normal DEL/UNLINK gain one sampled instruction per fragment, and normal KEYS/
RANDOMKEY move a scan loop into a separately named helper (total sampled count
falls, but the new helper's named count rises). The raw comparison preserves
both facts. They need review and a matched-load verdict; neither selected-hot
identity nor aggregate instruction savings overrides a cost failure.

## Controls and owner work

[Binary digests](binaries.json) identify the exact artifacts. PAD is explicitly
**type A, limited aggregate text-size behavior control**: PRE behavior padded
to POST's total .text size. [Receipt](pad-a-size/build.json). It does **not**
match internal function addresses or the changed cold Server layout and is
therefore **not a complete layout twin**. Do not use it to certify a layout-
independent merit result. The isolated [barrier-removed control](barrier-control/build.json)
is built for the MSETNX witness; it has not been started.

[owner-proof-plan.json](owner-proof-plan.json) carries 215 pending parameter rows
from every txnfix2/txnfix3 handoff family plus the new rows: txniso all modes,
atomics and database counts; AOF companions; all 8192-repeat EXEC/bare NX cells;
original EXEC audits and PRE controls; Stage B/mover and G1–G6 families;
Redis-7.4 differential matrix and armed read-local witnesses; broad batteries;
writer/AOF/snapshot/FLIP companions; fresh WATCH boots and crossed WATCH;
and each new a–d family on PRE and POST. It contains no copied pass verdicts.
Missing PRE instrumentation is not a valid negative control; `--pre` now runs
supported semantic checks and a PRE semantic pass invalidates the control.

Original held-window audits that synchronously wait for a plain writer before
releasing their group can now time out under D1. Capture that finding; do not
waive it or call it a pass. Any needed harness sequencing adaptation must retain
the exact data assertions and a real held-window witness. Runtime claims, the
new-row PRE failures/POST passes, complete PAD evidence and merit remain pending.

The design also leaves expiry/eviction versus read claims unresolved, and the
existing MGET cut does not retain history for arbitrary unversioned writes.
Those limits and the D1/D3 contracts are in [CONFIGURATION.md](../CONFIGURATION.md).
F3 blind-group AOF order remains the separate aoforder lane.
