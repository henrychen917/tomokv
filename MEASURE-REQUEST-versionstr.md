## 2026-10-08 — versionstr2

Static byte verdict: **PASS**. Live differential: **BLOCKED by four quiet-preflight refusals over ten minutes (0/64 legs run)**. This section supersedes the predecessor's failed byte verdict below. The unchanged proof tools and all current evidence are in `docs/versionstr/versionstr2/`.

Merged `origin/cpp` at entry (`c1f4f7d9c`), then fetched/merged again immediately before proof; origin remained `db86e5b4a051929c68108d33b1dc358428c59bca`, which is PRE. Production isolation is commit `bac3c0066`; the differential footer addition is `1905cec03`. The proof was recorded in `3243ca322`.

The diagnosis holds: restoring the two main-visible headers and the baseline compiler flags restores every ordinary body. `src/main.cc`, `src/core/config.h`, and `src/core/boot_support.h` are byte-identical to PRE. Both complete preprocessed main translation units are byte-identical too (`main-preprocessed.json`). Main's compiler budgets are the merged baseline's 146409 (multi-db) and 146203 (DB0); this lane adds no compiler-budget override.

There is no existing argc/argv pre-parse hook. `src/core/version.cc` therefore defines exactly one cold out-of-line function, `__wrap_main`; the release link uses GNU ld's `--wrap=main` to reach it from the C runtime. It prints the shared product/compatibility constants and exits for argv[1] `--version` or `-v`; otherwise it forwards argc/argv unchanged to `__real_main` and preserves its return status. This gives entry-option semantics: flag-looking option values and configuration-file contents are not scanned. The banner now precedes argument parsing, so it also appears before help/configuration errors. The DB0-to-multidb boot handoff does not re-enter the wrapper. No main-visible declaration or header edit remains. `version.h` is included only by `t_server.cc`, `server_tail.cc`, and `version.cc`.

| Static quantity | PRE | POST / verdict |
| --- | ---: | ---: |
| Hot bodies, raw and relocation-resolved | 1492 | 1492 equal |
| Ordinary emitted bodies | 4836 | 4836 equal |
| Ordinary instruction counts per body | 4836 | 4836 equal |
| Ordinary instruction total | 1,136,538 | 1,136,538 |
| Linked ordinary selections proven | 3021 | 3021 |
| Locked sizes/member layouts (both namespaces) | 16 types | all equal |
| Unexplained changes | 0 | 0 |
| `.text` bytes | 7,820,053 | 7,820,213 |

The two tools compare 94 common objects. The only eight changed existing bodies are INFO, its cold clone, HELLO, and LOLWUT in each namespace; every body and reason is listed in `docs/versionstr/versionstr2/changed-bodies.md`. The added objects are separately audited in `new-objects.json`: `src/core/version.o` is empty and `db0/src/core/version.o` contains only the 136-byte entry/banner/version wrapper. No ordinary function hides in a POST-only object. Both main objects, all four formerly drifting WbEngine lambdas, FlatStore::hash_key, and both AofProducer destructor symbols now match. The original proof tools are unchanged, with hashes in `proof-tools.json`.

```
PRE  cf8331b2675e87349528d35e8b1497a791361eaa77963d27db2c455032c32907
POST d7343c34a352b7e57b7db2f5493fdbf058e482d16d7f01646226b8703ef0845b
```

Both arms were fully rebuilt with GCC 13.3.0: `build/versionstr2/PRE` from a merge-base archive and `build/versionstr2/POST` from this branch. Build logs are retained (no warnings/errors). No throughput measurement or performance gain is claimed; no PAD arm is proposed.

Reproduce the static proofs:

```sh
python3 tools/lbstall_artifacts.py compare build/versionstr2/PRE build/versionstr2/POST build/versionstr2/hot-bodies.json
python3 tools/versionstr_artifacts.py build/versionstr2/PRE build/versionstr2/POST build/versionstr2/proof
```

Serverless checks pass: INFO controls 9/9; differential fanout controls 19/19; DEBUG LOAD controls 13/13; configuration parser and all 512 resolved geometry presentations; both CLI aliases. Seven stub-main integration cases prove early exit, correct forwarding (including `--version` as an option value), and return-status propagation. Omitting the wrapper makes the version check fail (exit 23 and the wrong output). The predecessor's banner assertion moved out of the geometry helper because that helper is again byte-identical to PRE; the live replay checks exactly one banner at each real boot.

Live replay uses `docs/versionstr/versionstr2/live.py`: cores 112–119 for the eight-thread/16-shard target, 120–126 for the differential driver, 127 for the Redis oracle. It requests DB0 and multi-db (`--databases 1/16`), split 6:2 and fused/read-local=1, atomic 0/1, permanent seeds 7/19/20/23, and RESP2/RESP3 (64 legs total). Every leg calls the existing infofix suite, whose properties verify both HELLO protocols, exact target version fields, and both product-specific LOLWUT footers. Quiet preflight gets the initial attempt plus three retries 200 seconds apart. No refusal counts as a live pass. The attempt ran at 10:51:50, 10:55:10, 10:58:30 and 11:01:50 UTC on 2026-10-08; both port/core preflights returned 2 on every attempt. Sibling compiler processes were recorded during retries 1 and 2; the last retry still found busy cores. All four logs and the failing driver transcript are in `docs/versionstr/versionstr2/live-preflight/`; the machine-readable outcome is `live-result.json`. No target or oracle was started, so **0/64 cells ran**. This is a recorded infrastructure refusal, not a passing differential. The oracle executable's exact CLI value is `7.4.10` (full line in `cli.json`); its live INFO and HELLO values were **not observed**.

Maintainer follow-up on an allocated quiet box (fresh output directory required):

```sh
python3 -u docs/versionstr/versionstr2/live.py build/versionstr2/POST/tomokv build/versionstr2/live-retry
```

The replay must finish all 64 cells with zero differences, exactly one version banner per boot, and nonzero read-local witnesses in the four fused boots. Then run the normal maintainer-owned iteration gate. No throughput comparison is requested for this identity correction.

Version search uses `grep`, including gunzipped historical evidence and literal, escaped, hex, octal, URL/HTML and base64 spellings. The active old spelling remains only in deliberate INFO/HELLO negative controls. Other hits are immutable historical measurements/reports, predecessor receipts, and the search's own needle; they were not rewritten as new observations. No extra encoded old spelling was found. Receipts and exact patterns are retained alongside the proof.

Rows: **+0 quick / +0 full**. `tests/gate.sh` is unchanged from the merge-base: EXPECT_QUICK=502, EXPECT_FULL=519. Config presentation remains in the existing parser row (definition at 1259–1262, collected at 3230, before quick exit at 3402–3406). Existing differential jobs are collected at 3434/3445, after that exit. No row was added or retired and no EXPECT edit is requested. The full gate remains maintainer-owned and was not run.

---

## Predecessor versionstr — historical failed attempt

Lane versionstr — WIP, not ready to merge. The version fix and regression checks are implemented and built, but the mandatory ordinary-dispatch byte-identity proof still FAILS. No server, benchmark, or gate was started. No push was made.

PRE is merge-base `5efc5414d3d6107b5e7e29f2404e585806c823ec`. `origin/cpp` was fetched and merged at entry, again before proof, and checked again at the final proof; it stayed at that commit. See `docs/versionstr/final-merge.txt`.

The constants are defined once in `src/core/version.h`: `kTomoVersion = "1.0-cpp"` and `kRedisCompatVersion = "7.4.10"`. They are immutable constexpr string pointers, following the previous constant's representation.

| Site | Final change |
| --- | --- |
| `src/cmd/t_server.cc`, HELLO | `version` uses `kRedisCompatVersion` in both RESP modes. |
| `src/cmd/t_server.cc`, INFO Server | `redis_version` uses compatibility; `tomokv_version` uses product identity. |
| `src/cmd/server_tail.cc`, LOLWUT | The trailing `TomoKV ver.` art footer uses `kTomoVersion`; it identifies our product. |
| `src/core/boot_support.h` | A version line precedes the existing geometry banner: `TomoKV 1.0-cpp (Redis 7.4.10 compatible)`. |
| `src/core/config.h` | Existing option parser handles `--version` and `-v`, printing both versions and returning before server initialization. |
| `Makefile` | Only the two main.cc compilation budgets change: 146401→146418 and 146203→146220. The latter is an incomplete byte-preservation attempt, not an accepted optimization. |
| `tests/auth.py` | HELLO 2 AUTH and HELLO 3 AUTH pin the compatibility string. |
| `tests/servertail.py` | Existing LOLWUT assertions pin the product-version footer. |
| `tests/boot_support_checks.inc` | Existing presentation checks verify the version line in all 512 geometry cases. |
| `tests/differ.py` | Existing infofix properties check INFO version grammar, identity, field placement/order, and HELLO 2/3 versions; restore the original protocol afterward. |
| `tests/infofields_test.py` | Serverless controls reject old/suffixed/malformed/wrong versions, missing fields, wrong protocol/shape and malformed CRLF. |
| `tests/debug_load_test.py`, `tests/differ_fanout_test.py` | Active INFO fixtures use 7.4.10. |
| `tools/versionstr_smoke.py` | Optional redis-py connection smoke, with an explicit skip when absent; never installs or starts a server. |
| `tools/versionstr_artifacts.py`, `docs/versionstr/budget.py` | Reproducible offline body/link/layout audit and TU-local compiler-budget trials. |

INFO's 38 Server-branch string literals are identical to PRE, in the same order, including CRLF and `redis_mode:standalone`; only version arguments changed. `docs/versionstr/schema-proof.json` records the source comparison. The differential requires all 12 supported shared Redis Server field names on both sides and preserves their section placement. Complete Server-field-set equality is not a property of PRE: TomoKV has its own telemetry and Redis has additional build/OS/listener fields. This lane does not add fabricated telemetry to claim full-set equality.

Live differential result: PENDING, not passed. The oracle binary's `--version` reports:

```
Redis server v=7.4.10 sha=f103d127:0 malloc=jemalloc-5.3.0 bits=64 build=f39586913084a746
```

No Redis/TomoKV listener was present. An INFO SERVER attempt at the default oracle endpoint 127.0.0.1:6379 returned connection refused (exit 1). Both transcripts and the oracle binary SHA are under `docs/versionstr/`. Existing infofix checks require target 7.4.10 exactly; they permit only a different numeric oracle 7.4.x patch and print it explicitly. Both HELLO versions must equal their own INFO version. A wider version regex was not substituted for an exact expectation.

The redis-py smoke transcript is retained verbatim in `docs/versionstr/redis-py-smoke.txt`:

```
$ python3 -m pip show redis
WARNING: Package(s) not found: redis
exit status: 1

$ python3 tools/versionstr_smoke.py 127.0.0.1 6379
SKIP: redis-py is absent; no package installed and no connection attempted.
exit status: 0
```

Serverless verification: INFO controls 9/9; DEBUG LOAD fixture controls 13/13; differential fanout controls 19/19; configuration/presentation checks pass, including all 512 geometry cases. Python syntax checks and `git diff --check` pass. `--version` and `-v` both print the exact requested line. These are not live server or gate results.

Version search receipts are `old-version-search.txt`, `encoded-version-search.txt`, and `redis-version-search.txt`. The only retained old-version text outside this report/evidence is eight recorded values in historical `docs/ccfix5/null-l1-geometry.json`, plus deliberate negative controls in `tests/infofields_test.py`. Historical measured values were not rewritten into fictitious POST observations. No additional escaped spelling was found. Existing 7.4.x oracle selectors were not widened.

Gate rows: +0 quick / +0 full. `tests/gate.sh` is unchanged: EXPECT_QUICK=500 and EXPECT_FULL=517. The affected existing config-parser row is at lines 1255–1256; feature batteries at lines 777–784 remain collected before the quick exit at lines 3389–3393. Differential properties ride the existing infofix invocation. No row or count change is requested.

Builds: PRE was built from a `git archive` of the merge-base into `build/versionstr/PRE`. POST was built into `build/versionstr/POST`; `build/tomokv` is byte-equal to POST. The final DB0 main.o uses the recorded 146220 trial (same release flags plus an IPA dump); only that changed TU was substituted and the normal Makefile link was rerun. A clean build with the committed Makefile reproduces the selected flags. Build logs and all rejected compiler trials remain under `build/versionstr/`. The committed budget search summary records unsuccessful candidates without claiming success.

Binary SHA-256:

```
PRE  22e5ba97c9404a50f73ba1105a7749bc4a14b8c5b428e17e2994c0ccaf87778e
POST 2f8aeac8a9a59c1a0217738004394f1761ef57cff959e9f433f9bf21eeb373dc
```

Reproduce the final static proofs without starting a server:

```sh
python3 tools/lbstall_artifacts.py compare build/versionstr/PRE build/versionstr/POST docs/versionstr/hot-bodies.json
python3 tools/versionstr_artifacts.py build/versionstr/PRE build/versionstr/POST docs/versionstr/final-proof
```

The first tool must eventually report every hot body equal after resolving relocations; the second must report every ordinary body/link selection equal, unchanged instruction counts, unchanged layouts, and no unexplained changes. Current failures are blocking, not waived. Every changed body and its reason/status is listed in `docs/versionstr/changed-bodies.md`; full machine-readable records are in `docs/versionstr/final-proof/`.

No PAD arm is proposed: the eight locked class sizes and member layouts are unchanged in both database namespaces. No performance improvement is claimed. The rejected compiler drift is not justified by the cold nature of INFO/HELLO.

Maintainer request, after the byte-proof blocker is resolved: use gate geometry (8 cores, 16 shards; split 6 io + 2 ex; fused with read-local armed), both atomic values and database variants. On existing maintainer-owned target/oracle listeners run `tests/differ.py TARGET_HOST TARGET_PORT ORACLE_HOST ORACLE_PORT infofix 7` and the same command with `-3`; each invocation probes HELLO 2 and 3. Exercise the existing auth, servertail and INFO rows and then the normal iteration gate. POST must emit the exact two identities and produce zero differential errors; PRE must fail the new exact-version check. If redis-py becomes available, run `tools/versionstr_smoke.py TARGET_HOST TARGET_PORT` and retain output. Do not install it for this lane. Append live results to MEASURE-RESULT. No throughput measurement is requested for this identity fix.

Final byte verdict: **FAIL**. Hot inventory: 1488/1492 relocation-resolved bodies equal (1484 raw equal); four DB0 WbEngine lambda bodies differ. Broader inventory: 4831/4836 ordinary bodies equal, 3016/3021 linked ordinary bodies proven; the additional ordinary mismatch is DB0 FlatStore::hash_key. Two AofProducer destructor symbols also drift. There are 33 changed emitted bodies total, seven outside the edited cold functions. All 94 objects were compared. All eight locked sizes and member layouts match in both namespaces.

| Static quantity | PRE | POST |
| --- | ---: | ---: |
| .text bytes | 7817349 | 7817557 |
| Ordinary instruction inventory | 1136512 | 1136497 |

These instruction counts do not establish a performance verdict. The +208-byte cold/text change has no associated performance claim; no measurement was run. The four lambda bodies swap between 537 and 824 bytes; preserving the global instruction total would not satisfy the per-body requirement.

## 2026-10-09 — versionstr3

Static byte verdict: **PASS**. Default build and all current gate unit/witness targets: **PASS**. Partial gate: **BLOCKED by four quiet/port preflight refusals over ten minutes (0/18 formerly failing rows rerun)**. Evidence is in `docs/versionstr/versionstr3/`.

Merged `origin/cpp` at entry (`92e716dc6`), preserving both sides of the `MEASURE-REQUEST` report conflict, and fetched/merged again before final proof. PRE is merge-base `dab7409642bf0a6d125fb5f479e6d190c7636083`. The Makefile repair is `f1066d0ff`. The protected `src/main.cc`, `src/core/config.h`, and `src/core/boot_support.h` match this merge-base exactly; `src/core/version.cc` matches versionstr2 (`b812934fa`) exactly. The proof tools are unchanged.

**Cause and repair.** `SRC += src/core/version.cc` put the wrapper in the shared object lists. The multi-database object is empty, but the DB0 object defines `__wrap_main` and refers to `__real_main`. Unit links do not pass `--wrap=main`. Replaying the original DB0 exbatch link recipe against its cached objects reproduced the undefined reference exactly (`reproduce-db0-link.log`). `SERVER_ONLY_SRC`, `SERVER_ONLY_OBJ`, and `DB0_SERVER_ONLY_OBJ` now keep the object out of the shared unit lists and include it explicitly in the wrapped server link. All 96 server objects retain their exact original order. No wrapper semantics or production source changed in this repair.

**Build proof.** `build-inventory.json`, `expanded-unit-targets.txt`, and `unit-build-summary.json` record the targets derived from the gate's build paths/make invocations and every direct `DB0_TEST_OBJ` consumer. The default target and 45 current targets pass, including a separate successful `make build/exbatch-db0-unit`. All 11 current DB0 consumers have neither `__wrap_main` nor `__real_main` in their symbol tables. The gate's direct foreign-read compile, ASAN build, core/waits TSan builds, and both MDBQSBR boot-control builds also pass. The newly merged LB unit-control recipe required `mkdir -p build/lbosc3` before its log redirection; this artifact-directory preparation is recorded, and no unrelated Makefile rule was changed.

The initial 46-target batch also attempted the non-gate historical `build/flushfix-pre-unit`. That target fails before linking because its frozen `e279aeb4c` source references removed `ReadLocalStats::mget_generation_retries` and `info_stats_sample_ops`. Both namespace compilations fail with identical diagnostics against fresh PRE and POST headers (`legacy-flushfix.json`). This is retained as a failure, not counted as a passing build. The gate uses the current `build/flushfix-units`, which builds successfully. The complete initial build log and the successful current-target replay are retained.

| Static quantity | PRE | POST / verdict |
| --- | ---: | ---: |
| Hot bodies, raw and relocation-resolved | 1492 | 1492 equal |
| Ordinary emitted bodies, relocation-resolved | 4836 | 4836 equal |
| Ordinary emitted bodies, raw | 4836 | 4833 equal |
| Ordinary per-body instruction counts | 4836 | 4836 equal |
| Ordinary instruction inventory | 1136424 | 1136424 |
| Linked ordinary bodies proven | 3021 | 3021 |
| Locked sizes/member layouts | Both namespaces | Equal |
| Unexplained changed bodies | 0 | 0 |
| `.text` bytes | 7845285 | 7845445 |
| Makefile-only relink, complete ELF | Old link recipe | Byte-identical |

Both unchanged byte tools exit 0. They compare 94 common objects and find exactly eight changed existing bodies: INFO (including its cold clone), HELLO, and LOLWUT in both namespaces. The only new objects are the empty multi-db version object and the 136-byte DB0 entry wrapper. `changed-bodies.md`, `new-objects.json`, and `proof/summary.json` contain the details. Relocation normalization is explicit above; the independent Makefile-only check relinks the same fresh objects using the pre-fix Makefile and obtains an identical complete ELF, proving this link-list repair moves no production body.

PRE and POST were freshly compiled. POST is retained at `build/versionstr3/POST/tomokv` and was copied back to the generic `build/tomokv` used by the null item. The initial snapshot was rejected because it observed the output while the linker was writing it; the final snapshot was taken only after make exited, and all proofs were repeated on the completed artifacts.

```text
PRE  build/versionstr3/PRE/tomokv
     6def8f04df33af1c407ed27dbc980e9c34335b40fb935ae0fc4b222f4e582985
POST build/versionstr3/POST/tomokv = build/tomokv = old-recipe relink
     f1800a8e71de7f0644083ec5cd52a339aca0180282d168f8221b75d5a6be400a
```

The corrected gate selection is below. `production_units` is a build prerequisite that the current selector rejects as a direct selection. The additional consuming jobs cover all 18 failures in `gate-run.wumlEk`; the requested release/ASAN batteries and `wb_policy` include live boots.

```sh
GATE_ONLY_JOBS="release_batteries asan_batteries exbatch_units wbland_units wb_rule_units reorder_engagement atomic_units wb_policy" \
  tests/gate.sh iteration --server-cores 112-119 --load-cores 120-127 \
  --server-smt '' --load-smt '' --ports 18340-18342
```

Gate result: **BLOCKED**, with **0/18 previously failing rows executed**. The existing `tools/quietcheck.sh` ran against CPUs 112–127 and all three assigned ports before any gate job could start. Initial admission plus three retries spanned ten minutes:

| UTC, 2026-10-09 | Port 18340 / 18341 / 18342 preflight exit | Finding |
| --- | --- | --- |
| 00:00:43 | 2 / 2 / 2 | Assigned CPUs busy |
| 00:04:03 | 2 / 2 / 2 | Assigned CPUs busy; compiler processes recorded on 120–127 |
| 00:07:23 | 1 / 1 / 2 | Ports 18340/18341 occupied; CPU 123 busy |
| 00:10:43 | 1 / 1 / 2 | Ports 18340/18341 occupied; CPU 123 busy |

The runner exited 2 without invoking the gate or booting a server. `gate-result.json`, all four `gate-quiet-*.log` receipts, and `gate-row-verdicts.json` retain the complete outcome: every formerly failing row is **NOT_RUN**, never counted green. The required 18-row runtime proof remains for the maintainer on the quiet gate geometry. The optional infofix differential was also **not run (0/64 cells)** because admission was unavailable; `live-result.json` records the exact replay command. No listener or other lane's process was stopped to obtain admission.

Rows **+0/+0**; `EXPECT_QUICK=502`, `EXPECT_FULL=519` unchanged. No row was added or retired on either side of the quick-tier exit, and `tests/gate.sh` matches PRE. Grep receipts cover plain, escaped, hex, Unicode, octal, URL, HTML and base64 spellings in `tests/` and `tools/`, including their 24 gzip artifacts. Presentation strings and test assertions were unchanged by versionstr3. No throughput measurement or performance claim is made; no measurement PAD arm is proposed.

**Lesson for the record:** a lane that touches the Makefile must build and run the gate's unit targets, not only its own serverless checks.

## 2026-10-09 — versionstr4

Repair commit: `36cd5c0f1`. The full serverless gate self-test passes (66 top-level tests). Link and static byte proofs pass; final build/handler receipts follow in this section.

Entry HEAD `5911a55b6`; fetched and merged `origin/cpp` (`dab740964`), already up to date. The exact pre-fix TSAN wiring assertion is reproduced in `docs/versionstr/versionstr4/before-fix.log`. Its source is **not a Makefile variable**: `job_core_tsan_build` in `tests/gate.sh` independently expands `src/core/*.cc`, admitting `src/core/version.cc` despite the Makefile's `SERVER_ONLY_SRC` separation. The build now excludes that server entry source before calling `tests/parbuild.sh`; the self-test expected set is unchanged.

The non-server inventory also found two Makefile test-object dependency globs and eight offline unit/control build helpers collecting sources or objects independently. Their build lists now omit the entry wrapper in both namespaces where applicable. Changes in Python files affect build input selection only; runtime checks and byte-comparison logic are untouched. The release link's ordered multi-db/DB0 object lists and both server-only version objects are unchanged. `production.diff` records only these build changes, relative to the entry HEAD.

Rows **+0 quick / +0 full**; EXPECT_QUICK=502 and EXPECT_FULL=519 remain unchanged. No server, benchmark or gate is run by this lane. The first build quiet screen refused admission (exit 2); this is a refusal, not a build failure.
