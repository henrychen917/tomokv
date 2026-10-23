# Dispatch and routing refinement

## dispatchfix

Base: `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`; branch `cx-dispatchfix`.
All correctness work and builds use CPUs 96–111, builds `-j16`, ports 28800–28899.
Redis source: `/home/user/Projects/redis/src`; oracle:
`/home/user/Projects/redis74/src/redis-server`. No performance measurements or throughput claims.

### EX4.10 — container outer arity

REPRODUCED on PRE through `GATE_ONLY_JOBS=dispatch_arity tests/gate.sh quick`,
with every 1s/2s × epoll/uring leg. Server CPUs 96–103, client CPUs 104–111,
16 shards, 2s ratio 6:2, databases 16, read-local 0, balancers off.
Nine of seventeen oracle comparisons fail per leg: XINFO STREAM's outer maximum
masks missing keys and wrong types as well as the stream grammar error.

Removed XINFO's artificial maximum. Valid child routing now reaches the stream
owner, performs the key lookup, and reports Redis's exact tail error. Fixed
child arities and MEMORY's grammar-before-lookup behavior remain covered by
oracle assertions. The same gate job passes all four legs on the candidate.
Evidence: `docs/dispatchfix/EX4.10/{pre,post}`. The first PRE invocation used
the oracle binary directory as REDIS74_ROOT, so its source preflight warned;
all runtime oracle legs ran. Later runs use the source root and explicit oracle binary.

Gate row `dispatchfix EX4.10 container outer arity` is collected before the
quick-tier exit: DQ +1 / DF +1. EXPECT constants are untouched.

### EX4.11 — container errors

REPRODUCED at the same four mode/engine geometries. The metadata-driven table
checks every advertised container and child at too-few/too-many arguments,
unknown children at both short and long arities, and the report's handler
grammar/lookup cases. Candidate passes the complete table against the oracle.
Evidence: `docs/dispatchfix/EX4.11/{pre,post}` (gzip JSON preserves exact replies).

Fixed CLIENT's unknown-child reply, ACL HELP, XINFO STREAM option errors and
canonical COUNT parsing, XGROUP's option/key/group/ID precedence and missing-key
error, and OBJECT's lookup-before-policy checks (FREQ and IDLETIME).
COMMAND unknown/COUNT x/HELP x/GETKEYS/GETKEYSANDFLAGS without arguments and
SCRIPT HELP x are NOT REPRODUCED on a7dfb9d23 at these exact geometries: their
PRE replies already equal Redis, as the saved table demonstrates.

One row, `dispatchfix EX4.11 container errors`, collected before the quick exit:
DQ +1 / DF +1; cumulative DQ +2 / DF +2. EXPECT constants remain unchanged.

### EX4.4 — advertised children

REPRODUCED: ACL DRYRUN and LATENCY HISTOGRAM are the two advertised children
that answer unknown-subcommand on PRE. The new row probes all 96 advertised
children and compares directed DRYRUN results with Redis, including wrong
arity, absent users/commands, key/channel denials, and proof that a dry-run
SET leaves the value unchanged. All four mode/engine legs pass on the candidate.
Evidence: `docs/dispatchfix/EX4.4/{pre,post}`.

ACL DRYRUN evaluates the immutable permission image and emits Redis's bulk
denial descriptions without executing the embedded command or logging a denial.
LATENCY HISTOGRAM now dispatches and returns the empty RESP2/RESP3 map for the
existing no-histogram state. **Compatibility limitation:** TomoKV's
batch/escalation timing does not record per-command histograms; actual histogram
recording is not implemented. No sampled slow-log data is presented as a complete
distribution. This is dispatch compatibility, not full latency-statistics parity.

Row `dispatchfix EX4.4 advertised children` is before the quick exit:
DQ +1 / DF +1; cumulative DQ +3 / DF +3.

### CC4.15 — subcommand grants

REPRODUCED on PRE in all four legs. Candidate passes 4059 exact comparisons per
leg (240 rule sequences), covering every advertised child grant/revocation, parent and category
precedence, case folding, first-argument grants, invalid and nested forms,
GETUSER/LIST rendering, SAVE/LOAD after every sequence, and live CONFIG admission
and revocation. Evidence: `docs/dispatchfix/CC4.15/{pre-complete,post-complete}`. PRE completes
the same full table and fails 3520/4059 comparisons in each leg. The old
`tests/acl.py` assertion rejecting `+select|0` was corrected only after retaining
the exact Redis SETUSER/GETUSER/DELUSER replies in
`docs/dispatchfix/acl-firstarg-oracle-replies.json`. Both existing ACL battery
rows now run all four mode/engine legs, for atomic off and on, under their
original labels; POST passes all eight legs and PRE fails the corrected grant
assertion in all eight.

Child permissions use an immutable bitmap sized from generated metadata; only
rules touching children allocate it. Root bits and the unrestricted fast gate
are retained. Parent/category grants update children and reset affected legacy
first-argument grants. Retained rules remove earlier child rules when a parent
is replaced, matching Redis's rendering and replay order. Replay verification
checks all effective child bits and the unordered first-argument set.

Selector syntax and read/write key-pattern rules remain the existing unsupported
surfaces; this item implements root-user subcommand/first-argument rules and does
not enable those independent ACL features.

Row `dispatchfix CC4.15 ACL subcommand grants` is before the quick exit:
DQ +1 / DF +1; cumulative DQ +4 / DF +4. EXPECT constants are untouched.

### EX4.17 — uniform bucket ranges and old-file recovery

REPRODUCED before editing the map, through the new gate job in all four legs.
At 200 shards PRE assigns 81 buckets to each of shards 0–198 and 265 to shard 199.
The directed test finds a key for **every one of the 16,384 buckets**, using the
persisted random hash seed, and checks DEBUG SHARDS against the exact expected map.
POST assigns 81 or 82 buckets per shard. This is an exact count, not a random-load estimate.

The authoritative map and Shard::init now share inverse boundaries. Cold recovery
accepts both file versions: v1 retains its legacy section validation, then each
current owner loads only keys belonging to its new ranges. Legacy FLUSH records
clear only the portion belonging to that old source stream. AOF publishes a durable
old-file manifest, then a synced v2 increment and its manifest before recording;
it never appends new-map records to a v1 non-divisor stream. Divisor geometries
retain the identical v1 map and header version. New non-divisor files use v2.

Authenticated PRE fixtures in tests/fixtures/dispatchfix-pre cover snapshot and
AOF, binary keys straddling old/new boundaries, grouped MSET, DEL, FLUSHALL,
FLUSHDB, SWAPDB, multiple logical databases, TTL, and all container value types.
Oracle assertions establish their logical contents. POST loads each PRE file,
checks every expected reply, appends data, restarts, rewrites and restarts again.
The same row runs PRE recovery even though the final balance assertion fails.
All four POST legs pass; read-local and both balancers are enabled during recovery
verification. Evidence: docs/dispatchfix/EX4.17/{pre,post}.

Dependency audit: key LB weights and moves use each Shard's [bucket_begin,
bucket_end); client LB uses owner/client weights and no bucket division; read-local
routes through Router then current shard ownership. DEBUG SHARDS uses that same
map, including the physical database namespace. Existing tests discover placement
through DEBUG SHARDS or use Shard range accessors; numeric 16384 occurrences in
other batteries are payload/capacity boundaries. The complete search is retained
in docs/dispatchfix/router-dependencies.txt.gz. The balancer/persistence jobs are
also included in the broader proof below.

Row `dispatchfix EX4.17 uniform routing and legacy recovery` is collected before
the quick-tier exit. Cumulative DQ +5 / DF +5: maintainer counts should become
EXPECT_QUICK=690 and EXPECT_FULL=707. Both constants are untouched.
Collection is at gate.sh lines 4242–4246, before its quick-tier exit at line 4360;
the existing ACL row expansion adds no row. The label
fixture check identifies exactly these five missing labels and no extra labels;
its refusal is retained in docs/dispatchfix/label-fixture.log.

### Build, identity and measurement arms

`make -j16 all` and the gate's production-unit build completed. All 40 targets
(the server, every listed job_production_units target, and both mdbqsbr live arms)
pass `make -q`; see docs/dispatchfix/freshness.json. All eight layout locks remain
unchanged. The separate PRE object rebuild has identical loadable sections to the
frozen PRE binary, excluding only the build-id; debug/source paths explain the
file SHA difference (identity/pre-rebuild.json).

The three established identity tools ran against PRE: lbstall_artifacts,
ccfix_audit and deadswitch/linked_bytes. Their differences are preserved rather
than treated as a stop condition. The complete object inventory has 16,871
bodies, 534 changed/new; every one is listed with its reason in
identity/object-body-reasons.{md,json}. The linked inventory has 8,693 groups,
521 changed, including 12/12 identical GET/SET/MGET/MSET groups. No compiler budget
change was needed to preserve those bodies. Twelve object hot-helper differences
are cold-loader FlatStore erase instantiations; the final linked hot audit reports
483/489 strict matches. The six remaining linked differences are only constant
pool/jump-table references: separate decoding proves identical nonaddress bytes,
the same eight-byte constant, and all 18 destinations for each of five tables.
See identity/hot-linked-diffs.json and hot-relocations.json; the original strict
checker discrepancies remain in the inventory. Identity is not a merit verdict.

| Arm | Worktree path | SHA-256 | .text bytes |
|---|---|---|---|
| PRE | `build/tomokv-PRE` | `2d8265e581c9f871dd36208039a915ea2373de458123dfc6febf63ce22dd25bd` | 7,747,526 |
| POST | `build/tomokv` | `2eb3a851906822dfe55740646feca8fc6bead8762ce3c35924c654e1a638876d` | 7,752,758 |
| PAD-A | `build/tomokv-PAD-A` | `949fb8fb6851ef7c3975bd1c16d18da4998ffcc17b2fe2d1b448c7a0ae724ba6` | 7,752,758 |

**PAD kind (A), behaviour twin:** PRE source behavior with POST's cold ACL and
persistence image layouts, plus inert tail padding matching POST's total .text
size. The data layouts are checked through DWARF in both namespaces. It does
**not** match internal function positions, so it cannot isolate every code-layout
effect. All five directed gate rows retain their PRE failures on this twin.
Build recipe and receipt: docs/dispatchfix/pad.py and pad/receipt.json. No PAD-B.

### Maintainer merit request — generic 14 cells

Run the unchanged 14 cells in docs/dispatchfix/merit-cells.txt with the gate's
instrument, eight server cores, 16 shards, the paper's databases=1 geometry,
matched offered load, and a contemporaneous same-binary null. The parser accepts
all 14; merit-cells-parsed.json retains the decoded cells. Compare PRE/POST and
PRE/PAD-A, and compare POST/PAD-A for any moving cell. Rate at matched offered load
decides rate cells; the instrument's latency score decides depth-one cells.
Record cycles/op, instructions/op, IPC, p99 and p99.9 and apply the instrument's
existing acceptance rules. A behavior effect must survive the size/layout
control's stated limits. No throughput or zero-regression performance claim is made.

NOT RUN: performance benchmarks, measurement load generators, these merit cells,
and full tests/gate.sh iteration. Those remain maintainer-owned. Correctness uses
only selected gate jobs, never a performance tier or full iteration.
