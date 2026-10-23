# Redis 7.4 data-type compatibility

## datafix1

PRE: `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`. No push. Work and correctness
servers restricted to CPUs 48–63 and ports 29800–29899. Performance remains with
the maintainer; no throughput claims.

CD4.3: reproduced against Redis 7.4.10. Free-order GEO options and lookup/member
error precedence implemented, including COUNT grammar and ANY placement. Routing
extracts keys; validation occurs only after the source lookup. The directed gate
row runs 377 assertions per leg, both engines, split/fused/armed-fused, atomic 0/1.
PRE fails and POST passes all 12 legs. Exact paired replies and lifecycle records:
`docs/datafix1/{pre,post}-geo-proof.tar.gz`; initial independent oracle run:
`docs/datafix1/oracle-geo/`.

Gate counts are maintainer-owned and unchanged. Currently DQ=+1 / DF=+1, collected
before the quick exit. The label fixture includes the new source-declared label;
its EXPECT count check will remain red until the maintainer updates the counts.
Further item proofs, final identity, artifacts and merit request follow below.

CD4.4: small partial SPOP retains intset/listpack; a counted pop with
(n-k)*5 <= k rebuilds the survivors exactly at Redis's branch threshold. That
can narrow an intset, demote a hashtable to a listpack, or promote survivors
under lowered live limits. The expanded directed row passes six POST legs and
fails six PRE legs. It checks conservation, uniqueness, TTL, encoding, bounded
memory, and rebuilt intset memory against a fresh set of the same survivors.
Independent oracle receipts: docs/datafix1/oracle-spop-rebuild/; paired gate
proof: docs/datafix1/{pre,post}-spop-rebuild-proof.tar.gz.
Cost per call, n members / k popped / B packed bytes: PRE's first compact
partial pop builds an expected O(n) table, then takes expected O(k) picks,
allocating O(n) table/string storage permanently. POST's single compact pop
walks or indexes once and shifts at most B bytes, O(n+B) with no auxiliary
allocation. Small counted compact pops sample and rebuild in linear passes,
O(n+B) time and O(k+B) temporary storage. Large counted pops sample survivors
in one pass, build them once, and emit the remainder in another pass: O(n+B)
plus expected hash insertion work if current limits require a table, with
O(n-k + survivor bytes) temporary storage. There is no rejection sampling or
repeated compact membership search. These are algorithmic costs, not measured
throughput or cycle claims. Cumulative gate delta DQ=DF=+2; EXPECT unchanged.

CD4.5: one-node quicklists demote after LPOP/RPOP, LSET, LREM (when something was
removed), LTRIM (including a no-op trim), blocking/MPop and mover removals. The
size check derives Redis listpack integer/string framing, header and back-lengths;
it uses <= half the live count/byte limit and transfers the sole packed buffer
without allocating. PRE fails / POST passes 12 legs, with count limits 4/5/8,
4096/4097-byte packed boundaries, all pop/move verbs, contents and memory shrink.
The existing edgeenc shrink assertion now expects Redis list demotion (other types
unchanged), supported by the independent oracle receipts. Cumulative DQ=DF=+3.

CD4.6: locale-collate defaults to the environment, supports boot/CONFIG SET/GET/
REWRITE, rejects invalid names and duplicate parameters with Redis's exact text.
Each ALPHA sort without STORE duplicates the published locale under a cold mutex,
then uses strcoll_l with that retained object for every comparison. Publication
never calls setlocale, and replacement cannot free a running sort's context.
STORE stays binary. Mixed-case/punctuation/accented weights, SORT_RO, dynamic BY,
all source types and concurrent CONFIG/sort checks pass 12 POST legs; PRE fails.
Config consumes 8 reserved bytes; all existing fields and the 624-byte size stay
fixed. The differential's stale C-only implementation comment is corrected; its
fixed-order corpus still requires C collation. Cumulative DQ=DF=+4.

CD4.10: BITFIELD checks the first byte like Redis; indexed offsets use explicit
unsigned machine-word multiplication, matching the oracle's wrapped # offset
behavior without C++ signed overflow. GET/SET/INCRBY/GETRANGE/STRLEN and refusal
atomicity pass six POST legs; PRE fails. Redis lookupStringForBitCommand grows to
(last_bit >> 3)+1 without a second bulk-limit check. A field is at most 64 bits,
so growth can exceed the configured limit by at most eight bytes; the existing
UINT32_MAX-64KiB supported cap leaves ample representable space. A static_assert
pins this proof. Read-only probes exercise the maximum supported cap without a
multi-gigabyte allocation. Cumulative DQ=DF=+5.

CD4.11: HEXPIRE/HPEXPIRE/HEXPIREAT/HPEXPIREAT validate negative/overflowing expire
values before condition and FIELDS parsing; key type lookup retains its earlier
precedence. The matrix crosses all four commands, present/missing/wrong-type keys,
invalid values, conflicting conditions and malformed field tails. PRE fails and
POST passes all six engine/mode legs. Cumulative DQ=DF=+6.

CD4.12: RAND validates counts and optional arguments before key lookup; the two
WITHVALUES/WITHSCORES half-range errors use Redis's short text. SRANDMEMBER excess
arguments return syntax before numeric parsing; ZRANDMEMBER parses the count
first. ZSCAN now emits the HSCAN-only NOVALUES error. A 1,056-case table covers
all RAND/SCAN verbs, missing/present/wrong-type keys, numeric boundaries, conflicting
errors and the register's remaining controls. PRE fails / POST passes six legs.
Cumulative DQ=DF=+7: all seven rows are collected before the quick-tier exit.
Maintainer EXPECT values should become QUICK 692 / FULL 709 (base 685 / 702);
this lane leaves those constants unchanged.

Inlining budget derivation: initial set IPA sizes grew 17685→17957 and
17505→17775 (db0); normal zset grew by 38. Bounded compile-only trials selected
set 24222 / db0 23842 and normal zset 33447. Every trial's command, object digest
and complete changed-body inventory is under docs/datafix1/budgets. These retain
all ordinary storage hot bodies; final whole-tree audits follow. No runtime knob
or algorithm change was introduced by the budget adjustment.

Merit request (maintainer only; NOT RUN here): use the gate's own ABBA instrument
and the exact 14 rows in tests/wbland_merit_cells.txt: h05, h06, p8g, p8s, d1g_l0,
d1s_l0, m8g_l0, v1g_l0, d128g_l0, d32g_l1, d8s_l1, d32s_l1, x9_32_l1, x9_32_l0.
First establish a same-binary null, then PRE/POST, PRE/PAD-A and PAD-A/POST with
matched offered load and the cell's declared geometry. Rate is the verdict for
rate cells; latency is the verdict for the two p1 cells. Report cycles/op, IPC and
instructions/op together and judge against the instrument's measured null spread.
A new spread above 2% needs investigation, not a relaxed threshold. The question
is whether the compatibility repair preserves ordinary workload merit. No
performance result or improvement is claimed by this lane.

Artifacts: PRE build/datafix1/pre-src/build/tomokv; POST build/tomokv; PAD-A
build/datafix1/PAD-A/tomokv. Digests: docs/datafix1/SHA256SUMS. PAD kind A is PRE
behavior (unchanged PRE objects) with 3,136 inert bytes appended to match POST's
7,750,662-byte .text. It controls total text size and the unchanged layout locks,
not every function address. Config's new cold pointer consumes PRE's reserved
storage; existing field offsets stay fixed. Exact link/object provenance is in
docs/datafix1/pad-kind.json; tools/datafix1_pad.py reproduces the arm.

Final identity: tools/ccfix_audit.py inventories 16,828 emitted bodies, 295 changed;
all 1,220 selected hot bodies are canonical-equal to PRE. Its command-only INFO/
CONFIG/ACL admission policy rejects the intentional data-type changes, as expected.
The stricter linked audit (tools/infofields_artifacts.py) likewise rejects its
INFO-only whitelist: 4,376/4,484 ordinary object bodies match and 2,593/2,690 linked
ordinary bodies are proven. Every changed body, including compiler spillover in
unedited helpers, is listed with a reason in docs/datafix1/body-reasons.json.
All ten linked GET/SET/MGET/MSET handlers are proven against their PRE object
implementations (linked-primary.json). These are identity proxies, not merit.
Both namespaces retain Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore
944, Rob<64> 192, AtomicEntry 144 and Config 624. Only Config's reserved area
changes definition; all existing non-reserved field offsets match (layout-reviewed.json).

Production proof: PRE and POST each pass all 57 selected storage_units, atomic_units
and netcmd_units rows, including encodingfix and storesize. Both builds pass
make -q for all, all 37 targets listed in job_production_units, and mdbqsbr-live-arms
(freshness.log). Complete gate-owned logs are archived in {pre,post}-units-proof.tar.gz.
The gate harness self-test passes 67/67 when run alone (gates-test-serial.log).
Two earlier concurrent runs had outer scheduler-fixture timeouts; their original
logs are retained. No fixture assertion or deadline was changed.

An initial concurrent differential run hit its 900-second outer row watchdog
before the last seed completed. All three overlapping coordinators were stopped
and their incomplete logs archived, explicitly marked LANE INTERRUPTED. Those
are not claimed as complete matrix passes. The serial reruns use the unchanged
standard permanent seeds 7,19,20,23 plus rotating seed 25, cloned from the same
pre-run history for matched PRE/POST arms. Each full leg inventory remains intact.
