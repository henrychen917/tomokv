# pttlfix — deadline-bounded differential TTL checks

Completed on 2026-10-07 in `/home/user/Projects/cx-pttlfix`, branch
`cx-pttlfix`. `git fetch origin cpp` and `git merge origin/cpp` confirmed the
starting tree was current at `08a68fcba`. Implementation checkpoints:
`80ebd0928`, `8a0969574`. No push.

**Required proof: 288/288 live suite legs PASS, zero differences, 112,784 TTL
checks.** Three contended lifetimes and one quiet lifetime passed in each
geometry, with both atomic modes and all six frozen seeds. The task's explicit
CPU 112–127 correctness-proof instruction supplies the scoped live-run
authorization. No compilation or performance measurement was performed.
Production source, layouts, build budgets, EXPECT values and existing fixtures
are unchanged.

The investigation inputs were `round3-read/REGISTER.md` (AT15 at15c),
`MEASURE-REQUEST-at15c.md` and its `docs/at15c` evidence, plus
`MEASURE-REQUEST-storesize5.md`'s `failed-first-split-1` and
`failed-first-attempt` findings. This change addresses the comparison contract;
it does not make a server-latency or performance claim.

| Contract | Before | After |
| --- | --- | --- |
| Relative TTL | Target versus oracle, at most one native unit apart | Each server independently checked against the generated deadline and its own request timing |
| Equal positive replies | Accepted without checking the deadline | Both deadline checks required |
| Missing/persistent results | Equal negative sentinels | Same exact `-1`/`-2` class; live results cannot match a sentinel |
| Absolute expiry probes | One native unit could be tolerated | Byte-exact |
| Other replies | Existing semantic normalizers and comparison | Existing normalizers retained; normalized bytes exact, including OBJECT IDLETIME |
| Summary | `clock tolerances`, counting only relaxed unequal replies | `deadline-bounded TTL checks`, counting every integer TTL reply pair, including equal/sentinel replies |

For an absolute millisecond deadline `D`, remaining milliseconds `R`, this
server's batch-send wall-clock millisecond `S`, and this particular reply's
monotonic send-to-completed-read latency `E`, the check is:

```text
0 <= (D - R) - S <= E + 1 ms
```

The timestamp is captured before each server's send, and after each individual
reply read, including buffered pipeline replies. The two servers have separate
windows. Integer nanosecond arithmetic avoids precision loss for large absolute
deadlines. TTL rounds to the nearest second: a reply `q` represents
`max(0, 1000*q-500)..1000*q+499` remaining milliseconds. HTTL rounds upward:
`max(0, 1000*q-999)..1000*q`. The comparator requires the reconstructed command
time interval to intersect that request's window. It does not grant a fixed
extra second. Zero remains a live result; missing timing or a missing deadline
for a live TTL is a failure. Hash replies validate every field, field order,
integer framing and array length. Matching errors remain byte-exact and do not
increment the integer TTL counter. Each array reply pair counts once.

There is an unavoidable distinction for relative setters: `EXPIRE`, `PEXPIRE`,
`SET EX/PX`, relative GETEX/SETEX/PSETEX, HEXPIRE/HPEXPIRE and relative RESTORE do
not name a single generator-known absolute instant. Their intended deadline is
recorded as `duration + [setter send, setter read + 1 ms]`, independently for
each server. The later query still has its own `E + 1 ms` window. This retains
the relative command grammar and bounds the setter's uncertainty using its
actual request, without learning a deadline from either TTL reply. Absolute
setters, including edgetime's existing future deadlines, retain exact points.
The ledger follows successful conditional mutations, persistence, overwrite,
field replacement/deletion, COPY and RENAME.

One edgetime tail case (`GETEX ... EX 600 EX 1200`) formerly compared
PEXPIRETIME immediately after a relative setter. Those absolute timestamps are
not deterministic across servers. Its TTL check remains in place; one shared
PEXPIREAT is now inserted afterward, before the byte-exact absolute probe.
The stream has 4,427 operations instead of 4,426; the historical failing
positions 445, 1526 and 2910 retain their positions. No suite or public gate
row is added. Wiredump also now prints an error only at the operation that
adds a difference and retains the unequal PTTL bytes.

The live proof used the existing mainline binary, copied into this worktree
as `build/pttlfix/tomokv`. The source worktree's `src` and Makefile match
`08a68fcba`. PRE/POST server behavior and bytes are identical; the harness is
the change. No PAD arm is applicable.

| Artifact | SHA-256 |
| --- | --- |
| Mainline target | `bdf7cf66f258a1c923f38fd54610eb8b405670d298ffe531c5cb84c320a54865` |
| Vanilla Redis 7.4.10 oracle | `ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b` |

Exact invocation, from this worktree:

```sh
bash docs/pttlfix/prove.sh "$PWD/build/pttlfix/tomokv" \
  "$PWD/build/pttlfix/live-proof-1"
```

The runner invokes `tests/differ_gate.sh` serially with target CPUs 112–119,
16 shards, split ratio 6:2 or fused/read-local=1; Redis is on CPU 120 and
clients on 121–127. Atomic=0 and atomic=1 each receive a fresh target boot.
The six seeds are 7, 19, 20, 23, 21 and 22. Suite names are stored one per line
in `docs/pttlfix/suites.txt`. Eight owned `taskset -c CPU yes > /dev/null`
processes, one on each CPU 112–119, remain alive across all three contended
lifetimes and both geometries. They are terminated and reaped before the
quiet runs. Saved `/proc` affinity observations show the target's singleton
worker masks, the oracle on 120, and the eight contention processes on their
specified CPUs. Every contended wrapper verifies all eight PIDs are alive.

The standalone focused mode refuses use as a fanout child, labels its output
`DIFFER FOCUSED PROOF`, and does not emit a full-matrix completion artifact.
Default full-gate inventory and accounting are unchanged. The summarizer
requires every leg, its exit status, exact TTL-check inventory and executed
command-coverage artifact. Synthetic accounting controls reject missing legs,
missing checks, missing coverage and failing legs; those controls are clearly
labelled and are separate from the live receipts.

| Condition | Lifetime | Geometry | Suite legs | Differences | TTL checks | Result |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| Contended | 1 | Split | 36 | 0 | 14,098 | PASS |
| Contended | 1 | Armed fused | 36 | 0 | 14,098 | PASS |
| Contended | 2 | Split | 36 | 0 | 14,098 | PASS |
| Contended | 2 | Armed fused | 36 | 0 | 14,098 | PASS |
| Contended | 3 | Split | 36 | 0 | 14,098 | PASS |
| Contended | 3 | Armed fused | 36 | 0 | 14,098 | PASS |
| Quiet | 1 | Split | 36 | 0 | 14,098 | PASS |
| Quiet | 1 | Armed fused | 36 | 0 | 14,098 | PASS |
| **Total** | | | **288** | **0** | **112,784** | **PASS** |

Every armed-fused atomic lifetime passed the existing read-local witness:
2,757–2,944 hits. These witnesses are additional private wrapper checks, not
suite legs. Raw evidence and per-suite totals are in
[proof-results.json](docs/pttlfix/proof-results.json) and
[proof.log](docs/pttlfix/proof.log). No failing lifetime was replaced or retried.

TTL reply-pair counts below were predicted from the generated streams (with
wiredump counted through an in-memory transport), then verified exactly in
every live leg. Hexpire has three additional directed error replies per seed;
those remain byte-exact and are excluded from the integer TTL counter.

| Seed | edgetime | hexpire | wiredump |
| ---: | ---: | ---: | ---: |
| 7 | 77 | 299 | 789 |
| 19 | 73 | 291 | 801 |
| 20 | 64 | 280 | 822 |
| 23 | 61 | 327 | 824 |
| 21 | 74 | 265 | 830 |
| 22 | 64 | 257 | 851 |
| **One geometry/atomic pass** | **413** | **1,719** | **4,917** |
| **All required live runs** | **6,608** | **27,504** | **78,672** |

The comparator unit's negative control injects `D=100000 ms`, send=1000 ms,
elapsed=2 ms, reply=98996 ms. The inferred offset is 4 ms, exceeding the
3 ms bound: comparison **FAILS**, even when both replies contain the same
wrong value. A second control drives the actual pipelined runner with fake
out-of-window replies and requires process exit **1**. The valid 7 ms
inter-server difference control passes using independent measured windows;
a narrow oracle window rejects the same value if only the target window
would have admitted it. Absolute probes reject a 1 ms mismatch.
The standalone invocation of this comparator control also returned exit 1;
[negative-control.log](docs/pttlfix/negative-control.log) retains its raw
deadline, request window, fake reply and failure status.

Validation commands and receipts:

```sh
python3 tests/differ_test.py -v
python3 tests/_differ_history.py self-test
python3 tests/differ_fanout_test.py
python3 docs/pttlfix/replay_receipts.py
bash -n tests/differ_gate.sh docs/pttlfix/prove.sh
```

The 17 comparator/runner tests, history self-test and 18 fanout tests pass.
The history mock now accepts `makefile(..., buffering=...)` and emits framed
integer TTL sentinels. Syntax checks and `git diff --check` pass.
The serverless historical replay accepts **8,073/8,073** relative TTL replies
across **105** AT15c traces, including **618** live TTL replies and the recorded
compiler-contention cases. Five legacy PEXPIRETIME mismatches from the old
relative-GETEX tail are retained explicitly in
[historical-replay.json](docs/pttlfix/historical-replay.json); they are not
silently relaxed or counted as passing absolute probes. The fresh proof uses
the corrected deterministic tail.

A supplementary quiet run checked the other generated relative-setter paths:
string and bitfield, all six seeds, both geometries and both atomic modes.
It passed **48/48** legs with **4,652** additional TTL checks (string 4,628;
bitfield 24). Its suite list is one name per line in the archived
`relative-suites.txt`; it uses the same focused wrapper, binary, ports and CPU
geometry. [relative-results.json](docs/pttlfix/relative-results.json) records
these separately from the required 288-leg proof.

[live-receipts.tar.gz](docs/pttlfix/live-receipts.tar.gz) preserves all eight
required wrappers, all 288 leg logs and coverage files, frozen seeds, command
coverage, the supplemental runs, source/binary hashes, PID and affinity
evidence, and durable per-leg journals. Its SHA-256 is
`8dd7d04081a8e08c2a5db88c501252e335db89a86fe6058cc5bdfbcbe494668e`, also saved
in [SHA256SUMS](docs/pttlfix/SHA256SUMS). The proof's final hash checks confirm
the target and harness remained unchanged for its entire duration.
[cleanup.json](docs/pttlfix/cleanup.json) records that ports 18899/18900 are
free and all eight owned contention PIDs are gone. No additional pttlfix
measurement is pending.

Public gate rows: **+0 quick / +0 full**. The quick-tier branch is at
`tests/gate.sh:3355`, with its exit at line 3359; no row is inserted on either
side. EXPECT remains **500/517** at lines 279/280. No existing fixture is
edited. This is a focused correctness proof, not a full iteration-gate or
performance acceptance result. The session's higher-priority search rule
required `rg`, so the grep-only convention could not be followed.
