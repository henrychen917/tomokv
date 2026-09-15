LANE cx-lbstall (worktree /home/user/Projects/cx-lbstall, branch from cx-final = v3). P0: the default-on key/client balancer stalls a LIVE
connection's already-read requests for ~5 s under open-loop load.
EVIDENCE (mainline, tools/tailgen from cx-tailgen — a Poisson open-loop RESP generator, 717K/s, 512 conns over 16 threads, 8:2
GET:BITCOUNT, v3 5d567adf5 booted as the tail cells do: --shards 256 --thread-mode 1s --atomic 1 --overlap 1):
 - LB default ON: p50 0.06 ms, p99 0.67 ms, but p99.9 320-1450 ms, p99.99 4.0-4.5 s, MAX = 4999.5 / 5000.2 / 5000.96 / 5001.7 ms in every
   run; one connection reaches ~7000 outstanding (= 1400 arrivals/s x 5 s); 1-3 episodes per 20-s window (any-connection-over-64 fraction
   0.25-0.65). Kernel queues sampled every second: server RecvQ <= 69 B, server SendQ <= 160 B, client RecvQ < 4 KB, client SendQ <= 92 B
   -> the requests were READ by the server and UNANSWERED for 5 s. Tool side clean (unsent bytes 0, pacing lag p99.9 24 us).
 - --client-lb 0 --key-lb 0: p99.9 1.03-1.26 ms, max outstanding 5-6, zero episodes. Same binary, same load.
 - src/core/weighted_lb.h:28 `kMoveTimeoutNs = 5 s`. src/core/io_loop.h ~300-320 client_transfer_ready() refuses while "connection has an
   unfinished executor completion" / "ROB, reply, borrow busy" / "deferred out-of-band frame" / transient CLIENT state; ~2036
   lb_client_move_started(move.id, now). Hypothesis: once a move is pending for a connection its traffic is held so it can quiesce, but a
   readiness predicate depends on progress that the hold itself prevents (open-loop arrivals never let the ROB/executor drain), so the
   connection sits until kMoveTimeoutNs cancels the move. memtier (closed loop, <= 8 in flight) quiesces in microseconds and never sees it.
 - Splits running on mainline (--client-lb 0 alone, --key-lb 0 alone); results will be appended to this file as LBSTALL-SPLIT.
TASK: 1) Find the exact hold: instrument (behind a debug counter, no hot-path cost when LB is stable) which predicate refuses and for how
long a connection's frames are parked while a move is pending; unit-test the scenario (a connection with continuous arrivals while a
move is requested). 2) FIX under the owner rule "LB never inhibits the hot path": a pending move must never hold a connection's traffic
for longer than a bounded few passes; if the connection cannot be made quiescent within that bound, the move is REFUSED immediately
(the balancer picks another candidate), not held until a 5 s timeout. kMoveTimeoutNs stays as a last-resort guard only. Same for key-lb
shard moves if they park ops. 3) Prove: reorder=0/1 hot bodies unchanged when LB is stable (byte-compare), size locks, all units incl.
TSAN, on cores 112-127 (taskset, make -j8). Do NOT boot a server on the box; mainline runs tailgen before/after and the gate.
Deliver build/tomokv-lbstall (POST) + MEASURE-REQUEST.md. Commit. End with CX-lbstall-DONE.

LBSTALL-SPLIT (mainline 20:19): --client-lb 0 ALONE removes the stall (round 1: p99.9 1.09 ms, max outstanding 5, zero over-64 episodes).
--atomic 0 with both balancers on still stalls (3/3 rounds, ~7000 outstanding). => the CLIENT balancer's connection migration is the hold;
key-lb shard moves are not (key-lb-only run pending, expected to stall with client-lb on). Focus on request_client_transfer /
client_transfer_ready / the parse hold placed on a connection with a pending client move, and kMoveTimeoutNs.
LBSTALL-SPLIT 20:22: --key-lb 0 ALONE (client-lb on) STILL stalls (out_max 7005, over-64 fraction 0.36). Attribution closed: client-lb connection migration is the sole cause; key-lb shard moves are clean.
