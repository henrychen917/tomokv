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

CD4.4: partial SPOP preserves intset/listpack, including integer width; expanded
sets remain expanded. PRE fails / POST passes the six engine/mode legs. Conservation,
uniqueness, TTL and non-growing MEMORY USAGE assertions accompany every shape.
Cost per call, n members / k popped / B packed bytes: PRE first partial pop builds
an expected O(n) hashtable and then does expected O(k) picks, allocating O(n)
table/string storage permanently. POST single pop selects directly (intset) or
walks (listpack), then shifts at most B bytes, O(B) with no auxiliary allocation;
counted k>1 visits the compact set twice and rebuilds survivors once, O(n+B),
O(k+B) temporary storage, no rejection sampling and no permanent promotion.
These are algorithmic costs, not measured throughput or cycle claims.
Cumulative gate delta DQ=+2 / DF=+2; EXPECT constants unchanged.
