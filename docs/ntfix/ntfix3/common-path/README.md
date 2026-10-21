# N4 common-path code generation

The production `read_space` body from both `src/main.o` and `src/core/reorder.o`
reads `rlen` at +4, `rpos` at +8, the buffer pointer at +16, and capacity at +24.
It has no load from the pending-frontier flag (+0x4c) or `RespFrontier::next`
(+0x74). Both cap-clamping comparisons branch to `.text.unlikely`, which
calls the 299-byte `read_space_refined` body. That cold body contains the
frontier loads and the unchanged ntfix2 allocation/offer logic.

`query_guard.cc` exposes the production predicate without changing it. In its
compile-only assembly, the conservative `rlen - rpos` comparison is at +0x1c;
when it passes, execution returns at +0x21. Only the failing-bound branch to
+0x30 loads the pending flag and (if armed) the saved frontier. The queued-MULTI
comparison remains first. No new common-path predicate is introduced.

Compile command (CPUs 80–95):

```
taskset -c 80-95 g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -I. -c docs/ntfix/ntfix3/common-path/query_guard.cc -o build/ntfix3/query_guard.o
```

This proves conditional frontier access, not full-body identity or performance.
The emitted receive helper is 371 bytes plus a 38-byte cold clone, versus PRE's
337-byte reorder copy. It is also newly outlined in main; that remaining
inlining change is reported in the full inventory and admitted for merit review.
The two allocations and final clamps share a compile-time helper so the cold
rule cannot drift from the common allocation code; it adds no state or runtime
mode. The two new unit cases exercise conservative-cap equality with and
without growth, including the short-receive exception.
