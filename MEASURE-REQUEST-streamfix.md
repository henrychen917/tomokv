# Redis 7.4 stream compatibility lane

## streamfix

Base: `83e0b809d0fdeb4bf43647bd0cada7a4f14f241d` on `cx-streamfix`.
Correctness work uses CPUs 96–111 and ports 20600–20699. No throughput measurements or push.

All nine assigned harness5 reproductions differ from Redis 7.4.10 on PRE in
2s/1s × uring/epoll. Raw typed replies and exact server argv are recorded in
`docs/streamfix/reproductions-pre.json`; binary hashes are in `docs/streamfix/pre-sha256.txt`.

Owner decisions required (stopped under the task's architecture/restriction rule):

- **OBJECT-IDLETIME-ZERO:** intentional zero-cost default. `FlatStore::configure_maxmemory`
  enables the idle clock only with maxmemory; both installation and accesses are inside
  maxmemory branches. Tracking idle time from creation without maxmemory requires newly
  executed metadata work on GET/SET/INCR/MGET/MSET, conflicting with this lane's zero-added-
  instructions requirement. Returning a fabricated age or enabling tracking only after
  OBJECT would not implement Redis semantics. No change to this root or its known failures.
- **RESTORE-IDLETIME-FREQ-IGNORED:** the supplied reproduction does not enable maxmemory,
  so faithful IDLETIME needs the tracking decision above. FREQ is also architectural:
  `KvObj::eviction_meta()` has five bits, `set_eviction_meta` masks to 31, and both owner
  and read-local LFU paths saturate at 31; Redis accepts 0–255 plus a decay clock. Merely
  storing FREQ 100 in that field yields 4. A cold reply-only override would misrepresent
  actual eviction/access behavior. The owner must choose full-width LFU metadata and its
  hot-path/layout budget. No partial fix or known-failure removal is claimed.

Remaining implementation and proof are in progress. Final gate counts and artifacts follow.
