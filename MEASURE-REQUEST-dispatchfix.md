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

Further assigned items, final proof, artifact identities and the 14-cell merit
request will be recorded here as the lane proceeds.

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
existing no-histogram state. **Limitation / scope question pending:** TomoKV's
batch/escalation timing does not record per-command histograms; actual histogram
recording is not implemented. No sampled slow-log data is presented as a complete
distribution. This is dispatch compatibility, not full latency-statistics parity.

Row `dispatchfix EX4.4 advertised children` is before the quick exit:
DQ +1 / DF +1; cumulative DQ +3 / DF +3.

### CC4.15 — subcommand grants

REPRODUCED on PRE in all four legs. Candidate passes 3352 exact comparisons per
leg, covering every advertised child grant/revocation, parent and category
precedence, case folding, first-argument grants, invalid and nested forms,
GETUSER/LIST rendering, SAVE/LOAD after every sequence, and live CONFIG admission
and revocation. Evidence: `docs/dispatchfix/CC4.15/{pre,post}`.

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
