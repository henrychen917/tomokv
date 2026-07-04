# Final autonomous-run results (2026-07-04)

## Merged to stable/main (2-Stage) + 3-stage (3-Stage)
- **Command interning** (argv[0] shared-robj): io-alloc reduction. A/B io4ex4 jemalloc 3 reps:
  GET32 **+3.0%**, MIX32 **+5.8%**, SET32 +1.0%. ASAN-clean (2s + 3s incl. operand-pool coexist).
- (earlier this session, on stable) epoll_pwait2 (+6.3x trickle), prefetch idiv caches, config gates.

## Parked (dev branch, flat on 1-CCD)
- **2s-decref-bounce-dev**: released-operand-bit decref-bounce fix. ASAN-validated, FLAT (+0.8% MIX,
  base 6.77M vs mask 6.82M). Cross-core cheap on shared L3; re-eval on multi-CCD Threadripper.

## Sweep (master.tsv) — Performance+Topology README table (moderate splits)
Best-split Tomo vs Redis: GET 1.84x, MIX 2.42x, BITCOUNT 1.76x, HGETALL 1.79x, ZRANGE 1.88x.
DRAM within ~5% (io6ex2 extreme flips flat-512B). Splits: io5ex3 wins dispatch/BITCOUNT, io4ex4
wins writes/big-reply, io3ex5 exec-lean.

## Build-trap lessons (3 caught by sanity-gate)
libc (make redis-server skips deps/jemalloc), identical binaries (mask committed -> stash no-op),
ASAN-instrumented (.make-settings persists CFLAGS=-fsanitize). VERIFY: --version jemalloc, .text
~4.36MB, distinct md5, sane range. Delete .make-settings for clean rebuild.
