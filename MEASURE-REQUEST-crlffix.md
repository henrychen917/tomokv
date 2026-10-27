## crlffix

Implemented on `cx-crlffix` from `83e0b809d0fdeb4bf43647bd0cada7a4f14f241d`.
No push. Correctness runs use CPUs 0–15 and ports 20300–20399; builds use
`taskset -c 0-15 make -j16`. No performance measurement or full iteration was run.

The fix centralizes length-aware error and status sanitation in `src/net/resp.h`.
FUNCTION, Lua, stream NOGROUP and malformed bulk-prefix errors now use those
builders. Bulk and verbatim encoding remains unchanged. The source audit lists
all **966** reply-builder definitions, callers and direct writers, with a
per-site disposition: [audit.md](docs/crlffix/audit.md),
[reply-sites.tsv](docs/crlffix/reply-sites.tsv) and
[source hashes](docs/crlffix/reply-source-hashes.json).

Redis 7.4.10's local `networking.c` (`addReplyError*`, `addReplyStatus*`,
`afterErrorReply`) was read first; `functions.c` and `script_lua.c` resolve an
important distinction: formatted errors trim terminal CR/LF and map remaining
CR/LF to spaces, but safe-SDS errors and safe statuses map without trimming.
FUNCTION LIST and runtime Lua errors use safe-SDS; returned Lua error tables use
formatted errors. Tests require these distinct trailing-newline behaviors.
Ordinary reply bytes retain existing formatting. Pre-existing unrelated wording,
length limits, unsupported surfaces and embedded-NUL conversion differences are
explicitly identified in the audit rather than claimed fixed.

PRE reproduction is recorded in [raw bytes and Tcl results](docs/crlffix/pre-repro/results.json):

| Server | Raw response to FUNCTION LIST injection followed by PING | Original upstream Tcl assertion |
|---|---|---|
| Redis 7.4.10 | `-ERR Unknown argument X  +INJECTED\r\n+PONG\r\n` | 1 pass, 0 fail |
| PRE, each of 1s/2s × epoll/uring | `-ERR Unknown argument X\r\n+INJECTED\r\n+PONG\r\n` | 0 pass, 1 fail |

The new `crlffix` gate job performs **4,192 candidate checks** across all 16
1s/2s × epoll/uring × atomic 0/1 × databases 1/16 boots (DB 15 on the latter).
Each recoverable command requires Redis-equal raw reply bytes, the next PING,
and an ECHO witness that rejects a forged PONG. Fatal parser errors instead
require the Redis-equal error plus EOF, then PING on a fresh connection.
MONITOR's escaped payload must match; raw lines are retained while volatile
timestamps/peer addresses are excluded from equality. Clean twins and bulk
controls check unchanged bytes. Compiler/runtime errors, function/library names,
command/subcommand/options, config, ACL, CLIENT/OBJECT, stream keys/groups and
the module-filter surface are covered.

This is one aggregate row collected at `tests/gate.sh:5575`, before the quick
exit at line 5775: **DQ=+1, DF=+1**. `EXPECT_QUICK=798` and `EXPECT_FULL=815`
are untouched; the maintainer's corresponding totals become **799 / 816**.
FUNCTION-LIST-CRLF is removed from the shared Tcl named skips and added to the
required passing inventory for both modes.

Correctness evidence is retained in [proof/index.json](docs/crlffix/proof/index.json),
including the exact plans, ledgers, logs and oracle wire records. All gate runs
are explicit `GATE_ONLY_JOBS` selections; none is a full-gate receipt.

| Check | Result |
|---|---|
| New row, immutable POST | 4,192 checks pass on all 16 boots |
| New row, PRE and PAD-A | Both fail 224 checks; every recorded wire result agrees between the two arms |
| New row, planted FUNCTION helper bypass | Fails 160 checks |
| Full configured Tcl job, POST | Both modes pass: 35 files and 1,644 passing tests per mode, including the newly required CRLF assertion |
| Full configured Tcl job, planted bypass | Both mode jobs fail their required FUNCTION-LIST-CRLF assertion |
| epoll feature/client/RESP/ACL/script/auth/config/HELLO selection | 172/172 rows pass |
| Frozen uring selection plus netcmd units | RUNNING; final receipt will be appended before delivery |
| Standard differential seeds, both engines, all legs | RUNNING; final receipt will be appended before delivery |
| `python3 tests/gates_test.py` | 73/73 pass |
| `make all`, every `job_production_units` target and freshness | Build exits zero; all 52 recorded checks return zero |

The feature selection runs all four split/armed-fused × atomic 0/1 legs,
including the functions, scripting and stream-group batteries. The other jobs
are `clientfix respcompat acl_subcommands scriptfix auth serverfix_config
serverfix_hello`. The final Tcl job uses server CPUs 8–15, load CPUs 0–7,
ports 20320–20322, ratio 6:2 and 16 shards. Its immutable binary digest is in
[tcl-final.json](docs/crlffix/tcl-final.json). Earlier runs reported MONITOR,
pubsub or blocking-list timing failures; all original failed ledgers remain
archived, and no assertion was relaxed or demoted. The initial mutable-build
diagnostic also failed the binary-change check and is superseded by frozen-arm
runs. The earlier concurrently building gate-self-test run had four scheduler
fixture deadline failures; the final 73/73 run uses `GATE_TEST_PORT=20398`.
The initial self-test invocation used its default ephemeral fixture listener.

The cost result is **zero added instructions in every one of 48 PRE/POST
command-scope comparisons**: GET/SET/INCR/MGET/MSET, batches 1/32, 1s/2s and
normal/db0 namespaces, including both MSET atomic settings. Every per-function
count and external-call count also agrees. An independent GDB single-step
counter agrees with the ptrace counter in all 96 arm traces.
[counts.md](docs/crlffix/counts.md),
[comparisons](docs/crlffix/fast-counts/comparison.json),
[counter cross-check](docs/crlffix/counter-crosscheck.json).
The scope covers linked production owner/scatter routines including NOPs and
inlined code; it excludes setup, fixture glue and external-library bodies.
This uses no server, worker threads, rate or timing measurement. An initial
helper refactor added 19 MGET instructions and was rejected; the final C-string
wrapper retains its original shape. Superseded counts remain recorded.

Arm digests are also in [artifacts.json](docs/crlffix/artifacts.json):

| Arm | File | SHA-256 | .text bytes |
|---|---|---|---:|
| PRE | `build/crlffix/arms/PRE` | `739ba423d86c3872a8a1906abf33d064262d9f7a2551137555dd1930c6e83eca` | 8435415 |
| POST | `build/crlffix/arms/POST` | `6e9080a219a3f62dcc11838c7420bd4fe222e3c9e7f7cf3557e196affaa0ca25` | 8428631 |
| PAD-A | `build/crlffix/arms/PAD-A` | `f03e247e6d97a547b659df3338a65a8654a97557cec6cb0f9fa81de81c455b06` | 8428631 |
| BROKEN | `build/crlffix/arms/BROKEN` | `2c7ae7892d9b6629f81d1f2019ad6830115f9f98c99dc627dc2d06d097e397b2` | 8428631 |

PAD-A is **kind A: behaviour twin**, PRE cold-error behavior transplanted into
POST's existing text slots. All section/symbol addresses and sizes match POST,
and every non-patched byte is identical. The offline patcher resolves PRE call
and CRLF-literal relocations. [Patch receipt](docs/crlffix/arms/PAD-A.json),
[16-leg PRE/PAD-A equality](docs/crlffix/arms/PAD-A-behaviour.json).
BROKEN restores only the FUNCTION error helper in both namespaces. These are
throwaway binary controls; production source has no test switch.

Maintainer merit request: **NOT RUN — performance belongs to the maintainer**.
Use the gate's own ABBA instrument and [18 cells](docs/crlffix/merit.cells.txt):
14 generic cells `h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0 v1g_l0 d128g_l0
d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`, plus 2s GET/SET p1/p32
`h53 h54 h21 h22`. Compare PRE/POST and PRE/PAD-A, with a contemporaneous
PRE/PRE null. The deciding result is a null in every cell at matched offered
load under the normal gate controls. Record rate, cycles/op, IPC and
instructions/op. No throughput improvement is claimed.

Full `tests/gate.sh iteration`: **NOT RUN — maintainer-owned**. Build/freshness
records include both mdbqsbr live arms and the blockfix cost target:
[units-freshness.json](docs/crlffix/units-freshness.json). Raw step logs and
superseded fixture/arm objects were deleted after their hashes and counts were
recorded. Build usage is about 16 GiB, with required unit prerequisites retained
for `make -q`.
