## bugs5

Base `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`, branch `cx-bugs5`. No push,
performance benchmark, measurement load generator, or full iteration gate.
Correctness geometry: server CPUs 96–103, Redis 7.4.10 on 104, clients 105–111;
builds restricted to 96–111 with `-j16`; ports 24800–24899. The gate planner
needs 16 declared physical CPUs: its server allocation includes unused CPU 104,
but each actual server slot remains exactly 96–103, 16 shards, ratio 6:2.

Implemented: CD4.2, SV4.3, RL4.1. IO4.3 is reproduced and requires the owner’s
protocol decision described below. DIFF-TRK-1 investigation is in progress.
This is a correctness change; no throughput claim.

### Re-verification and fixes

The full finding rows were checked in `round4-read/REGISTER.md` and their
`cmd-data.md`, `cmd-server.md`, `read-local.md`, and `io-loop.md` reports.
The absent external `cx-wave4` path is replaced by its retained tracked receipt
at `docs/wave4/differ/epoll-armed-fused/climon-a0-s19-failure.txt` and the tracking
section of `MEASURE-REQUEST-wave4.md` in this checkout.

* CD4.2: `src/cmd/t_hash.cc::cmd_hscan` still used a compact array offset on PRE.
  Deletion skips `f3`; promotion skips multiple surviving fields. Return the
  complete compact hash with cursor zero, as Redis does, preserving MATCH and
  NOVALUES. SSCAN and ZSCAN already finish their compact forms in one call;
  both compact set forms and zsets are included in the new oracle witness.
* SV4.3: PRE `cmd_slowlog` looked up the current directory entry during GET.
  Entries now retain an immutable address/name version. Executor timing takes
  that reference before execution publishes Done, so subsequent rename or
  disconnect cannot race historical attribution. The cold stack owns the
  reference; every pre-existing loop/layout assertion remains unchanged.
* RL4.1: assignment of `(thread_id + 1) * odd_constant` replaces XOR with the
  same initial constant. Multiplication is a bijection modulo 2^64: all supported
  thread IDs receive distinct, nonzero states. The increment law is unchanged.
  The task summary says increments never fire; the audit and reproduction show
  the opposite: zero modulo every denominator makes **every increment fire**.
  PRE thread zero reaches 31 on all 64 keys after 300 lane reads each.
  The Redis logarithmic Markov model predicts mean 12.98748 and standard error
  0.20117 over 64 keys; the oracle run measured 12.96875. The witness requires
  every GET/MGET key read to be lane-served and visits every live IO lane.

`bugs5` is a new gate job with three rows, each containing all eight declared
mode/engine/atomic legs. Its collection is before the quick-tier exit:
**DQ=+3, DF=+3**, so the maintainer’s constants would become **688/705** from
685/702. Neither EXPECT constant is edited. Final PRE gate run
`build/gate-run.EEcItu` fails all three rows for the intended data assertions in
all eight legs. Initial harness mistakes and their failed logs are retained;
they are not counted as reproductions. All three unchanged witnesses pass on
the pinned Redis oracle (`docs/bugs5/controls/oracle-*.log`).

### IO4.3 — reproduced; protocol design for the owner

`docs/bugs5/controls/results.json` records both engines and atomic settings at
2s/6:2/16 shards. A BLPOP holds the existing IoDrain window; the report form of
FLIP must report moving before 24 new connections send PING. Closing the blocker
permits completion; retaining it forces the existing five-second rollback.
1s attempts record the explicit unsupported-FLIP error, both engines/atomics.

Uring drops all 24 arriving connections in both completion and rollback cases.
Epoll completion resets connections queued on a converting IO’s listener;
rollback on the original listeners serves them. The established PING resumes
when quiescence ends. The old audit’s retry-on-dead-client mechanism has already
been changed by flipfix: `flip_candidate_clients_ready` skips closing pinned
clients and `flip_drop_closing_planned` removes them. Do not reintroduce that fix.

Current anchors: `accepts_paused`, `on_accept`, `admit_fd`,
`quiesce_accepts_for_conversion`, `deactivate`, and
`cancel_prepared_activation` in `src/core/io_loop.h`. Merely retaining positive
CQEs fixes only one loss: closing a SO_REUSEPORT listener also destroys its
kernel accept/SYN queues. Draining to EAGAIN then closing leaves an arrival race.
New EX→IO listeners created in reversible IoPrepare have the symmetric rollback
problem. Admitting directly into Client lists breaks the frozen plan/quota checks.

A complete design needs a listener ownership transfer in the FLIP protocol:

1. Retain accepted descriptors outside the planned Client set while dispatch is
   quiesced, including successful old-generation CQEs arriving during cancel.
2. Reserve surviving IO ownership of every listener that would otherwise close,
   including its kernel queues and TLS identity. Register that listener on the
   destination ring/epoll before acknowledging installation. Keep it open until
   process shutdown or a later acknowledged transfer; never close a listener as
   an ownership handoff. Multiple listeners per IO need independent accept tags,
   cancellation accounting, and bounded allocation prepared before commit.
3. Extend existing prepare/install/rollback acknowledgements to cover those
   resources and pending descriptors. On completion or rollback, admit deferred
   descriptors exactly once on the resulting IO owners, after quota validation
   and before ordinary dispatch resumes. Prepared listeners also need a rollback
   destination. Preserve the unique UNIX listener’s pinned-owner rule.

This can reuse existing phases and physical threads, but **changes what the
protocol transfers and acknowledges**. Under the instruction to keep the FLIP
protocol unchanged and stop at design when a change is required, no partial
accept-side patch is shipped. IO4.3 remains open; owner review of this resource
transfer extension is required. No IO4.3 passing gate row is claimed.

### Validation and merit request

Validation, identity inventories, final hashes, PAD-A scope, label-fixture check,
and the generic 14-cell merit request will be appended after final runs.
