# Redis 7.4 data-type compatibility

## datafix1

All seven requested findings reproduced against the pinned Redis 7.4.10 oracle
and are fixed on `cx-datafix1`. PRE is `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`.
No push. All correctness work and builds used CPUs 48–63 and ports 29800–29899;
builds used `-j16`. No throughput result is claimed.

| Item | Change | Directed battery | Legs |
|---|---|---|---:|
| CD4.3 | Free-order GEO option loop, exact COUNT/ANY/duplicate/source-member errors and lookup precedence; routing defers validation to the source owner | tests/datafix1_geo.py | 12 |
| CD4.4 | Compact partial SPOP, Redis's survivor-rebuild threshold, intset narrowing and live-limit encoding transitions; linear counted traversal | tests/datafix1_spop.py | 6 |
| CD4.5 | One-node quicklist demotion at half the live count/byte limits after pop, trim, remove, set and mover removals | tests/datafix1_lists.py | 12 |
| CD4.6 | locale-collate default/environment, boot parsing, CONFIG GET/SET/REWRITE and per-sort collation snapshots | tests/datafix1_locale.py | 12 |
| CD4.10 | BITFIELD tests the first byte, including GET; matches indexed-offset wrapping and Redis's bounded growth | tests/datafix1_bitfield.py | 6 |
| CD4.11 | Negative/overflowing hash-expire values precede condition/FIELDS validation; wrong-type lookup precedence retained | tests/datafix1_hexpire.py | 6 |
| CD4.12 | RAND count/option/lookup precedence, half-range texts, SRAND extra-argument syntax and SCAN-family errors | tests/datafix1_randscan.py | 6 |

Final directed proof: **29,328 assertions in 60 complete POST legs; all pass.**
Every corresponding PRE leg fails actual assertions; neither arm has a boot or
driver exception. Each leg boots fresh oracle/target processes. Both engines run
split (16 shards, 6 io + 2 ex), fused and armed-fused on CPUs 48–55. Multi-key
features also run atomic 0/1. The target uses database count 1 in these directed
legs; the broader jobs retain their declared configurations.

Receipts: `docs/datafix1/{pre,post}-linear-directed-proof.tar.gz` and
`{pre,post}-new-row-inventory.json`. Independent oracle assertions preceded each
implementation; `oracle-*` directories retain replies and owned-process lifecycles.
The oracle path, version and digest are in `oracle-identity.json`.

SPOP applies Redis's rebuild branch exactly when `(n-k)*5 <= k`. Rebuilding can
narrow an intset, demote a hashtable to a listpack, or promote survivors under
lowered live limits. The battery covers both sides of the branch, signed
16/32/64-bit integers, contents, uniqueness, TTL, memory bounds and SSCAN coverage
of surviving members. Rebuilt intset memory equals a fresh set of the same
survivors on each server. Absolute allocator byte counts are not asserted equal
between different server implementations.

Cost per partial call, `0 < k < n`, with n members and B packed bytes:

| Arm/path | Work | Additional storage |
|---|---|---|
| PRE compact listpack | O(n+B) table construction plus expected O(k) picks | Permanent O(n) table/string storage |
| PRE compact intset | O(n log n+B) indexed offset lookups/table construction plus expected O(k) picks | Permanent O(n) table/string storage |
| POST single compact pop | One pick and bounded packed traversal/shift, O(n+B) | No auxiliary allocation |
| POST counted compact pop | Linear sampling, survivor construction and reply traversal, O(n+B) | O(k+B) for small pops; O(n-k + survivor bytes) for rebuilding |

Counted partial calls make n sampling decisions and at most two full source traversals,
plus survivor construction. There is no repeated compact membership lookup or
duplicate-pick rejection loop. Current limits can require expected hash-insert
work when rebuilding. These are algorithmic bounds, not measured cycles or rates.

List demotion derives Redis listpack framing, integer widths, header and back-length
bytes; count limits 4/5/8 and 4096/4097-byte boundaries are tested. The only changed
existing assertion is edgeenc's list shrink expectation, backed by the oracle
receipts. Its other type expectations are unchanged.

ALPHA sorts without STORE retain one duplicated locale object for the whole sort.
A cold mutex protects publication/duplication, not comparisons; CONFIG SET cannot
free an active comparison context. No executor calls setlocale. STORE remains
binary. Tests cover environment/C/UTF-8 collation, BY, SORT_RO, all source types,
invalid names, embedded NUL, duplicate settings and concurrent changes.

BITFIELD grows through the last touched byte as Redis does. A field is at most
64 bits, so growth can exceed the configured bulk limit by at most eight bytes.
The supported UINT32_MAX-minus-64KiB ceiling leaves representable space, pinned
by static_assert. Boundary writes use a 1MiB cap; maximum-cap probes are read-only.
Multi-gigabyte allocation tests were NOT RUN; the upper-bound proof is arithmetic.

Gate accounting: **DQ=+7, DF=+7**. All seven collect_job lines (4286–4292) precede
the quick exit (4375–4379). EXPECT_QUICK=685 and EXPECT_FULL=702 are untouched;
the maintainer should set **692 / 709**. The explicit label fixture matches the
source multiset exactly (709). Its count validator remains red only because
EXPECT_FULL is still 702; see `label-fixture.log`.

Proof status (all live rows use tests/gate.sh's own partial-job interface):

| Proof | PRE | Final POST |
|---|---|---|
| Seven directed rows | 60/60 legs fail assertions | 60/60 legs pass |
| Storage/atomic/netcmd units, including encoding and memory | 57/57 pass | 57/57 pass (post-linear-units) |
| Configuration docs/parser and command metadata | 3/3 pass from PRE source | Included in final legacy jobs |
| Legacy data-type jobs, epoll | 156/156 pass | 156/156 legacy + 3/3 static pass |
| Legacy data-type jobs, io_uring | Earlier selected run: 157 pass, one tracking failure; globcase follow-up pending | 156/156 pass |
| Related jobs: parser, AOF, debug, GEO client, hash TTL, dump/restore, notifications | 199/199 pass | PENDING |
| Standard differential, both engines | PENDING | PENDING |
| PAD-A directed behavior control | PRE behavior required | PENDING |

The gate harness self-test passed 67/67 when run alone (`gates-test-serial.log`).
Final POST passes make -q for all, all 37 job_production_units targets and both MDB
witness builds (`freshness-linear.log`). PRE passed the same fixture freshness
checks before redundant fixture/control builds were removed; its source,
production objects and server remain, with make -q all still passing.
`lean-builds.json` records the pruning. The build tree is about 14GB, largely the
required POST production fixtures and controls.

The full changed-text/encoding grep and job mapping are in test-impact-*.txt and
test-impact-map.tsv. Historical standalone scripts without a gate job are named
there; they were not silently substituted for registered jobs. Exact job selections,
per-row results and lifecycle logs are retained in the proof archives.

Identity: 16,838 emitted bodies inventoried, 322 changed; every changed body has a
reason in `body-reasons.json`, including compiler spillover in unedited helpers.
All 1,220 selected hot bodies are canonical-equal. All ten linked GET/SET/MGET/MSET
handlers are proven against PRE (`linked-primary.json`). The broader audit reports
4,365/4,484 ordinary object bodies equal and 2,584/2,690 linked bodies proven.
Both tools still reject their INFO/CONFIG/ACL-only admission policies; those
whitelists were not weakened. Identity is a proxy; the merit comparison decides.

Budgets were re-derived from final initial IPA sizes 19373 / 19175 against PRE
17685 / 17505. Set budgets are 26200 / db0 26400; normal zset is 33447. Commands,
digests and body inventories for the trials are under `docs/datafix1/budgets`.
Both namespaces retain Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore
944, Rob<64> 192, AtomicEntry 144 and Config 624. Config's new pointer uses eight
reserved bytes; all existing non-reserved field offsets match (`layout-reviewed.json`).

Artifacts and SHA-256:

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | build/datafix1/pre-src/build/tomokv | 194bcfa235f0255304b9d774134f28a9fe7beaf61ba6f10861484404c17dc615 |
| POST | build/tomokv | b05021db6b4f7369b0cad5b7009b8a1918332860f92b03f029394c23e4d61dec |
| PAD-A | build/datafix1/PAD-A/tomokv | 75ea5fd78496a4e2de15f4178731627aecdeb6ae2db6765f8a9fc14619142b9c |

PAD kind **A, behavior twin**: unchanged PRE objects plus 30,400 inert text bytes,
matching POST's 7,777,926-byte .text and unchanged layout locks. This controls total
text size, not each function's placement. Config's locale pointer occupies PRE's
reserved storage. `tools/datafix1_pad.py` and `pad-kind.json` preserve exact link
and object provenance; `SHA256SUMS` records all three binaries.

Maintainer merit request — **NOT RUN here**, as instructed: use the gate's ABBA
instrument and the exact 14 cells in tests/wbland_merit_cells.txt:
h05, h06, p8g, p8s, d1g_l0, d1s_l0, m8g_l0, v1g_l0, d128g_l0, d32g_l1,
d8s_l1, d32s_l1, x9_32_l1, x9_32_l0. Establish a same-binary null, then compare
PRE/POST, PRE/PAD-A and PAD-A/POST at matched offered load and each declared
geometry. Rate decides rate cells; latency decides the two p1 cells. Report
cycles/op, IPC and instructions/op together. A spread above 2% requires
investigation, not a relaxed tolerance. The question is preservation of ordinary
workload merit after compatibility repairs. The full iteration, ABBA and NIC
performance tiers were NOT RUN; they remain with the maintainer.

Baseline and harness history is documented in `docs/datafix1/RUN-NOTES.md`.
Superseded or incomplete runs are not counted as final-binary passes.
