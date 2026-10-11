# txnfix REGISTER status addendum

The round-4 REGISTER is `/home/user/Projects/round4-read/REGISTER.md`, outside
this lane's worktree. The instruction to edit only this worktree prevents an
in-place update. These are the proposed status lines for the maintainer; no
finding is marked fixed before its proof is complete.

| Finding | Lane status | Remaining requirement |
|---|---|---|
| AT4.1 | WIP: optimistic EXEC validation, transparent retries and exclusive fallback implemented; new directed/stress rows pass both modes, atomics and database counts | Complete regression/differential, shutdown and hot-body proof; approve fallback |
| AT4.2 | Stage B core and fallback implemented, rejected by the explicit cost bar | Group lifetime redesign; full passing proof and zero ordinary-command cost |
| AT4.3 | Directed MSETNX concurrent-SET races pass, but Stage B is rejected by its cost bar | Same lifetime/cost requirement; no fixed/landed claim |

The crossed-WATCH pattern hangs PRE and completes under the new age rule.
DEL/UNLINK count at atomic 1 remains a reply constraint. Hits/misses can count
discarded EXEC attempts. The retained cut is a cleanup pin, and phantom
protection is enabled for whole-shard reads.

The earlier round-3 MULTI constraint needs its separate factual correction:
CONFIG SET is accepted; SAVE is refused by Redis too. Current engine refusals
are FLUSHALL, FLUSHDB, ACL, the six subscription-control commands, and DEBUG
RELOAD/LOADAOF. This lane does not change those refusals.

Txnfix2: latest merged base is 991d48f65. EXEC NX passes at least 8,192 trials
in both modes/settings on the merged Stage A image. The formerly reported
admission/open race already has IO-fence plus apply-drain guards; a deterministic
unit and two failing controls now prove both. Stage A selected ordinary hot
bodies and prior TLS offsets are restored. The default Stage B candidate adds
three instructions to ordinary MGET destruction and is stopped under the
owner's cost-bar exception. Its separate fallback adjustment removes a
reproduced writer/apply-inbox cycle. Bare atomic-0 RPOPLPUSH conservation fails
on merged PRE too; that control remains a failure. See the current txnfix2
section in MEASURE-REQUEST-txnfix.md for final proof status and commit boundaries.
