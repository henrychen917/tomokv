## scriptfix

Worktree `/home/user/Projects/cx-scriptfix`, branch `cx-scriptfix`; no push.
PRE is `5146b78ee89b64748dd46db970efa8086f653fa0`, built with normal flags into
`build/scriptfix/pre/tomokv`. POST is `build/tomokv`.

Implemented CC4.3 (readonly Lua environment), CC4.6's unrelated-operation reset
fix, CC4.25 (shared map/set reply budget), and CC4.27 (own function dumps above
4096 libraries). **CC4.6's per-executor state split remains an owner decision**:
[design and structural FCALL cost estimate](docs/scriptfix/single-state-design.md).
A mutex around Lua alone cannot compose with cross-owner staging, retries and
publication. No scheduler, ownership, layout, instruction-budget or element-limit
relaxation is included.

PRE reproductions ran before production edits. All eight new rows fail on PRE
for the audited findings; their logs are `docs/scriptfix/pre-<case>-<mode>.log`.
The Redis 7.4.10 oracle passes the corresponding Redis expectations, including
its unbounded aggregate replies and single mutable function state. Exact error
texts come from those live oracle replies. The array budget remains the existing
100000 units, including terminating scans; maps charge keys and values, sets
charge their keys, sharing that same counter through every nested shape.

`tests/scriptfix.py` accepts `--binary`, `--port`, `--cores`, `--mode`, and
`--engine`. It owns/reaps one fresh listener, refuses occupied ports, asserts
PING after conversion failures, and has a 55-second row deadline. Its separate
`functions --single-state` witness asserts the still-open Redis-wide counter
sequence; the ordinary `functions` gate row asserts the implemented reset fix.

Gate additions: `scriptfix {sandbox,functions,replies,dump} ({1s,2s})`, eight
rows from `job_scriptfix`, collected before the quick exit. DQ **+8**, DF **+8**:
**511 + 8 = 519 quick; 528 + 8 = 536 full**. The arithmetic comment is above the
unchanged EXPECT constants. The explicit fixture includes all eight labels.
The unchanged fixture checker refuses the owner-owned `EXPECT_FULL=528` despite
source/fixture agreement at 536; it cannot pass until the owner updates the
counts. Neither the constants nor the checker is weakened to conceal this.

Build, differential, POST-row and byte-identity proofs are in progress. Every
command is confined to CPUs 112–127; live proofs use target 112–119, oracle 120,
client 121–127, ports 25056–25069. No benchmark or full gate is run. The mainline
will run the requested performance null after correctness and identity review.
