Lane cd13b — cross-owner GEO metadata and COMMAND LIST ACL category compatibility

PRE is merge-base `9d957b9fbb7a6eadace068b9615eef81b0dd6686`. Fetch and merge of `origin/cpp` were already up to date. The landed cdfix handoff was read. `MEASURE-REQUEST-cmdmeta.md` is absent from this origin/cpp revision, so its “One unrelated pre-existing difference” was read from local branch `cx-cmdmeta`; that branch was not merged. No push.

The task's STORE no-demotion premise conflicts with both the landed cdfix implementation and Redis 7.4.10. Redis `geo.c:829–831` creates a fresh zset, runs `zsetConvertToListpackIfNeeded`, and replaces through `setKey`; `db.c:262` copies the previous LRU/LFU metadata. Only GEOADD has the no-demotion requirement. This lane preserves local STORE semantics: an expanded destination containing two members is `skiplist` before STORE and `listpack` afterward, on both servers. Changing STORE to retain skiplist would introduce a Redis difference. Live oracle receipts confirm this, rather than relying on source review alone.

| Item | Redis 7.4 | PRE | POST |
| --- | --- | --- | --- |
| CD13b, STORE / STOREDIST / GEOSEARCHSTORE | Preserve the destination's warmed LFU history when replacing its value | Atomic-mode witness: initial 5, warmed 31, replaced 0; all three properties fail | Owner reads current destination metadata immediately before physical installation; ordinary and atomic install paths both preserve warmed 31 |
| Previously expanded STORE destination | Small result may compact | `skiplist` before, `listpack` after | Same as Redis and the local path; no encoding semantic change |
| COMMAND LIST FILTERBY ACLCAT unknown | Empty array in both protocols | Error | Exact `*0\r\n` |
| ACLCAT `string`, `STRING`, `StRiNg` | Case insensitive; same set of 22 command names | Existing case folding is correct | Same case folding; explicit generator assertions retained |

Exact wire frames (CRLF escaped):

| Probe | PRE | POST | Redis oracle |
| --- | --- | --- | --- |
| Unknown category `cd13b-no-such-category` | `-ERR Unknown ACL category 'cd13b-no-such-category'\r\n` | `*0\r\n` | `*0\r\n` |
| Each GEO store count | `:2\r\n` | `:2\r\n` | `:2\r\n` |
| OBJECT FREQ after each store, atomic witness | `:0\r\n` | `:31\r\n` | RESP2 STORE `:38\r\n`, STOREDIST `:35\r\n`, GEOSEARCHSTORE `:31\r\n` |
| OBJECT ENCODING, pre-store expanded destination | `$8\r\nskiplist\r\n` | `$8\r\nskiplist\r\n` | `$8\r\nskiplist\r\n` |
| OBJECT ENCODING, small stored result | `$8\r\nlistpack\r\n` | `$8\r\nlistpack\r\n` | `$8\r\nlistpack\r\n` |

LFU values are stochastic across servers; the check compares each server with its own initial value, not the other server's counter. It first expands to 160 members, shrinks to two and asserts skiplist; 4,096 ZCARD touches must raise FREQ by at least three. Failure to arm retries at most three times with fresh keys and then FAILS. After STORE, FREQ must remain strictly above initial. CONFIG maxmemory/policy are restored in a finally block and test keys are removed.

The only new image field is a boolean in ObjectImage's existing padding. Both arm fixtures assert size 48, entries offset 8, expiry offset 16 and payload offset 24. All public layout locks compile unchanged. The coordinator marks the GEO image; it never reads destination metadata. `geo_store.cc` performs a non-touching owner lookup, ignores an expired resident, and uses the same isolated metadata-copy adapter as cdfix. The predecessor is not mutated. Both `apply_image` and `execute_atomic_apply` invoke it immediately before installation. No reader retry, seqlock, ownership transfer, configuration knob or per-operation path was added. Existing packed-zero-as-uninitialized insertion semantics remain the separate cdfix handoff; this lane does not claim to repair that shared policy.

Cross-owner proof and tests:

The shared wire property asks DEBUG SHARD, which calls the actual FlatStore hash with its current seed, then DEBUG LBSIGNALS for live owner IDs and migration counts. It searches at most 4,096 candidates for different shards AND different owners. The exact `(shard, owner, migrations)` tuples must be identical immediately before and after STORE. It refuses a geometry with fewer than two owners. Redis itself has no TomoKV ownership; oracle keys are chosen with this same witnessed target routing map. Every receipt includes the exact keys and tuples.

Concrete final RESP2 witness (full keys and raw frames in `docs/cd13b/oracle-resp2.log`):

| Operation | Source key | Destination suffix appended to source | Source `(shard, owner, migrations)` | Destination `(shard, owner, migrations)` |
| --- | --- | --- | --- | --- |
| STORE | `cd13b:POST-multi-split-a1-r0-n0-l0:STORE:0:source` | `:destination:0` | `(8,6,1)` | `(13,7,1)` |
| STOREDIST | `cd13b:POST-multi-split-a1-r0-n0-l0:STOREDIST:0:source` | `:destination:3` | `(11,7,1)` | `(6,6,1)` |
| GEOSEARCHSTORE | `cd13b:POST-multi-split-a1-r0-n0-l0:GEOSEARCHSTORE:0:source` | `:destination:1` | `(11,7,1)` | `(0,6,1)` |

Each pair is cross-shard AND cross-owner. The fixture separately asserts this against the actual prepared two-hop scatter key records before invoking production owner phases; the raw wire witness cannot silently select the local path.

The production RESP parser, handlers and scatter owner phases run in `tests/cd13b_unit.cc` through pipes. No TomoKV listener, worker threads, IO ring, server loop, benchmark or gate was booted. Split uses 16 shards / 6 IO + 2 EX; fused uses 16 shards / 8 owners. All builds and serverless checks are pinned to CPUs 112–127. The only live server was vanilla Redis via the differ harness's unchanged guarded oracle boot, identity check and cleanup, explicitly authorized by this task. The helper extracts those harness sections and fails if their boundaries change; it does not run the gate matrix.

Validation receipts:

- `docs/cd13b/matrix.json` and the 32 matching logs: namespaces multi/db0 × split/fused × atomic 0/1 × RESP2/RESP3 × notifications 0/1.
- `docs/cd13b/pre-negative.log`: PRE fails the unknown-category check and all three GEO checks (four required failures). The additional PRE atomic-off receipt resets to initial 5, and the PRE RESP3 receipt also fails all four checks.
- `docs/cd13b/apply-image-only-atomic-negative.log`: the incomplete apply_image-only candidate fails all three atomic-mode GEO checks, proving the additional owner installation is necessary.
- `docs/cd13b/late-owner-metadata.log`: after the coordinator constructs the image, the fixture sets destination metadata to 17. The installed object must contain exactly 17; a coordinator-side copy would retain 31 and FAIL. The shared wire assertions also pass. `late-owner-atomic0.log` proves the same timing boundary with atomics disabled.
- `docs/cd13b/oracle-resp2.log` and `oracle-resp3.log`: real Redis 7.4.10 and POST pass all checks in both protocols. Oracle binary SHA-256 `ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`; source revision `f103d127b9747965e28f20615ef790332661fc68`. Category case lookup is `acl.c:255`; unknown-category filtering is `server.c:5156`.
- Python compilation, differ generator inventory and shell syntax checks pass.

The existing `geo` and `cmdmeta` generators gained properties; there is no new suite or gate row. **Count delta +0 quick / +0 full.** `tests/gate.sh` and EXPECT constants are unchanged. The existing differential collectors at lines 3380 and 3391 follow the quick-tier exit at line 3348. These standalone lane checks are not newly registered gate rows.

Reproduction, all serverless except the explicitly named Redis oracle wrapper:

```sh
taskset -c 112-127 make -j12 BUILD_ROOT=build/cd13b/POST LDLIBS='-luring -pthread -lssl -lcrypto -Wl,-Map,build/cd13b/POST/tomokv.map' all
taskset -c 112-127 python3 tests/cd13b_checks.py build
taskset -c 112-127 python3 tests/cd13b_checks.py run
taskset -c 112-127 python3 tests/cd13b_checks.py run --namespace db0 --mode fused --atomic 0 --resp3 1 --notify 1
taskset -c 112-127 python3 tests/cd13b_checks.py run --late 1
taskset -c 112-127 python3 tests/cd13b_checks.py run --arm PRE  # expected exit 1, four failures
taskset -c 112-127 tests/cd13b_oracle.sh --resp3 0
taskset -c 112-127 tests/cd13b_oracle.sh --resp3 1
taskset -c 112-127 python3 tests/cd13b_audit.py
```

PRE was archived and built from the merge base before edits, with the same release flags and an absolute BUILD_ROOT of `build/cd13b/PRE`. The baseline archive remains in `build/cd13b/PRE-src`.

Maintainer measurement request: run the existing split and armed-fused differential matrix at the gate's geometry (`--shards 16 --ratio 6:2`, cores 0–7 for split), both RESP and atomic settings, and `tests/gate.sh iteration`. For the ordinary-path null, use `tests/abbagate.py`, PRE versus POST, cells **h01,h02,h09,h10,h17,h18,h25,h26,h33,h34,h41,h42,h49,h50,h57,h58**: GET/SET × p1/p32 × both modes × read-local 0/1, overlap/reorder 0, atomic 1, 512 connections. Use its calibrated offered load, matched null and sequential ABBA arms. Record its derived performance shard/ratio geometry separately from the 16-shard, 6:2 correctness geometry. Record per-cell rate, cycles/op, instructions/op and IPC, and require the maintainer's per-cell zero-regression verdict. Correctness requires no differential failures and all ownership/arming assertions firing. No performance result is claimed or fabricated here. No PAD is supplied: no object size or existing field offset changes, and this is a correctness candidate. Text placement changes still require the mainline null.

Final artifact and byte/instruction audit (PASS):

| Arm | Path | SHA-256 |
| --- | --- | --- |
| PRE | `build/cd13b/PRE/tomokv` | `ccd068a30f073ecf416bb745694adb89b1cd7f4de34c47fcc0ed6410d98a6f33` |
| POST | `build/cd13b/POST/tomokv` | `ff37e6c4c1d6a192161b1b8e314a46413beb97e3cb02e01d60c6b9b0c6d02e87` |
| POST copy | `build/tomokv` | `ff37e6c4c1d6a192161b1b8e314a46413beb97e3cb02e01d60c6b9b0c6d02e87` |

Built with the repository's GCC 13 release flags, jemalloc, both production namespaces; no LTO or runtime tuning change. ELF `.text`: **7,797,900 → 7,799,717 bytes (+1,817)**. This is text size, not a performance result.

`tests/cd13b_audit.py` audits **16,947 emitted body copies across 90 objects**: **16,687 literal raw-byte matches**, **16,878 byte-and-resolved-target matches**, **69 changed/added/removed copies**. **12** of those copies are affirmatively discarded by both linker maps (or absent from PRE); their selected executable copies are independently byte-identical. There are **zero unexplained changes**. Only the six namespace-specific objects for `xshard`, `server_tail` and new `geo_store` contain differences; all other bodies, including both `main.o`, all GEO command bodies, and all ZSET bodies are identical after verified address normalization.

All **1,225 ordinary `cmd_` body copies** are byte-identical after address normalization (**1,207** are also literally identical before normalization). Including ordinary notification/bitfield/scatter-prepare helpers gives **1,239/1,239 protected matches**, **1,217 raw matches**. No SHUTDOWN or other administrative `cmd_` exception is hidden. The broader lbstall hot inventory has **1,488 equal existing copies plus two newly emitted, discarded lookup copies**; no retained hot code differs.

The audit preserves every opcode, register, immediate, internal branch and resolved target. It normalizes only ELF relocation fields and instruction-decoded same-section call/jump/function-pointer LEA addresses. This is the repository's respcompat/lbstall-style address-normalized byte proof, not a claim that linked absolute addresses stayed fixed. Independent deliberate opcode and callee-target corruptions are both rejected. Linker-map checks account for C++ D1/D2 destructor aliases and verify the chosen symbol's linked address and size before accepting a discarded copy.

Compile-budget adjustments are confined to the changed xshard TU: multi 127577 → 127628, DB0 126170 → 126223, inline-unit-growth still zero. `main.o` settings are untouched. The cdfix adapter is shared as a macro to retain its original local lambda identity; both t_zset objects remain fully byte-identical. DB0's COMMAND LIST name builder retains an append call to prevent unrelated SHUTDOWN inlining; the other namespace retains its original constructor. Both choices are cold and byte-audited.

**Every changed body, PRE/POST byte count, static instruction count and concrete reason is listed in [docs/cd13b/changed-bodies.md](docs/cd13b/changed-bodies.md).** Full symbol names, canonical/raw hashes, protected rows, hot rows and discarded-copy proofs are in [docs/cd13b/audit.json](docs/cd13b/audit.json); the successful run is [docs/cd13b/audit.log](docs/cd13b/audit.log). Changes in unchanged-source cold administrative and scatter parsers are explicitly identified as compiler inlining effects; no performance conclusion is inferred from their smaller/larger instruction counts.

Final-object checks: **32/32 configurations pass**, both live Redis protocol checks pass, both owner-window controls pass, and all three PRE negative configurations fail the required four assertions. Mainline full gate and rate/cycles/IPC null remain pending maintainer scheduling. Append those results as `MEASURE-RESULT`.
