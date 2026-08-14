---
name: thredis-bloom-signature-saturation
description: "The atomic read-hold's 64-bit key signature is saturated — ~75% of holds are bit aliasing, not key overlap"
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**Measured 2026-08-08 with the new `tomokv_atomic_ownread_{reads,pending,held,conserv}` census** (commit
1a480b1fd, per-io-thread counters on tm_io_sig, no shared atomics). 8-key MGET:MSET, 200 conns,
static io4/ex4, atomic ON:

    keyspace   1:1 ops/s   held/reads   held/pending ("overlap")
    64         150821      51.4%        88.3%
    10000      577278      44.4%        72.4%
    2000000    494531      47.3%        74.9%

**The hold rate does not fall with keyspace size.** At 2M keys the true probability that an 8-key
read shares a key with an 8-key pending write is ~0.01%, yet 74.9% of such reads are held. That is
the signature of BIT ALIASING, not overlap: `csHashSignature(h) = 1ULL << (h & 63)` puts one bit per
key into a 64-bit word, so two DISJOINT 8-key sets collide with p ~= 1 - C(56,8)/C(64,8) ~= 66% per
pending group, higher with several pending. `conserv` (all-ones signature + detached-head arm) is
<0.5% of holds, so the gate's known conservatism is NOT the cause — the filter itself is.

**Consequence for the story we had been telling.** "1:1 is a keyspace artifact" was half right: the
ks=64 collapse is real overlap, but the ks>=10k losses are ~75% FALSE holds. So the 1:1 deficit is
mostly a fixable filter defect, NOT the structural `n_conns/commit_latency` ceiling, and NOT proof
that own-resolve or borrow is needed. Fix = exact key-hash check behind the filter (filter stays as
the cheap first reject; a filter MISS is still definitive proof of disjointness). Branch
2s-atomic-sigexact. Retest 1:1 at all three keyspaces after.

**FIX BUILT AND VALIDATED same day — branch 2s-atomic-sigexact @7c1bfb826.** Exact key-hash check
BEHIND the filter (filter stays the first test; a filter MISS is still definitive proof of
disjointness, only its ~75%-wrong "maybe" is settled). csGroup carries `uint64_t *key_h` + `key_h_n`
(560->576 bytes, all gate fields in the first cache line) in its own inline region; compares HASHES
not bytes, so hash inequality proves keys differ and a collision only costs a hold. Crucially it does
NOT use `g->subs[i]` — csPipeFreeStageSubs() and csMsetnxAdvanceReservations() free sub-fakes while
the group is still LINKED and pending, so the obvious implementation is an intermittent UAF that a
short test passes.

A/B (interleaved, 2 reps, static io4ex4, ks-swept):

    cell            A shipped   B exact     delta    held/pending A -> B
    1:1  ks 10k      586340      682463     +15.7%   71.2% -> 5.2%
    1:1  ks 2M       496001      584991     +18.5%   74.6% -> 0.85%
    1111 ks 10k     1058303     1214830     +14.8%   41.4% -> 2.6%
    1:1  ks 64       149978      147193      -1.9%   88.3% -> 74.2%   (overlap is REAL here)
    9:1  ks 10k      974079      956669      -1.8%   65.6% -> 15.1%

Correctness on B all zero: monotonic_vis 82534 reads 0 rollback/0 torn; nx_own_pending 3000 rounds
0/0/0; mget_own_ryow 15000 rounds 0; atomicity_test 375789 reads 0 torn ALL-SAME; 0 log incidents.
Three-regime pattern is exactly right: big win where holds were false, neutral where overlap is real.

**TWO FOLLOW-UPS the census handed us.** (1) After the fix, ~98% of the REMAINING holds at ks=2M are
the DETACHED-HEAD conservative arm (group completed and briefly unlinked from the FIFO before its
commit_seq publication, signature unreachable, so it holds); true key-overlap holds are 0.02%. That
arm, not overlap, is now the entire hold cost. (2) The consistent -1.8/-2.6% on 9:1 is the exact
check RE-HASHING the read's keys on every filter hit; csOwnReadSignature already computed those
hashes, so caching them should erase it.
Related: [[thredis-atomic-window]], [[thredis-atomic-session-2026-08-08]], [[thredis-wrong-two-quantities]].
