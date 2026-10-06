Lane cdfix: CD6 / CD7 / CD8 / CD13, Redis 7.4 compatibility

**WIP — do not merge yet.** The four compatibility changes and their serverless witnesses are implemented. The strict requirement that every body outside the requested fixes remain identical is NOT fully satisfied: three unchanged-source GEO helper bodies still differ. The audit deliberately fails on those differences. Mainline's 14-cell null and live differential runs remain unrun, as instructed. No performance conclusion is claimed.

PRE is the merge-base binary at `b1d931ee2a271f28c9c9c91e2556c8fa36000a4d`, after the required fast-forward merge of `origin/cpp` into `cx-cdfix`. No push was made. All compilation and serverless execution used CPUs 112–127. No server, benchmark, load generator, gate, or live differential harness was started by this lane.

The references are `/home/user/Projects/round3-read/cmd-data.md`, rows CD6/CD7/CD8/CD13, and the harness's pinned checkout `/tmp/claude-1000/redis74`, Redis 7.4.10 at `f103d127b9747965e28f20615ef790332661fc68`. Relevant source: `dict.c` reverse-binary dictScan, `geo.c:601–610` repeated STORE parsing, `geo.c:962–963` GEOPOS replies, `util.c:862–884` LD_STR_HUMAN, `networking.c` addReplyHumanLongDouble, and `db.c:262` preservation of the replaced value's LRU/LFU bits. GEOADD delegates to ZADD; radius STORE constructs a replacement and may compact it.

| Item | Redis behaviour | PRE behaviour | POST behaviour and evidence |
| --- | --- | --- | --- |
| CD6 | Reverse-binary hash-bucket cursor; bounded-size churn preserves full-iteration coverage. Cursor numbers and page boundaries are implementation-defined. | Generation-stamped physical cursor restarts on every rehash; witness exceeds 1,024 pages without termination. | Shared `scan_cursor_next` counter visits logical home buckets, including displaced members, tombstones and wraparound. All 192 permanent members returned in 28 pages despite 27 witnessed intervening rehashes. Eight additional growth/wraparound cases each witness three capacity increases. |
| CD7 | Format `%.17Lf`, trim fractional trailing zeros and the bare decimal point; normalize negative zero. RESP2 bulk and RESP3 double use the same text. | Keeps all 17 fractional places, causing different bulk lengths and numeric reply bytes. | Uses Redis's fixed long-double format and exact trimming. 512 seeded random coordinates × two protocols × notify off/on = 2,048 complete byte-equal GEOPOS frames per database build, checked against unmodified Redis geohash.c + util.c. |
| CD8 | Every STORE/STOREDIST token replaces both destination and score mode; last one wins. | First destination wins, last mode wins. | Both destination and mode follow the last token. Both radius verbs, both orders, absent/existing-string destinations, protocols and notify paths checked in 32 cases per database build. |
| CD13 | GEOADD preserves LFU state and expanded encoding; STORE retains destination metadata but can choose listpack. | GEOADD/local STORE rebuilds reset LFU history; a shrunken expanded zset demotes on GEOADD. | Metadata passed from the owner-side GEO caller into the replacement builder and copied with set_eviction_meta. Already-expanded GEOADD forces normal promotion on first insertion; STORE retains normal compact thresholds. Exact nonzero metadata 5/12/31 and encoding witnesses pass in both notification paths. |

CD6 uses the existing home-bucket invariant: rehash preserves the low hash-bit prefix, while physical slot displacement does not. Each bucket's entire probe chain is visited before advancing the reverse-binary cursor. COUNT bounds work between buckets, never truncates a bucket. Generation storage and insertion/rehash bookkeeping remain unchanged, preserving insertion-path code and allocations. The property assumes bounded table size, as does Redis's SCAN termination guarantee. SSCAN final cursor has bulk bytes `$1\r\n0\r\n`; page ordering/cursor bytes are intentionally not compared across servers.

CD7's exact reproducer is `GEOADD coordinate -160.5371430516242981 32.99910767291845559 m`, followed by `GEOPOS coordinate m`:

| Protocol | PRE bytes, CRLF escaped | POST / Redis pure-function oracle bytes |
| --- | --- | --- |
| RESP2 | `*1\r\n*2\r\n$22\r\n-160.53714305162429810\r\n$20\r\n32.99910767291845559\r\n` | `*1\r\n*2\r\n$21\r\n-160.5371430516242981\r\n$20\r\n32.99910767291845559\r\n` |
| RESP3 | `*1\r\n*2\r\n,-160.53714305162429810\r\n,32.99910767291845559\r\n` | `*1\r\n*2\r\n,-160.5371430516242981\r\n,32.99910767291845559\r\n` |

For CD8, seed `GEOADD geo 13 38 a 13.01 38.01 b`. In both orders, `GEORADIUSBYMEMBER geo a 10 km ...` replies `:2\r\n`. PRE writes `first`; POST writes `last`. The untouched absent destination returns `:0\r\n`, `+none\r\n`, `*0\r\n` for EXISTS / TYPE / ZRANGE WITHSCORES. The written destination returns `:1\r\n`, `+zset\r\n`, and the frame below. Existing first destinations remain strings on POST, including their WRONGTYPE ZRANGE reply. Complete PRE/POST RESP2/RESP3 hex transcripts are in `docs/cdfix/wire-pre.log` and `wire-post.log`; those are direct-handler transcripts, not live oracle results.

| Last token | Written destination ZRANGE WITHSCORES, RESP2 |
| --- | --- |
| STORE | `*4\r\n$1\r\na\r\n$16\r\n3479065152021743\r\n$1\r\nb\r\n$16\r\n3479070897832762\r\n` |
| STOREDIST | `*4\r\n$1\r\na\r\n$1\r\n0\r\n$1\r\nb\r\n$18\r\n1.4159773120355879\r\n` |

CD13 encoding bytes after expansion to 160 members, deletion down to two, then GEOADD: PRE `$8\r\nlistpack\r\n`; POST and Redis `$8\r\nskiplist\r\n`. Same-key radius STORE can subsequently return `$8\r\nlistpack\r\n`. LFU counters are stochastic and differ in representation between servers, so the live wire property measures each server's own initial value, requires a fresh bounded arming attempt to raise it by at least three, and requires OBJECT FREQ to remain above initial after GEOADD. Integer framing is checked exactly; counters are not falsely compared numerically between servers. The deterministic serverless witness disables access increments and checks packed metadata 5/12/31 exactly.

The differential inventory extends the existing `geo` and `scan` suites only. It adds 256 random GEOPOS coordinates per invocation (both RESP2 and RESP3 are already enumerated by the harness), both STORE orders for both radius verbs with both destination probes, GEOADD encoding checks, and the LFU wire property against both existing connections under allkeys-lfu. It restores CONFIG settings even on failure. SSCAN churn alternates 192 permanent members with 512 fresh transient members, bounds the scan at 2,048 calls, and fails if pagination never arms or coverage is incomplete. No new gate row: **count delta +0 quick / +0 full**. `tests/gate.sh`, EXPECT constants, fixture files and harness boot code are unchanged. The existing differ rows are after the quick-tier exit at `tests/gate.sh:3276` (collectors at 3304 and 3315).

Serverless reproduction (no listener or io_uring boot):

```sh
taskset -c 112-127 python3 tests/cdfix_checks.py build --output build/cdfix/unit
taskset -c 112-127 build/cdfix/unit/POST-multi
taskset -c 112-127 build/cdfix/unit/POST-db0
taskset -c 112-127 build/cdfix/unit/PRE-multi
taskset -c 112-127 build/cdfix/unit/PRE-db0
taskset -c 112-127 build/cdfix/unit/PHYSICAL-multi scan-growth
```

POST is expected to pass all six cases. PRE is expected to fail scan termination, coordinate bytes, STORE destination, encoding and metadata, while passing the finite-growth case. PHYSICAL is a test-only throwaway copy changing logical-home matching to physical-slot matching; it terminates but fails permanent-member coverage. It is not a server arm and is never installed as build/tomokv. The audit also verifies that opcode and resolved-call-target mutations are rejected; the repository instruction normalizer's negative controls passed.

The remaining required work is to remove the three GEO helper code-generation differences without broadening the audit allowance, then have the maintainer run the existing differential harness's split and armed-fused matrices using its vanilla Redis boot. At split geometry reproduce with 16 shards, cores 0–7, ratio 6:2. Both RESP versions and atomic settings must pass. Mainline owns the existing 14-cell PRE/POST null; use these exact arm hashes, matched offered load, and the gate's own ABBA instrument. Report each cell's rate, cycles/op, instructions/op and IPC; require the mainline per-cell no-regression verdict, not an average. Do not select a different 14-cell definition from this lane. Timing cells have not been measured here.

No data-structure layout changed: the header edits are declarations only and the existing layout assertions compiled. No PAD arm is claimed or supplied; this is a correctness candidate, with no performance-gain claim. `.text`/code placement necessarily changes, so the mainline null is still required even after byte identity is repaired.

Two source-reviewed handoffs remain outside the requested local replacement fix. Cross-owner GEO STORE installs through `scatter_engine.inc:357` apply_image, whose fresh object also lacks metadata preservation; the same-key LFU STORE witness deliberately exercises the scoped local path, and does not prove that cross-owner path. Also, packed metadata zero retains FlatStore's existing zero-as-uninitialized policy (`flatstore.h:1674`); the sibling promotion pattern has the same limitation. This lane does not alter the shared insertion/scatter bodies or claim either issue is repaired.

Artifact and instruction audit results follow.

| Arm | Path | SHA-256 |
| --- | --- | --- |
| PRE | `build/cdfix/PRE/tomokv` | `b968fbe3264a96d44bd2379cd20d381b6f51741811a2b0e886c239d23d7a42be` |
| POST | `build/cdfix/POST/tomokv` | `45879a65a3df0dd585d341f98a846cafcf89e046c887a4923639e8c221b33a43` |
| POST copy | `build/tomokv` | `45879a65a3df0dd585d341f98a846cafcf89e046c887a4923639e8c221b33a43` |

GNU size reports text 8,798,261 → 8,801,693 bytes (+3,432); data 89,704 and BSS 1,146,456 are unchanged. These are artifact sizes, not measured performance. The source build used g++ 13 with the repository release flags (`-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, jemalloc). Both namespaces are in the production binary.

The PRE binary was built before source edits. The POST release build is reproducible with:

```sh
taskset -c 112-127 make -j12 BUILD_ROOT=build/cdfix/POST LDLIBS='-luring -pthread -lssl -lcrypto -Wl,-Map,build/cdfix/POST/tomokv.map' all
cp build/cdfix/POST/tomokv build/tomokv
taskset -c 112-127 python3 tests/cdfix_checks.py audit --output docs/cdfix/body-audit.json
```

The last command MUST currently exit 1. It compares all production object functions in both namespaces, including cold clones, and preserves opcodes, registers, immediate values, local branch layout, literal targets and resolved callees. Only verified relocation/address fields are normalized. The two added LEA cases resolve local function-pointer destinations rather than masking arbitrary RIP-relative bytes. Opcode and resolved-target corruption controls fail as required.

The final inventory contains **16,838 emitted bodies**: **16,540 raw-byte matches**, **16,794 matches after address relocation**, **44 changed/added/removed bodies**, and **4 changed or newly emitted COMDAT copies proven discarded by linker maps**. The retained copies in both linked binaries resolve to the same, independently byte-equal object bodies. **All 52 protected body copies match**, including GET/SET/MGET/MSET/HSET, SADD/SISMEMBER/SMEMBERS and SetMemberTable insert/capacity/rehash paths. Every body outside geo.o, t_set.o and t_zset.o is equal. Three existing GEO helpers still fail strict identity; no normalizer or blanket GEO exclusion hides them.

GCC compile-only budgets in Makefile retain ordinary set/zset bodies: multi/db0 set 23440/23300, zset 33395/32970, GEO 14410/14440, with inline-unit-growth=0. The 16-byte metadata-copy adapter prevents the new setter call from changing ordinary SORT/ZSET inlining. The remaining GEO differences are compiler inlining changes; they are not semantic changes, not a byte-identity pass, and not assumed harmless without the owner's required proof.

Every emitted body difference is listed below; full mangled names, raw/equality flags and retained-copy evidence are in `docs/cdfix/body-audit.json`.

| Object | Body | PRE → POST bytes | Reason / status |
| --- | --- | --- | --- |
| `db0/src/cmd/geo.o` | `void tomo_db0::(anonymous namespace)::cmd_geoadd<false>(tomo_db0::Shard&, tomo_db0::Op&)` | 4661 → 4788 | CD13: collect existing metadata and encoding; updated replacement call, including its emitted template helpers |
| `db0/src/cmd/geo.o` | `void tomo_db0::(anonymous namespace)::cmd_geoadd<false>(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | 239 → 254 | CD13: collect existing metadata and encoding; updated replacement call, including its emitted template helpers |
| `db0/src/cmd/geo.o` | `void tomo_db0::(anonymous namespace)::cmd_geoadd<true>(tomo_db0::Shard&, tomo_db0::Op&)` | 4833 → 5018 | CD13: collect existing metadata and encoding; updated replacement call, including its emitted template helpers |
| `db0/src/cmd/geo.o` | `void tomo_db0::(anonymous namespace)::cmd_geoadd<true>(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | 243 → 243 | CD13: collect existing metadata and encoding; updated replacement call, including its emitted template helpers |
| `db0/src/cmd/geo.o` | `tomo_db0::(anonymous namespace)::parse_search(tomo_db0::Op&, tomo_db0::(anonymous namespace)::GeoSearchOptions&) [clone .constprop.0]` | 3418 → 3412 | CD8: last destination replaces earlier STORE destination |
| `db0/src/cmd/geo.o` | `tomo_db0::(anonymous namespace)::reply_coordinate(tomo_db0::Op&, double)` | 483 → 633 | CD7: Redis fixed-long-double formatting, zero/dot trimming and RESP framing |
| `db0/src/cmd/geo.o` | `tomo_db0::(anonymous namespace)::reply_geo_results(tomo_db0::Op&, tomo_db0::(anonymous namespace)::GeoSearchOptions const&, std::vector<tomo_db0::(anonymous namespace)::GeoResult, std::allocator<tomo_db0::(anonymous namespace)::GeoResult> > const&)` | 1904 → 1932 | UNRESOLVED: compiler inlining changed an unchanged-source GEO helper; audit FAIL |
| `db0/src/cmd/geo.o` | `tomo_db0::cmd_geo_xshard_local(tomo_db0::Shard&, tomo_db0::Op&, bool)` | 1274 → 1719 | CD13: local STORE destination metadata; updated replacement call |
| `db0/src/cmd/geo.o` | `tomo_db0::cmd_geo_xshard_local(tomo_db0::Shard&, tomo_db0::Op&, bool) [clone .cold]` | 51 → 51 | CD13: local STORE destination metadata; updated replacement call |
| `db0/src/cmd/geo.o` | `tomo_db0::FlatStore::find_resident(unsigned long, tomo_db0::Slice) const` | 0 → 108 | CD13: new cold current-destination lookup; no existing PRE body changed |
| `db0/src/cmd/geo.o` | `tomo_db0::FlatStore::find_in(int, unsigned long, tomo_db0::Slice) const` | 0 → 554 | Discarded COMDAT; retained equal copy: db0/src/main.o |
| `db0/src/cmd/geo.o` | `void std::__introsort_loop<__gnu_cxx::__normal_iterator<tomo_db0::ZsetEntry*, std::vector<tomo_db0::ZsetEntry, std::allocator<tomo_db0::ZsetEntry> > >, long, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::(anonymous namespace)::cmd_geoadd<false>(tomo_db0::Shard&, tomo_db0::Op&)::{lambda(tomo_db0::ZsetEntry const&, tomo_db0::ZsetEntry const&)#1}> >(__gnu_cxx::__normal_iterator<tomo_db0::ZsetEntry*, std::vector<tomo_db0::ZsetEntry, std::allocator<tomo_db0::ZsetEntry> > >, __gnu_cxx::__normal_iterator<tomo_db0::ZsetEntry*, std::vector<tomo_db0::ZsetEntry, std::allocator<tomo_db0::ZsetEntry> > >, long, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::(anonymous namespace)::cmd_geoadd<false>(tomo_db0::Shard&, tomo_db0::Op&)::{lambda(tomo_db0::ZsetEntry const&, tomo_db0::ZsetEntry const&)#1}>)` | 2954 → 3151 | CD13: collect existing metadata and encoding; updated replacement call, including its emitted template helpers |
| `db0/src/cmd/t_set.o` | `void tomo_db0::(anonymous namespace)::cmd_sscan<false>(tomo_db0::Shard&, tomo_db0::Op&)` | 3126 → 2858 | CD6: shared reverse-binary logical-home scan and MATCH filtering |
| `db0/src/cmd/t_set.o` | `void tomo_db0::(anonymous namespace)::cmd_sscan<false>(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | 115 → 115 | CD6: shared reverse-binary logical-home scan and MATCH filtering |
| `db0/src/cmd/t_set.o` | `void tomo_db0::(anonymous namespace)::cmd_sscan<true>(tomo_db0::Shard&, tomo_db0::Op&)` | 3126 → 2858 | CD6: shared reverse-binary logical-home scan and MATCH filtering |
| `db0/src/cmd/t_set.o` | `void tomo_db0::(anonymous namespace)::cmd_sscan<true>(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | 117 → 115 | CD6: shared reverse-binary logical-home scan and MATCH filtering |
| `db0/src/cmd/t_set.o` | `tomo_db0::CollectionRef::replace_compact(tomo_db0::Compact&&)` | 306 → 595 | Discarded COMDAT; retained equal copy: db0/src/cmd/t_list.o |
| `db0/src/cmd/t_set.o` | `tomo_db0::SetMemberTable::scan(unsigned long, unsigned long, std::vector<unsigned int, std::allocator<unsigned int> >&) const` | 0 → 19 | CD6: shared reverse-binary logical-home scan and MATCH filtering |
| `db0/src/cmd/t_set.o` | `tomo_db0::SetMemberTable::scan(unsigned long, unsigned long, std::vector<unsigned int, std::allocator<unsigned int> >&) const [clone .part.0]` | 0 → 1072 | CD6: shared reverse-binary logical-home scan and MATCH filtering |
| `db0/src/cmd/t_zset.o` | `tomo_db0::zset_owner_replace(tomo_db0::Shard&, tomo_db0::Slice, unsigned long, bool, std::vector<tomo_db0::ZsetEntry, std::allocator<tomo_db0::ZsetEntry> > const&, long, bool)` | 1030 → 0 | CD13: replacement metadata / expanded state, revised bridge signature or tiny copy adapter |
| `db0/src/cmd/t_zset.o` | `tomo_db0::zset_owner_replace(tomo_db0::Shard&, tomo_db0::Slice, unsigned long, bool, std::vector<tomo_db0::ZsetEntry, std::allocator<tomo_db0::ZsetEntry> > const&, long, unsigned char, bool, bool)` | 0 → 1126 | CD13: replacement metadata / expanded state, revised bridge signature or tiny copy adapter |
| `db0/src/cmd/t_zset.o` | `tomo_db0::zset_owner_replace(tomo_db0::Shard&, tomo_db0::Slice, unsigned long, bool, std::vector<tomo_db0::ZsetEntry, std::allocator<tomo_db0::ZsetEntry> > const&, long, unsigned char, bool, bool)::{lambda(tomo_db0::KvObj*, unsigned char)#1}::operator()(tomo_db0::KvObj*, unsigned char) const [clone .isra.0]` | 0 → 16 | CD13: replacement metadata / expanded state, revised bridge signature or tiny copy adapter |
| `src/cmd/geo.o` | `void tomo::(anonymous namespace)::cmd_geoadd<false>(tomo::Shard&, tomo::Op&)` | 4682 → 4821 | CD13: collect existing metadata and encoding; updated replacement call, including its emitted template helpers |
| `src/cmd/geo.o` | `void tomo::(anonymous namespace)::cmd_geoadd<false>(tomo::Shard&, tomo::Op&) [clone .cold]` | 243 → 250 | CD13: collect existing metadata and encoding; updated replacement call, including its emitted template helpers |
| `src/cmd/geo.o` | `void tomo::(anonymous namespace)::cmd_geoadd<true>(tomo::Shard&, tomo::Op&)` | 4873 → 5051 | CD13: collect existing metadata and encoding; updated replacement call, including its emitted template helpers |
| `src/cmd/geo.o` | `void tomo::(anonymous namespace)::cmd_geoadd<true>(tomo::Shard&, tomo::Op&) [clone .cold]` | 235 → 246 | CD13: collect existing metadata and encoding; updated replacement call, including its emitted template helpers |
| `src/cmd/geo.o` | `tomo::(anonymous namespace)::parse_search(tomo::Op&, tomo::(anonymous namespace)::GeoSearchOptions&) [clone .constprop.0]` | 3380 → 3368 | CD8: last destination replaces earlier STORE destination |
| `src/cmd/geo.o` | `tomo::(anonymous namespace)::reply_coordinate(tomo::Op&, double)` | 483 → 633 | CD7: Redis fixed-long-double formatting, zero/dot trimming and RESP framing |
| `src/cmd/geo.o` | `tomo::(anonymous namespace)::reply_geo_results(tomo::Op&, tomo::(anonymous namespace)::GeoSearchOptions const&, std::vector<tomo::(anonymous namespace)::GeoResult, std::allocator<tomo::(anonymous namespace)::GeoResult> > const&)` | 1932 → 1904 | UNRESOLVED: compiler inlining changed an unchanged-source GEO helper; audit FAIL |
| `src/cmd/geo.o` | `tomo::cmd_geo_xshard_local(tomo::Shard&, tomo::Op&, bool)` | 1290 → 1719 | CD13: local STORE destination metadata; updated replacement call |
| `src/cmd/geo.o` | `tomo::FlatStore::find_resident(unsigned long, tomo::Slice) const` | 0 → 108 | CD13: new cold current-destination lookup; no existing PRE body changed |
| `src/cmd/geo.o` | `tomo::FlatStore::find_in(int, unsigned long, tomo::Slice) const` | 0 → 630 | Discarded COMDAT; retained equal copy: src/main.o |
| `src/cmd/geo.o` | `void std::__adjust_heap<__gnu_cxx::__normal_iterator<tomo::ZsetEntry*, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> > >, long, tomo::ZsetEntry, __gnu_cxx::__ops::_Iter_comp_iter<tomo::geo_build_store(tomo::Op&, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> > const&, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> >&)::{lambda(tomo::ZsetEntry const&, tomo::ZsetEntry const&)#1}> >(__gnu_cxx::__normal_iterator<tomo::ZsetEntry*, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> > >, long, long, tomo::ZsetEntry, __gnu_cxx::__ops::_Iter_comp_iter<tomo::geo_build_store(tomo::Op&, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> > const&, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> >&)::{lambda(tomo::ZsetEntry const&, tomo::ZsetEntry const&)#1}>)` | 1858 → 1661 | UNRESOLVED: compiler inlining changed an unchanged-source GEO helper; audit FAIL |
| `src/cmd/geo.o` | `void std::__insertion_sort<__gnu_cxx::__normal_iterator<tomo::ZsetEntry*, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> > >, __gnu_cxx::__ops::_Iter_comp_iter<tomo::(anonymous namespace)::cmd_geoadd<false>(tomo::Shard&, tomo::Op&)::{lambda(tomo::ZsetEntry const&, tomo::ZsetEntry const&)#1}> >(__gnu_cxx::__normal_iterator<tomo::ZsetEntry*, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> > >, __gnu_cxx::__normal_iterator<tomo::ZsetEntry*, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> > >, __gnu_cxx::__ops::_Iter_comp_iter<tomo::(anonymous namespace)::cmd_geoadd<false>(tomo::Shard&, tomo::Op&)::{lambda(tomo::ZsetEntry const&, tomo::ZsetEntry const&)#1}>)` | 2742 → 2451 | CD13: collect existing metadata and encoding; updated replacement call, including its emitted template helpers |
| `src/cmd/t_set.o` | `void tomo::(anonymous namespace)::cmd_sscan<false>(tomo::Shard&, tomo::Op&)` | 3713 → 3395 | CD6: shared reverse-binary logical-home scan and MATCH filtering |
| `src/cmd/t_set.o` | `void tomo::(anonymous namespace)::cmd_sscan<false>(tomo::Shard&, tomo::Op&) [clone .cold]` | 117 → 117 | CD6: shared reverse-binary logical-home scan and MATCH filtering |
| `src/cmd/t_set.o` | `void tomo::(anonymous namespace)::cmd_sscan<true>(tomo::Shard&, tomo::Op&)` | 3713 → 3395 | CD6: shared reverse-binary logical-home scan and MATCH filtering |
| `src/cmd/t_set.o` | `void tomo::(anonymous namespace)::cmd_sscan<true>(tomo::Shard&, tomo::Op&) [clone .cold]` | 117 → 117 | CD6: shared reverse-binary logical-home scan and MATCH filtering |
| `src/cmd/t_set.o` | `tomo::FlatStore::find(unsigned long, tomo::Slice)` | 806 → 774 | Discarded COMDAT; retained equal copy: src/cmd/xshard.o |
| `src/cmd/t_set.o` | `tomo::SetMemberTable::scan(unsigned long, unsigned long, std::vector<unsigned int, std::allocator<unsigned int> >&) const` | 0 → 19 | CD6: shared reverse-binary logical-home scan and MATCH filtering |
| `src/cmd/t_set.o` | `tomo::SetMemberTable::scan(unsigned long, unsigned long, std::vector<unsigned int, std::allocator<unsigned int> >&) const [clone .part.0]` | 0 → 1072 | CD6: shared reverse-binary logical-home scan and MATCH filtering |
| `src/cmd/t_zset.o` | `tomo::zset_owner_replace(tomo::Shard&, tomo::Slice, unsigned long, bool, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> > const&, long, bool)` | 941 → 0 | CD13: replacement metadata / expanded state, revised bridge signature or tiny copy adapter |
| `src/cmd/t_zset.o` | `tomo::zset_owner_replace(tomo::Shard&, tomo::Slice, unsigned long, bool, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> > const&, long, unsigned char, bool, bool)` | 0 → 1053 | CD13: replacement metadata / expanded state, revised bridge signature or tiny copy adapter |
| `src/cmd/t_zset.o` | `tomo::zset_owner_replace(tomo::Shard&, tomo::Slice, unsigned long, bool, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> > const&, long, unsigned char, bool, bool)::{lambda(tomo::KvObj*, unsigned char)#1}::operator()(tomo::KvObj*, unsigned char) const [clone .isra.0]` | 0 → 16 | CD13: replacement metadata / expanded state, revised bridge signature or tiny copy adapter |
