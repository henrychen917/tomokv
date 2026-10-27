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
