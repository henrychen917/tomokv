ST3 / storesize3 — cold compiler boundary, partial hot-body restoration

**WIP — requirement (2) FAILS; do not merge as an accepted optimization.**
Seven of the original nine bodies are now raw-byte identical to frozen PRE.
The two specified reorder bodies and RANDOMKEY also match. SCAN has PRE's
instructions and resolved targets but different encoded addresses. Five
ordinary db0 bodies still differ in instructions/targets against merged
mainline, and the multi-DB image retains both producer-accounting changes and
incidental compiler changes. These are not all DBSIZE/INFO routing bodies.
The exact-byte exception is not being waived. No proof of impossibility is
claimed: restoration remains unfinished at the lane's 60-minute limit.

Worktree `/home/user/Projects/cx-storesize`, branch `cx-storesize`. Started from
`b7e22cb14`, merged `origin/cpp` at `7213a9405` in `0f3057a52` before editing.
Fetched and merged again at 2026-10-06 02:26 UTC: already up to date at
`7213a94055cd12ebb6ce69757b310e250d3c2d07`. at15b was not in origin/cpp then.
The source/Makefile of this mainline ref match the existing `649116c91`
mainline-control objects exactly (`git diff 649116c91 origin/cpp -- src
Makefile` is empty). Both comparisons below are retained; mainline is not a
substitute baseline for frozen PRE.

Production changes are committed in `b2e574e2f`, `23b77148c`, `775579333`, and
`d4fdaa2e3`. The frozen POST was built from `d4fdaa2e3`; subsequent changes
only add audit tooling/receipts and this report. No push was performed.
Builds, compiler trials, serverless fixtures and body audits used CPUs 112–127.
No server, benchmark, load generator or gate was run. Higher-priority tooling
instructions required `rg`, conflicting with the prompt's grep-only request;
that conflict was disclosed before work and `rg` was used for text searches.

| Requirement | Result |
| --- | --- |
| State/sampler definitions removed from hot headers | Implemented; exact PRE compiler outcomes still only partly recovered |
| Every ordinary body raw-equal in both images | **FAIL**; all remaining failures listed with literal bytes below |
| Existing positive suites, db0 witnesses, visited bounds | PASS, including both images and split/fused × read-local off/on |
| `subexpiry` composition | Exact census source retained; field-TTL INFO is an explicit complexity exception |
| PRE/POST/PAD-A built, SHA-256 refreshed | Complete; PRE unchanged |
| Gate row contribution | Unchanged **+1 quick / +1 full**, EXPECT constants untouched |

The cold boundary is in the existing `src/cmd/storesize.cc`, keeping this
feature in its existing translation unit. It now owns the complete
`StoreSizeState`, its accessor, the expiry-index sampler template definition,
the sample publisher and the complete `Shard::publish_size` definition.
Hot headers retain declarations. State construction/destruction are
`noinline,cold`; the batch publisher and sampling/publication methods are
out of line and `noinline`. The batch boundary retains its existing single
`publish_size()` call at the same sites, with unchanged-store suppression.
No per-operation publication was added. Existing multi-DB mutation-accounting
hooks, including those in `flatstore_atomic.inc`, remain: their cost and
ordinary-body changes have not been hidden or removed from the audit.

The publisher's `noexcept` contract matters. Outlining without it made GCC
lose inferred no-unwind information and changed executor callers. Declaring
the actual nonthrowing boundary restores that information. No speculative
register-preserving ABI, `pure` annotation on a mutating function, copied
machine bodies, or relaxed audit normalization is in the candidate. Isolated
trial source patches and results are in [trials](docs/storesize3/trials).

The Makefile retains the existing per-unit `inline-unit-growth=0` mechanism.
These effective `large-unit-insns` limits recover most db0 decisions, but
**do not establish an exactly PRE-equivalent unit-growth graph**:

| db0 unit | Frozen PRE | storesize2 | storesize3 |
| --- | ---: | ---: | ---: |
| main | 146214 | 146464 | 146270 |
| genthread | 128873 | 129050 | 128910 |
| rl2s | 161715 | 161892 | 161680 |
| reorder | 147380 | 147730 | 147304 |

The SCAN translation unit uses its existing flags. Multi-DB flags are
unchanged. Main, genthread and reorder's selected db0 bodies all match the
merged-mainline control after resolving relocations; this is narrower than
the required raw-byte claim.

The before/after table preserves the nine-body numbering from storesize2.
The generic callback numbers identify emitted lambda copies, including
aliases. Full names and bytes are in the linked audit receipts.

| Body | PRE bytes | storesize2 bytes | storesize3 bytes | Raw equal to PRE | Resolved-target equal |
| --- | ---: | ---: | ---: | --- | --- |
| 1. rl2s `parse<true, 32u, false, true>` callback #1 | 772 | 852 | 772 | yes | yes |
| 2. rl2s `parse<true, 32u, false, true>` callback #4 | 772 | 852 | 772 | yes | yes |
| 3. rl2s `parse<false, 0u, true, true>` callback #1 | 772 | 852 | 772 | yes | yes |
| 4. rl2s `parse<false, 0u, true, true>` callback #4 | 772 | 852 | 772 | yes | yes |
| 5. rl2s `parse<true, 32u, false, false>` callback #1 | 852 | 772 | 772 | NO | NO |
| 6. rl2s `parse<true, 32u, false, false>` callback #4 | 852 | 772 | 772 | NO | NO |
| 7. rl2s `parse<false, 32u, false, false>` callback #1 | 852 | 772 | 852 | yes | yes |
| 8. rl2s `parse<false, 32u, false, false>` callback #4 | 852 | 772 | 852 | yes | yes |
| 9. main `serve_impl<false,true,true,false,false,false>` lambda #1 | 824 | 537 | 824 | yes | yes |
| 10. reorder `FlatStore::erase_in_read_local` | 1257 | 1208 | 1257 | yes | yes |
| 11. reorder ordinary `parse<false,32,false,false>` | 18363 | 18411 | 18363 | yes | yes |
| 12. t_server `scan_home<cmd_scan::lambda>` | 1567 | 1535 | 1567 | NO | yes |
| 13. t_server `cmd_randomkey` | 653 | 663 | 653 | yes | yes |

The remaining five ordinary db0 instruction/target changes against merged
mainline are four `core/rl2s.o` generic callbacks (#1/#4 for
`parse_and_dispatch<true,32,false,false>` and
`parse_and_dispatch<false,32,false,true>`), each **852 → 772 bytes**, and
`persist/aof.o: FlatStore::erase`, **543 → 479 bytes**. The latter newly
outlines `maybe_start_shrink`; PRE inlines that helper and calls
`start_rehash`. It is an incidental change, not a monitoring requirement.
The callback failures are the same high/low `inspect` call-site selection
problem documented in storesize2: PRE inlines the low call at `rob.h:497`,
POST the high call at `:496`. The new report is
[inline-evidence.txt](docs/storesize3/inline-evidence.txt); the PRE and
storesize2 evidence remains in
[nine-inline-evidence.txt](docs/storesize2/nine-inline-evidence.txt).
The former reorder failures in
[reorder-inline-evidence.txt](docs/storesize2/reorder-inline-evidence.txt)
are now raw-equal.

Against frozen PRE there are also seven inherited mainline R7 db0
instruction differences. They are identified in the full list; inherited
does not mean raw-equal. Address-only changes also remain failures under the
owner's literal-byte rule. No remaining ordinary difference is classified as
acceptable just because a normalized audit matches.

| Baseline | Image | Hot raw | Hot resolved | Handler/publication raw | Handler/publication resolved |
| --- | --- | ---: | ---: | ---: | ---: |
| storesize2 vs pre | db0 | 707/741 | 723/741 | not recorded | 609/622 |
| storesize2 vs pre | multi | 617/741 | 626/741 | not recorded | 506/623 |
| storesize2 vs mainline | db0 | 714/741 | 730/741 | not recorded | 609/622 |
| storesize2 vs mainline | multi | 619/741 | 626/741 | not recorded | 506/623 |
| storesize3 vs pre | db0 | 720/741 | 729/741 | 598/622 | 611/622 |
| storesize3 vs pre | multi | 620/741 | 629/741 | 375/623 | 508/623 |
| storesize3 vs mainline | db0 | 727/741 | 736/741 | 598/622 | 611/622 |
| storesize3 vs mainline | multi | 628/741 | 635/741 | 375/623 | 508/623 |

`tools/lbstall_artifacts.py compare` is unchanged. It keeps target identities,
addends, strings and constants when resolving relocations. The supplemental
all-command/publication audit now records raw equality as well. A missing
body still fails. Moving eight weak publisher copies to one strong cold-unit
definition is explicitly recorded as a move, with the replacement's real
bytes; it does not silently count as equality. The audits examine emitted
copies, not merely the linker's selected COMDAT copy.

Every remaining failed copy is listed, including size, full demangled name,
classification and raw/resolved status:

- [db0: 45 distinct failed copies](docs/storesize3/db0-remaining-bodies.md)
- [multi: 368 distinct failed copies](docs/storesize3/multi-remaining-bodies.md)
- [db0 literal PRE/POST bytes and body SHA-256](docs/storesize3/db0-literal-differences.json)
- [multi literal PRE/POST bytes and body SHA-256](docs/storesize3/multi-literal-differences.json)

Those lists are the union of raw OR resolved failures across the two audits,
de-duplicated by object and symbol. Full pass/fail rows and logs are in
`docs/storesize3/{db0,multi}-{hot,handlers}-vs-{pre,mainline}-final.{json,log}`.
Target deltas distinguish added accounting calls from incidental effects;
unexplained instruction changes remain explicitly unresolved. Multi-DB's
existing exact owner-private counter design requires mutation hooks. Removing
them without another data source would break the passing count assertions.
Keeping them means the strict ordinary-body restriction is not met. This
report does not claim that a different design cannot solve that conflict.

The permitted routing surface is limited to these `cmd/t_server.o` bodies:

| Body | db0 PRE → POST bytes | multi PRE → POST bytes | Why it belongs to the feature |
| --- | ---: | ---: | --- |
| `cmd_dbsize` | 242 → 242 (addresses differ) | 242 → 290 | Selects the published physical-database counter; NOW remains census |
| `cmd_info` | 16161 → 16519 | 16215 → 16967 | Builds the published/census keyspace output and `subexpiry` field |
| `cmd_info` cold clone | 349 → 351 | 353 → 379 | Exception cleanup emitted for that same INFO body |
| `command_config_routes_all_shards` | 610 → 668 | 668 → 766 | Selects monitor census versus published route, including field-TTL attention |

Other producer/accounting, parser, writeback, SCAN and persistence bodies are
not included in that exemption. The three GET and two SET emitted handler
copies retain resolved equality in both images; that does not prove their
entire called paths or MGET/MSET scatter paths equal.

For the at15b addendum this lane takes the explicitly allowed **retain the
count source** option. `multidb_stats()` counts hash objects whose field-TTL
table is nonempty; two expiring fields in one hash count as one. Aggregation
in `xshard_commands.inc` preserves each database's `subexpiry`. The formatter
emits one `dbN:keys=...,expires=...,avg_ttl=...,subexpiry=...` line. This is
the format/count portion of at15b; its unrelated admission changes were not
copied. The census uses the public `hash_ttl_slot()` accessor.

A conservative per-shard field-TTL attention flag is published at the same
batch boundary. If any published flag is set, INFO sections containing
keyspace use the existing exact owner census. With no field TTLs the published
route emits `subexpiry=0`. A stale attention entry may request an unnecessary
census; it is never used as the actual `subexpiry` count. Removing the last
field deadline and FLUSH are covered. The flag shares the existing one-batch
publication freshness, not a wall-clock guarantee. INFO SERVER and other
sections without keyspace do not acquire this census route. Plain DBSIZE is
still published; DBSIZE NOW remains exact census.

**Consequently, bare INFO with possible field TTLs is not O(shards): it can
walk all resident keys.** This is the declared alternative to adding exact
per-database subexpiry mutation accounting in this lane. Without field TTLs,
db0 INFO remains O(shards), and multi INFO O(shards × configured databases),
bounded by the existing 256-database limit. No universal constant-work INFO
claim is made. Field-TTL cost needs its own measurement shape below.

Existing published key/expiry pairs, namespace mapping, dirty rows, expiry
mean calculation, selected-database semantics and migration ownership are
preserved. State belongs to FlatStore and moves with its shard; it names no
per-thread allocation. Observers load atomics without retries or seqlocks.
The db0 sampler still visits at most 16 expiry-index slots per publication;
no key expiry skips sampling after updating the field attention flag.
Published statistics can lag one owner batch and are not a cross-shard atomic
snapshot. Exact NOW retains its prior semantics.

All locked layouts remain Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. The opaque db0
sidecar is now 24 bytes (previously 16); multi remains 12,416 bytes before
allocator rounding because its arrays already start at 64-byte boundaries.
The existing pointer occupies bytes 4–11 of the reader/owner gap. Neither
read-local overwrite rules nor ownership migration protocols were changed.

The final production arms are:

| Arm | File | SHA-256 |
| --- | --- | --- |
| PRE | `build/storesize3/PRE` | `47b0c843d59a275a7aaa515c733d3fdcee3db8bf9a5525684ac2f7209394e9bc` |
| POST | `build/storesize3/POST` | `30035c48fed39833b82041232230ed535d556821ae45adc47e633ff9b7265807` |
| PAD-A | `build/storesize3/PAD-A` | `59d83429afc74ab1c20c4e753dc7f68cdc202db4e9c4dd7042ea8f00b3281f8b` |

All three were verified with [SHA256SUMS](docs/storesize3/SHA256SUMS).
PRE is the unchanged fully rebuilt storesize2 PRE, whose original rebuild
receipt is [pre-rebuild.log](docs/storesize2/pre-rebuild.log); it was not
recompiled again in this lane. POST was force-rebuilt with GCC 13.3.0:
[build-final.log](docs/storesize3/build-final.log). Production binaries do not
contain visited-object instrumentation.

PAD-A is **kind A — behaviour twin**: PRE monitoring census routes with
POST text size/layout. The existing control changes exactly two return
immediates, one per database image, from one to zero. Section headers,
symbol tables, text size and symbol addresses are identical to POST. It
retains POST producer accounting, sampler, field attention and the new wire
field: it isolates monitoring routing, not the whole feature's producer cost.
See [pad-final.json](docs/storesize3/pad-final.json). ELF `.text` is PRE
7,781,132 bytes and POST/PAD-A 7,792,220 bytes, delta +11,088 including the
mainline merge. No kind-B arm was built; no gain is claimed from this delta.

| Serverless verification | Result |
| --- | --- |
| Forced production + both-image fixture + broader multi-DB build | PASS, `make -B -j8 build/tomokv build/storesize-unit build/multidb-unit` |
| Frozen PRE fixture | PASS, 8 cases / 120 walk observations; [pre-checks.log](docs/storesize3/pre-checks.log) |
| POST positive suite | PASS, 8 cases / 120 walk observations; [controls-final.log](docs/storesize3/controls-final.log) |
| PAD-A-equivalent instrumented fixture | 8 legacy cases PASS; positive test deliberately FAILS at `FAIL storesize: monitor route`; same receipt |
| Field-TTL source/format checks | PASS in both arms/images/modes, 8 combinations each; same receipt |
| Existing multi-DB unit | PASS; [multidb-unit-final.log](docs/storesize3/multidb-unit-final.log) |
| Strict body audit | **FAIL**, preserved nonzero hot-compare exit status and literal failure receipts |

The original fixtures retain populations 128 / 4,096 / 16,384 and capacities
16,384 / 16,384 / 32,768. POST plain DBSIZE, bare INFO and INFO KEYSPACE visit
zero objects and zero slots for those no-field-TTL datasets; NOW and legacy
routes retain the full visited capacity/object count. The db0 witnesses,
freshness witness, SELECT/MOVE/SWAPDB/FLUSH and expiry assertions remain.
Added subexpiry checks require the field census actually to visit the hash;
they cover two TTL fields counted once, partial/last HPERSIST, namespace map
swaps and return to published routing after FLUSH. No skipped arming case or
weakened visited bound was introduced. Fixture geometry is 16 shards, eight
configured threads (6 IO + 2 EX for split), also fused/read-local variants;
these are serverless drivers, not live mode boot or gate evidence.

Exactly one gate row remains: `storesize published monitoring`,
`tests/gate.sh:1587`, invoked at 1588 and collected with `core_units` at 3130.
Both are before the quick-tier exit block at 3279 (exit at 3283), hence the
lane still contributes **+1 quick / +1 full**, not another new row for ST3.
`EXPECT_QUICK=497` and `EXPECT_FULL=514` at lines 279–280 are unchanged.
For this lane alone the maintainer's counts should become **498 / 515**.
The gate was not run.

Audit reproduction (serverless, expected hot-audit failure):

```sh
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare build/storesize-pre/db0/src build/db0/src docs/storesize3/db0-hot-vs-pre-final.json
taskset -c 112-127 python3 tools/storesize_artifacts.py handlers build/storesize-pre/db0/src build/db0/src docs/storesize3/db0-handlers-vs-pre-final.json
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare build/storesize-pre/src build/src docs/storesize3/multi-hot-vs-pre-final.json
taskset -c 112-127 python3 tools/storesize_artifacts.py handlers build/storesize-pre/src build/src docs/storesize3/multi-handlers-vs-pre-final.json
taskset -c 112-127 python3 tests/storesize_checks.py check-all build/storesize-unit
taskset -c 112-127 ./build/multidb-unit
taskset -c 112-127 sha256sum -c docs/storesize3/SHA256SUMS
```

Measurement handoff is held as WIP pending restoration; these are reviewable
arms, not evidence of acceptance. Earlier owner-supplied mainline null results
for storesize2 do not measure these new hashes. No new PRE/POST performance
table exists because no measurements were run by this lane.

When the maintainer elects to measure, use PRE/POST/PAD-A with the gate's own
ABBA instrument and a contemporaneous same-binary null. Cells are the exact
14 in `tests/wbland_merit_cells.txt`:
`h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`.
Retain the instrument's geometry, mode, pipeline, offered rates and shard/ratio
derivation. Headline geometry: 32 physical server cores 0–31, loaders 32–111,
512 connections, 2M keys, 64-byte values except v1g, uring, atomic=1,
overlap=1, reorder=0, default balancers, save disabled. Repeat matched
nonzero-database workloads to measure the multi-DB producer cost separately.

INFO interference: h05 GET p32, fused/read-local=0, **40M resident keys**,
64-byte values, 512 connections. Recalibrate for the dataset and hold offered
load matched across each binary's no-poller and 1 Hz bare-INFO arms. Repeat
with multiple populated databases, then a separate field-TTL population to
expose the declared census fallback. Use `tools/storesize_poller.py` only on
mainline; reject missed periods, bad replies, incomplete poll counts or
unrelated harness INFO polls in a no-poller arm. Record rate, p50/p99/p99.9,
cycles/op, instructions/op, IPC and INFO latency. Compare poll penalties to
each arm's own no-poller baseline. PAD-A should retain census cost on ordinary
key populations. Rate/tails and cycles/op at matched load decide; instructions
and IPC explain. No ordinary-cell regression beyond the contemporaneous null
is acceptable. Append actual results to MEASURE-RESULT. Performance acceptance
cannot replace the still-failing strict body-identity requirement.
