**ccfix2 status: committed WIP. Do not merge this as a completed CC11/CC18 fix.** Executed errors now increment real counters, and the forced pending-record scatter cases emit the expected keymisses. The required success-path identity and exact instruction-count acceptance are **not met**. Redis commandstats coverage also has remaining gaps described below. No server, load generator, live differential, throughput benchmark, or gate was run. The only perf-event executions were the explicitly requested serverless instruction witnesses.

`origin/cpp` was fetched and merged first, producing `2d3113d44`. The merge-base PRE is `9d957b9fbb7a6eadace068b9615eef81b0dd6686`. BASE is that merged tree before ccfix2. Production POST source is `467798e09`; later changes add test assertions and receipts. The measured ccfix binary from the addendum is preserved unchanged. Nothing was pushed.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE, merge-base | `build/ccfix2/PRE/tomokv` | `76a4a1b3a162f468402d4c4d7f8f18a912d9e8476e4d8fdcfde76f67aada7ea1` |
| BASE, ccfix plus required mainline merge | `build/ccfix2/BASE/tomokv` | `5f57acf279fb1773ea0e5d714964488abef6c204336ea72d4cfd6c6a16a4fdbe` |
| POST | `build/ccfix2/POST/tomokv` | `c494caed88c60e4ed6b4d3dfad844c39059d6b770c83a80813519d35d1ef6059` |
| Default review copy | `build/tomokv` | `c494caed88c60e4ed6b4d3dfad844c39059d6b770c83a80813519d35d1ef6059` |
| Measured ccfix reference | `build/ccfix/POST/tomokv` | `ff58fe0503a9032bf754d4714078f9f9760b4b62b15e40659b60dca0ec852084` |

[Build manifest](docs/ccfix2/build-manifest.json) includes compiler and section sizes. Both database namespaces are linked. Release builds used the repository Makefile and GCC 13.3.0. PRE and BASE were built from archived source trees; POST was built with `make BUILD_ROOT=build/ccfix2/POST all`. Builds used CPUs 0–15, instruction witnesses CPU 24, and the serverless atomic fixture CPUs 16–23. No work was assigned to the maintainer's reserved cores 112–127.

All locked instance layouts remain unchanged in both namespaces: `Op=336`, `Client=1984`, `ThreadCtx=1408`, `Shard=1440`, `FlatStore=944`, `Rob<64>=192`, `AtomicEntry=144`, `Config=624`. The existing `tests/multidb_layout.cc` also confirms every exported layout value matches PRE/BASE/POST; see [layout receipt](docs/ccfix2/layout.json). BASE→POST ELF `.text` changes 7,799,116→7,797,676 bytes (−1,440); GNU `size` text changes 8,818,685→8,818,221, and BSS grows 32 bytes for TLS state across two namespaces. No PAD binary was produced. Unchanged object sizes do not establish immunity to changed text placement; a padding control remains outstanding if this implementation is retained for measurement.

The implementation uses an error-only `Op::Sink::append_error` with the same argument ABI as `append`, plus `begin_error` for assembled error lines. Generic append and successful reply helpers do not inspect counters. The definitions remain visible in the header while out of line: an external-only declaration caused GCC escape analysis to alter GET's success tail; the visible definition restores GET and SET's admitted error-callee-only differences. Thread-local ownership is bound once at worker placement, including fused/split and role changes. The hook increments the existing per-thread failed plane for `op.spec->id`. It parses already emitted RESP bytes to avoid counting several ordinary error members as several failed calls, while skipping bulk payloads that merely contain an error-looking string. ACL/NOAUTH dispatch rejections use a scoped suppression and retain `rejected_calls` attribution.

WRONGTYPE, syntax, range, OOM and NOSCRIPT helpers, assembled script/function/stream errors, and Lua error-table serialization now reach the hook. EXEC's collected member bytes are copied without counting them against EXEC again; actual EXEC/EXECABORT errors use EXEC's own hook. INFO retains the agreed format `cmdstat_<name>:calls=<n>,rejected_calls=<n>,failed_calls=<n>` without timing fields. `failed_calls` is no longer a constant zero.

The scatter change uses the object returned by `atomic_find_tracked`, at the existing fragment epoch, and emits a missing-source notification through the existing classifier. It does not perform a second potentially different lookup. COPY records one source miss; SINTERSTORE and BITOP with two missing sources record two; destination misses remain suppressed. However, the new `notify && pending_reads && !object` condition adds work to the pending-record lookup when notifications are disabled. **This does not satisfy the disabled-path requirement.** The isolated notification-gate instruction witnesses cannot certify the entire scatter lookup.

The remaining work is concrete:

- Restore all ordinary success-body instructions, including incidental compiler inlining changes in APPEND/GETEX, HLEN, dispatch, store helpers and other bodies identified in the audit. GET/SET alone are insufficient.
- Move the pending-record notification work behind an already selected armed path, retaining the exact resolved object and source/destination classification, and prove the whole disabled lookup remains unchanged.
- Complete Redis's `ignore_error_stats_update` semantics for forwarded Lua errors. Redis may increment the outer command once per flagged returned error, whereas this implementation deduplicates all returned errors. One returned nested error passes; multiple forwarded errors are not claimed compatible.
- Existing command-call accounting does not count nested script commands at the handler invocation, and queued MULTI commands are counted at queue time. Aborted queues therefore need a separate calls/rejections audit. Pre-dispatch rejection coverage beyond the inherited ACL/NOAUTH sites is not complete. The lane must not be described as matching every Redis rejection/failure case.
- Satisfy the exact instruction witness, build any required padding control, and obtain the maintainer's wire/gate/null results. No performance acceptance is claimed here.

The source oracle inspected is local vanilla Redis 7.4.10 at `/home/user/Projects/redis`, especially `networking.c:afterErrorReply`, `server.c:incrCommandStatsOnError/call`, `multi.c`, and `script_lua.c`. These findings are source-derived, not reported live observations.

The serverless proofs are reproducible with `python3 tools/ccfix2_prove.py units`. The fixture initializes 16 shards at eight-CPU gate geometry but starts no listener, worker, timer or ring. It directly runs real owner phases from the existing atomic fixture and leaves the source writer undecided. It checks that records exist on the exact source keys, that the reader's cut resolves their predecessors as missing, and that emitted events and batch keys match exactly. Both 1s and 2s pass. An unarmed fixture fails rather than skipping.

| Proof | Result |
|---|---|
| Original ccfix flags/classifier/storage assertions plus real GET/SET/EVALSHA error producers | PASS |
| Same flag assertions against merge-base headers | Expected assertion failure; POST passes |
| New error test linked to BASE command bodies with the new cold counter implementation | Expected assertion failure on missing executed-error count |
| COPY / SINTERSTORE / BITOP with actual pending source records | PASS, counts 1 / 2 / 2 in 1s and 2s |
| Pending-record fixture with arming removed | Expected failure: source record absent |
| Same fixture with only the new scatter notification block removed | Expected failure: keymiss count |
| EXEC failing member, EXEC without MULTI, EXECABORT discarding a member | PASS; inner GET and EXEC attribution checked separately |
| Ordinary Lua array with two error elements, one returned nested WRONGTYPE | PASS for those specific cases |
| Auditor admits only the error callee, rejects opcode mutation and unrelated target mutation | PASS |

Logs and controls are under [docs/ccfix2](docs/ccfix2); throwaway control sources and executables remain under `build/ccfix2`. The controls are never used as production binaries. Python compilation and `git diff --check` pass.

`python3 tools/ccfix2_prove.py instructions` runs the unchanged five 100,000-call production witnesses in both namespaces. The final complete run is below; CSV files and [all six results](docs/ccfix2/instruction-comparison.json) retain exact integer counts. The assertion **fails**, without a tolerance or rounding. An earlier diagnostic rerun also recorded one-instruction differences in notification intervals; [first attempt](docs/ccfix2/instructions-first-attempt.txt) and `instructions-recheck-*.csv` retain them. No clean-run selection is used to claim a pass.

| Interval, 100,000 calls | PRE | BASE | POST | db0 PRE / BASE / POST |
|---|---:|---:|---:|---|
| off/keymiss | 1,800,053 | 1,800,053 | 1,800,053 | 1,800,053 each |
| off/string | 1,800,053 | 1,800,053 | 1,800,053 | 1,800,053 each |
| save-only/keymiss | 2,000,053 | 2,000,053 | 2,000,053 | 2,000,053 each |
| save-only/string | 2,400,053 | 2,400,053 | 2,400,053 | 2,400,053 each |
| note_command | 700,038 | 700,038 | **700,039** | 700,038 each |

`tools/ccfix_audit.py --error-callees` retains all opcode/register/immediate/member-offset comparisons and resolves named relocation targets. The only admitted error-target substitution is `Op::Sink::append`→`append_error`. Same-section RIP-relative LEA addresses are resolved to exact function identities, including aliases; this removes address-only wrapper false positives without masking instructions. [Negative-control receipt](docs/ccfix2/audit-negative-control.json) records rejected opcode and unrelated-callee changes.

| Comparison | Full hot inventory accepted | Original 1,486 hot occurrences accepted |
|---|---:|---:|
| Measured ccfix→BASE, inherited merge changes | 1,447 / 1,491 | 1,447 / 1,486 |
| BASE→POST, this lane | **1,459 / 1,492** | **1,453 / 1,486** |
| Measured ccfix→POST, addendum reference | **1,434 / 1,491** | **1,434 / 1,486** |
| Merge-base PRE→POST | 1,459 / 1,492 | See full inventory |

The lane's full comparison has 17,061 function occurrences, 783 changed: 317 classified `error-branch callee only`, 466 `other`. Of 1,213 command-handler occurrences, 948 match outright and 224 differ only by the admitted error callee; **41 are classified other**, with 34 outside CONFIG/INFO/ACL. The requested empty-other condition fails. Every changed body is listed and classified in [final-audit/changed-bodies.json](docs/ccfix2/final-audit/changed-bodies.json). Full bodies and summaries are retained for [this lane](docs/ccfix2/final-audit/summary.json), [inherited merge changes](docs/ccfix2/inherited-audit/summary.json), [the measured reference](docs/ccfix2/measured-base-audit/summary.json), and [merge-base PRE](docs/ccfix2/merge-base-audit/summary.json). The [historical inventory projection](docs/ccfix2/historical-hot-inventory.json) retains all original 1,486 occurrences; none was dropped to improve the result.

The unmodified `tests/r7shadow_noop.py --inventory splitlocal` reports **359/396**, `strict_noop=False`, against BASE→POST. [Log](docs/ccfix2/splitlocal-audit.log) and [complete compressed result](docs/ccfix2/splitlocal-audit.json.gz) are committed. Its raw disassemblies and per-body diffs remain in `build/ccfix2/splitlocal-receipts` to avoid committing 260 MB of generated text. This result is not relabelled green merely because some differences are expected error callees.

The existing differential suite now requires, on both endpoints after RESETSTAT: ACL-denied GET `(calls,rejected,failed)=(0,1,0)`, executed WRONGTYPE GET `(1,1,1)`, successful missing GET `(2,1,1)`, and an EXEC containing WRONGTYPE GET `(3,1,2)`, with EXEC `(1,0,0)`. EXEC without MULTI then gives EXEC `(2,0,1)`. Oracle timing fields are ignored; target field names/order are exact. The pending-record wire cases use `_lib.armed(..., 'ATOMIC-COMMIT-HOLD', 1)` and owner-key helpers, require pending-record and predecessor-read witnesses, exclude localfast, release the latch in `finally`, and compare exact notification frames with Redis. Atomic=0 has no pending-record mechanism; atomic=1 must open the window or fail.

Maintainer wire commands, sequentially on the scheduled box:

```sh
REDIS74_ROOT=/home/user/Projects/redis GATE_LOAD_CORES=8-15 \
GATE_DIFFER_GEOMETRY=split GATE_DIFFER_OUT=build/ccfix2/differ-split \
tests/differ_gate.sh "$PWD/build/ccfix2/POST/tomokv" 7899 7900 0-7 6:2

REDIS74_ROOT=/home/user/Projects/redis GATE_LOAD_CORES=8-15 \
GATE_DIFFER_GEOMETRY=armed-fused GATE_DIFFER_OUT=build/ccfix2/differ-fused \
tests/differ_gate.sh "$PWD/build/ccfix2/POST/tomokv" 7899 7900 0-7 6:2
```

These use the differ harness to own both listener lifetimes and its existing ACL-file fixture. Neither was executed by the lane. Both-mode boots and the live wire outcomes remain unverified here.

Gate rows are **+0 quick / +0 full**. Tests extend existing differential rows: `tests/gate.sh:3380` (`differ-split`) and `:3391` (`differ-armed`), both after the quick-tier exit at `:3348`. The constants remain untouched at 499/516; no count adjustment is requested.

For the lane's eventual performance null, use the gate's own ABBA instrument and unchanged [14 generic cells](docs/ccfix/generic14.cells.txt): `h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64`. The primary comparison is merged BASE versus POST, isolating this error-hook/scatter change. Also retain measured ccfix versus BASE to expose the inherited merge delta; a merge-base PRE→POST result alone cannot satisfy the addendum. Record per-cell matched-load rate, cycles/op, instructions/op and IPC, with exact binary hashes and arm order. Apply the mainline null's existing acceptance band per cell; do not average a regression away across cells. Performance cannot waive the failed success-byte or semantic requirements. There are no requested rate measurements while this lane is running, and no measurement result is claimed.
