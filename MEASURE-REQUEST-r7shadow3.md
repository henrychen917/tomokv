# r7shadow3 — split isolation and AUTO occupancy floor

Worktree `/home/user/Projects/cx-r7shadow`, branch `cx-r7shadow`, PRE `665a0cb13`.
The owner confirmed the codex phase. This lane starts no server, benchmark, load
generator or gate. Builds and serverless witnesses run on CPUs 112-127.

## Split audit and the unresolved per-boot result

The launch binary has been preserved as `build/r7shadow3-pre/tomokv`. Its SHA256
is `5f72057199d456a09b4145d022fa3a9e3047cba021ace8c7d92c6f0e28a5b81a`, matching the
owner's frozen `bench-bins/tomokv-r7shadow2-665a0cb13` byte for byte.

Source tracing did **not** find the hypothesized request-dependent split leak:

- `main` resolves reorder after both configuration sources and validation, before
  placement, server initialization or worker creation. Mode is already final.
- `Server::init` resolves its private configuration before schedule allocation.
  `overlap=1` allocates the same 64-byte-per-thread shared schedule array for all
  three values. The policy fields use its existing padding. With overlap off,
  split allocates no schedule array.
- Parser stamping and late-read demotion are in the isolated armed call graph.
  `PolicyScope` and the AUTO observer live only in its IO loop. Ordinary
  `ThreadCtx::sample_depth` does not call the observer.
- The old split selectors read the resolved configuration, including on FLIP
  re-entry. No second raw reorder value, environment override or live setter was
  found. Both split executor template types were checked; `<true>` also means
  read-local capability and does not by itself mean fused placement.

POST removes the remaining **split role selectors** entirely: both ordinary
owner-entry sites in `main`, the read-local owner in `rl2s.cc`, ordinary split IO,
and split read-local IO call the baseline directly. This is structural enforcement
of the scope, not an assertion that one of those resolved selectors caused the
old tails. `Server::init` now also honors the PAD capability for direct callers.
Fused behavior remains selected at fused boot.

The old serverless fixture pre-resolved reorder before initialization, weakening
its allocation witness. The new fixture passes the raw value. Its instrumented
R7 object counts operational envelope entries, parser stamping, policy scope,
sampling, queue construction and reorder-info traversal. The allocation witness
counts reorder-requested sidecar allocation and independently compares every C++
allocation's size/alignment sequence through boot and the synthetic workload.
Instrumentation has no release counters, storage, branches or calls. Cold
configuration resolution and capability reporting are intentionally not counted
as operational R7 entries.

At the gate geometry (8 threads, 6 IO + 2 EX, 16 shards), all 12 combinations of
raw `0/1/-1`, overlap `0/1`, and read-local `0/1` passed: operational paths **0**,
reorder allocations **0**, identical allocation traces, FIFO handler order and
RESP retirement. The real INFO handler reports `reorder:0`, `reorder_retired:1`,
no reorder counters/policy, and no schedule array when overlap is off. The
overlap-owned array is inspected for zero reorder state when overlap is on.
Fused positive controls count actual R7 work. All 16 negative controls are
detected, including a sidecar allocated and freed before the final inspection.
Receipt: `build/r7shadow3-split-witness.json`.

The saved six 985K split boots in `tailgen-rs2s2{on,off}/r*-ro*-985000/server.log`
all report the same 32-thread placement: 16 IO + 16 EX, 256 shards, split mode,
overlap on. They do not record effective reorder, INFO, hash seeds, live load
balance state or per-window profiles. They also include population work in their
shutdown counters. Their executor operation totals are similarly balanced in
both the slow and fast boots; IO distributions vary in both arms and do not
uniquely distinguish the slow boots.

There are real once-per-boot/connection choices independent of reorder:
`main` seeds hashing with `getrandom`, address/allocator placement varies between
processes, and SO_REUSEPORT hashes connections onto separately created IO
listeners. The tailgen seed controls arrivals, **not** those server choices.
They can feed different load-balancer trajectories. These are candidate
explanations, **not a demonstrated cause**. Three whole ON boots followed by
three whole OFF boots cannot distinguish a request effect from those choices or
run-order drift. The 11.207/4.367/9.863 versus 4.399/4.103/4.199 ms observation
is retained as a blocking failed null, not dismissed as noise. The precise cause
of the bimodality remains unresolved; this lane has no supporting profile and
will not manufacture one. POST needs the matched split null measurement below.

## Measurements and final artifacts

Pending completion of the AUTO category and final artifact verification.
