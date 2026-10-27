# T7 writer-episode schedule correction

The archived gate failed at `old.read() == [1, 1]`. The added reply diagnostic
reproduces `[101, 1]` on the saved POST binary (SHA-256 below) in 11/24 TomoKV
legs; Redis passes 3/3. This is a schedule defect, not a server ordering violation.
`Shard::watch_key_ready` inspects started holders, not waiter marks. When H and
E_old both claim k, E_old waits behind H and has no started claim on k. After H
finishes, MSET is allowed to pass before E_old places, even though E_old's age
precedes the writer stamp. Waiting for `atomic_txn_place_waits` proves the age
exists but does not prove a holder exists.

The corrected H claims k′ (same shard as k) and j. E_old places and reads k,
then waits on H's j claim. The test requires both the placement wait and three
stage tasks (two optimistic reads plus the escalated read of k) before sending W.
W now waits on E_old's started claim and cannot pass it. E_young's age follows
W's observed episode. Replies and data assert exactly H, E_old, W, E_young,
as on Redis. This also keeps the disconnected-script T15 leg independent of
AT4-WOUND-1: H is Executing and neither script is wounded.

Corrected direct run: 24/24 TomoKV + 3/3 Redis legs. Both runs use shards 16,
1s/read-local 1 or 2s/6:2, atomic 0/1, uring/epoll, EVAL/EVALSHA/FCALL,
server CPUs 48-55, driver CPUs 56-63. `before.json` and `after.json` retain
all leg outcomes. Final-source gate-job evidence is recorded in the lane report.

Reproduction command (original schedule plus reply diagnostic):

```sh
taskset -c 56-63 python3 tests/at412.py --case T7 \
  --binary /home/user/Projects/bins/at412-post-931130b2 \
  --oracle /home/user/Projects/redis74/src/redis-server \
  --cores 48-55 --port 20200 --output build/at412c/t7-before
```

Saved POST SHA-256: `931130b2593c92dc984dea47d6ce6b229a748c2314b819903a51c2c33eaaca76`.
