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
