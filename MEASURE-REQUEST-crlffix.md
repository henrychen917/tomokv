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
