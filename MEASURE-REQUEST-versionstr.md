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
