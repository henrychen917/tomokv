# ARM C: lower per-operation io_uring work

## What changed

- `src/uring2.c:761` stages `io_uring_prep_recv_multishot` with buffer
  selection when the new receive mode is active. One callback slot and one
  SQE remain armed across all CQEs carrying `IORING_CQE_F_MORE`.
- `src/uring2.c:847` resolves the CQE BID, copies the bytes into the client's
  query SDS, immediately returns the buffer to the provided-buffer ring, and
  re-arms every terminal request. `-ENOBUFS` is counted; a terminal ENOBUFS
  re-arms, while an ENOBUFS CQE with `F_MORE` leaves the still-live arm alone
  after replenishment.
- `src/uring2.c:1410` allocates and registers one provided-buffer pool per IO
  owner. The registered ring capacity is rounded up to liburing's required
  power of two, but exactly the configured N buffers are allocated and added.
  Kernel versions before 6.0, allocation failure, or
  `io_uring_setup_buf_ring`/registration failure log a warning and retain the
  one-shot path for that owner.
- `src/uring2.c:534` and `src/uring2.c:551` add the guarded direct-send path.
  `src/uring2.c:1021` verifies the buffer address and logical cursor again at
  the CQE before retiring bytes. Partial sends and EAGAIN/EINTR retain the
  same prefix and use the existing retry queue.
- Config declarations are at `src/server.h:3316` and `src/config.c:3256`.
  Range/default coverage is at `tools/preflight/knob_matrix.sh:347`; that
  server-starting script was intentionally not run.

## Knobs

- `tomokv-uring-multishot` is immutable, range 0..8192, default 0. `0` keeps
  the original one-shot receive path and creates no provided-buffer ring.
  `N > 0` requests multishot receive with N `PROTO_IOBUF_LEN` buffers per IO
  thread; unsupported owners fall back to one-shot with a log line.
- `tomokv-uring-sendcopy-min` is modifiable, range 0..INT_MAX, default 0. `0`
  always uses the original scratch copy. `N > 0` sends a staged plain-buffer
  prefix directly only when its length is at most N bytes and every guard
  below passes. A change affects later promotions only; an in-flight prefix
  records whether it is direct or copied.

## Ownership and guards

`appendClientInputFromUring` (`src/networking.c:4732`) uses `sdscatlen`, so it
copies all received bytes into client-owned SDS storage and retains no pointer
to the kernel-selected buffer. Parsing runs later in `tomoUring2ProcessReady`,
after CQ advancement. It is therefore safe to return the BID immediately
after `appendClientInputFromUring`, including when the client is paused or
migrating; the SDS, not the provided buffer, travels with the client.

POLL_FIRST is preserved on each initial/replacement arm using the existing
SOCK_NONEMPTY hint. Shots after the first are polled internally by the live
multishot request and need no userspace re-arm.

Direct send requires a RUN-mode, ordinary TCP client; a plain `c->buf`; an
empty reply list; no `cs_barrier`; and none of replica/master/monitor,
RDB-channel, close, protected, migrating, or pipeline-stalled flags. TLS and
all other connection types therefore use the scratch path. Existing
`tomoUring2SendCanPromote` exclusions also reject internal and otherwise
ineligible clients.

The direct-buffer stability proof is: real-client reply construction only
appends after `bufpos`; it never reallocates `c->buf`; the only real-client
cron reallocation is already blocked by
`tomoUringBackendClientSendPending` (`src/server.c:2517`); legacy writes are
blocked by the same predicate (`src/networking.c:3470`); CQE accounting alone
advances/resets the in-flight prefix; and close/free waits for SEND/cancel
retirement. Address/cursor checks turn any future violation into a fatal
invariant failure instead of silently continuing with changed storage.

## INFO counters and risk

Watch `tomokv_uring_multishot_arms`, `tomokv_uring_multishot_cqes`,
`tomokv_uring_multishot_rearms`, `tomokv_uring_multishot_enobufs`, and
`tomokv_uring_recv_oneshot`. For send selection, watch
`tomokv_uring_send_nocopy` and `tomokv_uring_send_copy`. They are emitted in
`src/server.c:20985`.

The main operational risk is undersizing the shared receive pool: exhaustion
is recovered without losing the arm, but raises latency and the ENOBUFS/rearm
counters. Memory is N times `PROTO_IOBUF_LEN` per IO thread, plus rounded ring
metadata. The send path deliberately has narrow guards because any new path
that reallocates or resets a real client's output buffer must also honor
`tomoUringBackendClientSendPending`.

Per the task's safety rules, validation was compile-only. The required
USE_URING+jemalloc build links `src/redis-server`; no server, benchmark, CLI,
test, preflight, or knob-matrix process was started. Existing unrelated
`server.c` warnings remain unchanged.
