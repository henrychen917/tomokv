## crlffix

Baseline: `83e0b809d0fdeb4bf43647bd0cada7a4f14f241d` on `cx-crlffix`.
No performance measurements; correctness uses CPUs 0–15 and ports 20300–20399.

PRE reproduction ([raw bytes and Tcl results](docs/crlffix/pre-repro/results.json)):
Redis 7.4.10 sends `-ERR Unknown argument X  +INJECTED\r\n+PONG\r\n`.
PRE sends `-ERR Unknown argument X\r\n+INJECTED\r\n+PONG\r\n`
in all four 1s/2s × epoll/uring legs. The unchanged upstream Tcl assertion
passes on Redis and fails on each PRE leg (0 passed, 1 failed).

Source of truth: `/home/user/Projects/redis/src/networking.c` and `functions.c`.
Formatted errors trim terminal CR/LF and map remaining CR/LF to spaces.
Redis's safe-SDS errors (including FUNCTION LIST) and safe statuses map without
trimming. These distinct semantics must survive the fix and oracle tests.

Implementation, audit inventory, gate proof, counts and arm digests follow in
subsequent small commits. EXPECT_QUICK/EXPECT_FULL remain untouched.

The implementation centralizes length-aware errors and statuses in `src/net/resp.h`.
FUNCTION, Lua, stream NOGROUP and the malformed bulk-prefix error now use them.
The formatted-error and safe-SDS distinction is preserved, including Lua's returned
error table versus its status table. Bulk/verbatim encoding is unchanged.

`job_crlffix` is one aggregate row, collected immediately after `respcompat`,
BEFORE the quick-tier exit: **DQ=+1, DF=+1**, nominal constants 798/815 →
799/816 (maintainer changes them). It exercises 1s/2s × epoll/uring × atomic
0/1 × databases 1/16, using DB 15 on the 16-database boots. Every command is
followed by PING and an ECHO witness. Fatal parser errors require exact error
bytes and EOF, matching Redis, then a fresh connection's PING. MONITOR compares
its escaped argument payloads, preserving raw lines but excluding volatile
timestamps/peer addresses from equality.

The new row is red on PRE (224 failures across all 16 legs) and green on the
second POST build. The one FUNCTION-LIST-CRLF assertion has been removed from
the shared Tcl skip list and added to the required passing inventory for BOTH
modes. Final immutable-arm proofs and a planted sanitizer bypass follow.

An initial helper refactor changed command-scope counts (MGET +19), so it was
superseded. The second build restores the original short error-wrapper shape;
completed GET/SET/INCR/MGET small traces match PRE exactly. No throughput claim.

Final cost proof: [counts.md](docs/crlffix/counts.md),
[48 comparisons](docs/crlffix/fast-counts/comparison.json),
[96 independent counter cross-checks](docs/crlffix/counter-crosscheck.json).
Every PRE/POST total and per-function count agrees; external-call counts agree.
This is a bounded serverless command scope, not an end-to-end performance result.

Full audit: [audit.md](docs/crlffix/audit.md), with every one of 966 reply
builder definitions/call sites/direct writers and its disposition in
[reply-sites.tsv](docs/crlffix/reply-sites.tsv).

PAD-A is **kind A, behaviour twin**: restored PRE cold error behavior inside
POST's existing text slots. All section/symbol addresses and sizes are identical
to POST; every other byte is identical. The byte patcher independently resolves
PRE call and CRLF-literal relocations. [Patch receipt](docs/crlffix/arms/PAD-A.json).
The 16-leg response inventory matches PRE with zero differences
([comparison](docs/crlffix/arms/PAD-A-behaviour.json)); its new row fails just as PRE
fails. The separate BROKEN arm restores only the FUNCTION error helper, in both
namespaces; both full Tcl-mode jobs fail their newly required injection assertion.
The production source contains no test control or runtime switch.

Maintainer measurement request (NOT RUN here): use the gate's own ABBA
instrument and [these 18 cells](docs/crlffix/merit.cells.txt): generic
`h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0 v1g_l0 d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`,
plus split GET/SET p1/p32 `h53 h54 h21 h22`. Compare PRE/POST and PRE/PAD-A,
with a contemporaneous PRE/PRE null. The deciding result is a null in every
cell at matched offered load under the normal gate controls. Report rate,
cycles/op, IPC and instructions/op; no throughput improvement is claimed.

Arm digests (also [artifacts.json](docs/crlffix/artifacts.json)):

| Arm | File | SHA-256 | .text bytes |
|---|---|---|---:|
| PRE | `build/crlffix/arms/PRE` | `739ba423d86c3872a8a1906abf33d064262d9f7a2551137555dd1930c6e83eca` | 8435415 |
| POST | `build/crlffix/arms/POST` | `6e9080a219a3f62dcc11838c7420bd4fe222e3c9e7f7cf3557e196affaa0ca25` | 8428631 |
| PAD-A | `build/crlffix/arms/PAD-A` | `f03e247e6d97a547b659df3338a65a8654a97557cec6cb0f9fa81de81c455b06` | 8428631 |
| BROKEN | `build/crlffix/arms/BROKEN` | `2c7ae7892d9b6629f81d1f2019ad6830115f9f98c99dc627dc2d06d097e397b2` | 8428631 |

`make -j16 all` and every production-unit target, both mdbqsbr live arms and the
blockfix cost target completed. All 52 build/freshness records are zero:
[units-freshness.json](docs/crlffix/units-freshness.json). `python3 tests/gates_test.py`
passes all 73 tests on the final run (the earlier concurrent-build run had four
scheduler-fixture deadline failures). Final self-test listener was pinned to
20398 with GATE_TEST_PORT; all correctness servers use the lane port block.
The initial self-test invocation used its default ephemeral fixture listener.

Raw single-step logs and superseded fixture/arm objects were removed after
recording hashes and counts. Current build footprint is about 16 GiB. Required
unit prerequisites remain for make -q. No full iteration, performance benchmark
or push was run. Remaining live differential/Tcl proof is being recorded below.
