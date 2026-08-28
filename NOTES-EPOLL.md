# NOTES-EPOLL — a second network event engine

Branch `t-epoll`. Adds `--net-io uring|epoll`: a selectable epoll backend beside io_uring, so the
same binary runs on kernels and in environments where io_uring is unavailable or unwanted.
**The default is unchanged (`uring`), and the uring build contains no epoll code.**

---

## 1. The knob

Modelled on `--persist-io normal|uring`, deliberately and exactly: it is the same *kind* of decision
(which kernel interface carries our IO), so it gets the same shape.

| | |
|---|---|
| flag | `--net-io uring\|epoll` |
| conf file | `net-io epoll` (one parser serves both — `src/core/config.h`) |
| type | named enum, case-insensitive, `NetIoEngine { Uring = 0, Epoll = 1 }` |
| default | `uring` |
| scope | boot-only; `CONFIG GET net-io` reports it, `CONFIG SET` refuses it |
| docs | `tomokv.conf` NETWORK section; `--help` |
| test | `tests/config_parser_test.cc` — accepts `EpOlL`, **rejects `kqueue` and the empty value**, and asserts the default is `Uring` |

Selecting `epoll` implies one other thing, announced on stderr at boot rather than done silently:

```
--net-io epoll: persist-io forced to normal (the uring persistence engine needs a ring)
```

`--persist-io uring` submits AOF/snapshot writes and fsyncs as SQEs on an io thread's ring, and under
this engine no ring exists. Forcing rather than erroring keeps `--net-io epoll` usable with any
existing config file.

The boot banner names the engine, so a log tells you which one ran:

```
tomokv-cpp: 6 threads (4 io + 2 ex), 16 shard(s), 2s (io sends), epoll, alloc=jemalloc
```

---

## 2. Design: how the engine is dispatched, and why it costs nothing when off

### The choice

**Boot-latched, resolved once into a template parameter at the loop's outermost frame.** `IoLoop::run`
already picked its instantiation from two boot facts — is there a unix listener, is there a TLS
listener — and the engine simply joins them as a third:

```cpp
void run() {
    const bool has_unix = ...;
    if (epoll_) {
        if (tls_context_) { has_unix ? run_loop<true,true,true>() : run_loop<false,true,true>(); }
        else              { has_unix ? run_loop<true,false,true>() : run_loop<false,false,true>(); }
        return;
    }
    ... the same four with kEp = false ...
}
```

Every engine-dependent site below that is `if constexpr (kEp)`. `WbEngine::serve/pump/submit_*` take
the same `bool kEp` and the io loop passes the value its own instantiation carries.

This is the tree's existing compile-or-boot-time-variant pattern, applied at the level the decision
actually lives at. `handler_notify` in `src/cmd/command.h` instantiates each handler twice
(`template <bool kArmed>`), stores both pointers in the 48-byte registry row, and picks one with a
single per-batch test — so an operation never branches on whether notifications are armed. The engine
is a property of the *whole loop* rather than of one handler, so the same idea is applied one level
out: two whole loop bodies, one test at thread start, nothing per event.

### Why not the alternatives

- **A runtime `bool` in the loop.** That is a branch on every recv, every send and every event — the
  exact per-event test the brief rules out, in the hottest code in the server.
- **Virtual `NetEngine` with `submit_recv`/`submit_send`.** The indirect call would land per send.
  At p32 a send covers ~32 ops so it amortises, but at p1 it is per operation, and p1 is the regime
  this tree has spent the most work on.
- **A separate `EpollIoLoop` class.** ~1000 lines of parse/route/retire/dispatch duplicated. The two
  engines would then be free to drift apart in exactly the places (ordering, retirement, backpressure)
  where they must not.

### The zero-cost argument

Three separate claims, each checkable:

**(a) No epoll code exists in the uring instantiation.** Mechanically verified rather than asserted —
disassemble the symbol and look for any epoll reference:

```
$ objdump -d build/tomokv  (symbol tomo::IoLoop::run_loop<false, false, false>)  | grep -icE 'epoll|eventfd'
0
$ objdump -d build/tomokv  (symbol tomo::IoLoop::run_loop<false, false, true>)   | grep -icE 'epoll_wait|EpollSet'
2
```

**(b) The engine is never tested per operation.** Every `kEp` in `io_loop.h` is inside an
`if constexpr` (12 of them) or a template argument list. `IoLoop` reads its runtime `epoll_` field
in exactly two places, and neither is per operation:

```
$ grep -n 'if (epoll_)' src/core/io_loop.h
220:        if (epoll_) {                                          <- run(), once per thread
2170:            if (epoll_) { c->set_recv_armed(false); ... }      <- close_client, cold
```

`WbEngine` has the same shape: `epoll_` is read only by `pump_tls_any` and `serve_suppressing`, both
of which are already `__attribute__((noinline, cold))` or reached only from the CLIENT REPLY object.

**(c) The shared code that both engines traverse gained only outer-level tests.** `Ring` grew one
`wake_fd_ >= 0` test in `submit()`, `submit_and_reap()`, `submit_and_wait()`, `sqe()`,
`for_each_cqe()`, `for_each_cqe_filtered()` and `msg_to()`. Those are called **once per loop pass**
(the submit/drain steps), **once per park** (the wait), or **once per park-wake** (`msg_to`) — never
per operation. All are `__builtin_expect(..., false)` and false in the uring build.

The one change to a per-connection line is in `flush_ready`:

```cpp
if (c->rob().quiesced() && (kEp || !conn.recv_armed())) conn.reset_rbuf_at_quiescence();
```

`kEp` is a constexpr `false` in the uring instantiation, so `(false || X)` folds to `X` and the
emitted sequence is the pre-lane one.

**Measured**, not only argued — see §6: the uring engine is A/B'd against the pre-lane base binary
(`329fa10ec`) at p1 and p32.

---

## 3. Design: what the epoll engine actually does

The rule the whole lane is built around: **an engine may change only how an io thread waits for and
completes network readiness.** Routing, shard ownership, the ROB, retirement order, the reply
structure and the entire EX side are engine-blind. `ex_loop.h`, `thread.h` and `signal.h`'s Channel
protocol are **unmodified**.

### Readiness: edge-triggered, armed once, never re-armed

Each connection is registered once, at adopt, with `EPOLLIN|EPOLLOUT|EPOLLRDHUP|EPOLLET`, and is never
`epoll_ctl`'d again; `::close()` is the only deregistration. Listeners are level-triggered (a backlog
we could not drain — maxclients, a failed allocation — must be re-reported, and a consumed edge would
be gone). The doorbell eventfd is level-triggered and drained explicitly.

Alternatives rejected: `EPOLLONESHOT` costs one `epoll_ctl` **per recv** on the hot path;
level-triggered `EPOLLIN` spins the loop at 100% whenever a connection holds bytes the ROB window
will not yet let us parse.

Edge triggering carries an obligation — drain to `EAGAIN`, and if you stop early, remember it
yourself. `Client::recv_armed_` carries exactly that memory under this engine, with no new field
(`sizeof(Client)` is still 1984, `sizeof(Op)` still 336; both static_asserts hold and the build
gates on them):

| `recv_armed_` | io_uring | epoll |
|---|---|---|
| `true` | the kernel holds a pointer into our read buffer | we reached EAGAIN; an edge is owed |
| `false` | no recv outstanding | there may be more; retry without waiting |

Both consumers keep working unchanged: `stuck` in `flush_ready` keeps a connection in the active set
while it is false (so a read that stopped for want of buffer space is retried), and
`safe_to_release()` refuses to free a connection while it is true.

### Registration lives in `adopt_client`, not in the accept

An AF_UNIX connection is accepted by one io thread and **owned** by another (the round-robin handoff).
Registering at accept would put the fd in the accepting thread's epoll set and deliver every one of
its events to a thread that must not touch that connection.

### Sends are synchronous, and deliberately do **not** reuse `on_send_complete`

That handler ends in "resubmit → `pump`", which under io_uring means "queue another SQE and return".
Called synchronously it means "syscall again, right now, from inside the accounting for the previous
syscall" — and on `EAGAIN`, the normal steady state of a backed-up socket, it recurses until the stack
runs out. `pump_epoll` is therefore an explicit loop over the same three sources in the same order
(legacy remainder → segment queue → promoted fill buffer) with three exits: nothing left, `EAGAIN`
(stop staged; the EPOLLOUT edge resumes), or a fatal errno.

`EAGAIN`/`EINTR` are flow control, not errors. The `ECONNRESET`/`EPIPE`/`ECONNABORTED`/`closing()`
family counts as `peer_aborts`, the same carve-out the CQE path makes, so `err=0` does not become a
timing lottery under connection churn.

A fatal errno has no CQE to travel back on, so it latches in `WbEngine::send_failed_` and the io loop
consumes it right after each serve site. `IoLoop::epoll_close_now` exists because that latch is a
one-slot channel: `close_client` flushes a TLS alert through the same engine, and a failure latched
*there* would otherwise be picked up by the next connection's `take_send_failure()` and close a
healthy client.

### Cross-thread wakes, without an io_uring anywhere

Every cross-thread wake in the tree is spelled `my_ring.msg_to(peer_ring, tag)` — `Channel::wake`,
`ThreadCtx::wake_if_parked`, and the snapshot epoch barrier. Those call sites belong to the EX side
and the channel mesh, which this lane may not touch. So the engine-dependent part is hidden **behind
the same `Ring` methods**: in epoll mode a `Ring` creates no io_uring at all, just an eventfd plus a
small mutex-guarded mailbox.

- `msg_to(target, tag)` → push the tag into the target's mailbox, then write its eventfd (payload
  before bell, the same order the channel mesh uses).
- `for_each_cqe(fn)` → hand the mailbox back shaped as `io_uring_cqe`s, so **both** loops' `on_cqe`
  switches see the identical tag stream and neither knows which engine it is on.
- `submit_and_wait(want, ms)` → `poll()` the eventfd with the same 50 ms ceiling (the ex loop's park).
- `submit()`, `submit_and_reap()`, `for_each_cqe_filtered()` → no-ops; `sqe()` → `nullptr`.

**The tag has to survive, not just the wake.** The snapshot epoch barrier posts
`UrKind::SnapshotStart` carrying a `SnapshotManager*`, and the executor that receives it calls
`begin_snapshot()` on that pointer. A doorbell that only said "wake up" would silently break BGSAVE
under epoll — the executors would never enter the barrier. Hence a mailbox of tags rather than a bare
counter.

Consequence, and the point of the whole design: with `--net-io epoll` the process makes **no io_uring
syscall at all** — not `io_uring_setup`, not `io_uring_enter` — including on the executor threads.
Proven by strace in §5.

### Zero-copy and TLS

- **Zero-copy borrowed-value sends work unchanged.** The segment queue still hands the kernel a
  borrow by pointer through an iovec; `::sendmsg` replaces the submitted SQE and the borrow is
  released for exactly the bytes the kernel reports accepted. If anything it is *safer* here: there
  is no window in which the kernel holds a borrow asynchronously.
- **TLS works**, in all three transports: memory-BIO userspace, socket-BIO userspace, and kTLS.
  `arm_tls_socket_poll` has nothing to submit (both directions are already armed), so it records the
  want on the `TlsConn` and the edge answers it. `epoll_pass` retires both recorded wants on any edge
  and lets `drive_tls` re-record what it still needs — the same converge-by-retry the poll CQE gives
  the uring engine.

**Nothing is refused under epoll.** See §7 for the one behaviour that changes (persist-io) and the
two things that are genuinely out of scope.

---

## 4. Two defects found while bringing it up

Both were found by running, not by reading, and both are covered by existing tests.

### (a) An iterator held across `close_client` (ASAN heap-buffer-overflow)

`flush_ready`'s phase-1 walk over the active set held a `std::vector` iterator. `close_client`'s retry
paths call `mark_active`, which `push_back`s and can reallocate. Under io_uring this was latent — the
only in-walk closer was `drive_tls`, and only for TLS. Under epoll the synchronous read/send paths
close routinely, and it fired on the **first connection that ever closed**:

```
ERROR: AddressSanitizer: heap-buffer-overflow
  #0 tomo::IoLoop::PtrSet::erase(...)
  #1 unsigned int tomo::IoLoop::flush_ready<false, true>()
  #2 void tomo::IoLoop::run_loop<false, false, true>()
  ... freed/allocated by: tomo::IoLoop::PtrSet::insert -> _M_realloc_insert
```

Fixed structurally, for both engines: the walk is index-based (an index survives reallocation), it
re-checks identity before deciding (`if (idx >= active_.size() || active_.at(idx) != c) continue;`),
and the epoll read/send paths **defer** their closes out of the walk entirely into `epoll_closes_`,
drained between phase 1 and phase 2 where nothing is iterating.

### (b) `CLIENT KILL` on self delivered its reply and then never closed

Under io_uring, "closing ⇒ not armed" is automatic: `arm_recv` refuses to re-arm a closing connection,
so `recv_armed_` falls to false when the outstanding recv completes and `safe_to_release()` opens.
Under epoll nothing completes — the flag means "an edge is owed", and for a socket being torn down
that is simply false. Nothing cleared it, so `safe_to_release()` refused forever.

`CLIENT KILL … SKIPME NO` on self is the path that exposed it, because it reaches its victim through
`mark_closing()` rather than `close_client()` (the reply has to go out first), so no other code would
ever clear the flag. Minimal reproduction, A/B:

```
--- URING ---   kill reply: b':1\r\n'   eof after 0.000s
--- EPOLL ---   kill reply: b':1\r\n'   NO EOF after 5s          <-- the defect
--- EPOLL (fixed) ---  kill reply: b':1\r\n'   eof after 0.000s
```

`tests/climon.py`'s "KILL self close-after-reply" is the regression cover, and it failed before the
fix and passes after.

---

## 5. What passes under epoll

Everything below was **run against an epoll-booted server**, on this lane's own cores (112-127) and
ports (7580-7589), `--shards 16 --ratio 4:2`, unless the row says otherwise. Where a battery has a
uring arm as well, that arm is the control, not decoration.

### 5.1 The full battery set, both atomic modes

| battery set | atomic 0 | atomic 1 |
|---|---|---|
| feature batteries (24: `s6 multi_exec blocking stream streamgroups pubsub lua_scripting scriptsurf limits resp3 bitfield dumprestore zsetops geo climon climon2 tracking hexpire servertail lcs concur edgeproto edgeenc edgetime`) | **24/24** | **24/24** |
| debug-surface batteries (10: `lbsignals slowlog atomfix scriptatomic execatomic execiso execfix session_monotonic xacct xscript`) | **10/10** | **10/10** |
| core stress (`torture ryow atomic_torn atomic_ryow concur`) | **5/5** | (covered under ASAN below) |
| eviction battery, all 8 sections, one fresh boot each (`off noev lru vlru vttl lfu growth config`) | **8/8** | — |

```
ENGINE=epoll ATOMIC=0 PASS=24 FAIL=0        ENGINE=epoll ATOMIC=1 PASS=24 FAIL=0
  s6                  ok (s6: 215 comparisons, 0 failures -> PASS)
  multi_exec          ok (MULTI/WATCH directed battery passed)
  blocking            ok (BLOCKING PASS)
  climon              ok (climon: ok)
  xscript             ok (XSCRIPT all directed battery passed)
  shutdown invariants ok
epoll: events=130267 recvs=109440
```

```
ENGINE=epoll ATOMIC=0 PASS=10 FAIL=0        ENGINE=epoll ATOMIC=1 PASS=10 FAIL=0
  execfix             ok (execfix: PASS)
  execiso             ok (in-EXEC isolation battery passed)
  scriptatomic        ok (SCRIPTATOMIC: 0 FAIL (0 vacuous))
epoll: events=1660451 recvs=1276197
```

```
ENGINE=epoll ATOMIC=0 PASS=5 FAIL=0
  torture      ok (TORTURE PASS)          ryow         ok (RYOW PASS)
  atomic_torn  ok (ATOMIC_TORN PASS)      atomic_ryow  ok (ATOMIC_RYOW PASS)
  concur       ok (CONCUR: 16 checks passed, 0 failed)
epoll: events=887701 recvs=715450

EVICT (epoll): pass=8 fail=0
  evict off  ok (SECTION off: 2 ok, 0 FAIL)      evict lru    ok (SECTION lru: 3 ok, 0 FAIL)
  evict noev ok (SECTION noev: 3 ok, 0 FAIL)     evict growth ok (SECTION growth: 7 ok, 0 FAIL)
```

Every boot in every row above also cleared the shutdown fence
`stuck: live_conns=0 rob_not_quiesced=0 unsent_bytes_pending=0`.

### 5.2 The differ suites against vanilla Redis 7.4

Same matrix `tests/differ_gate.sh` runs — 36 suites x seeds {7,19} x atomic {0,1} = 144 legs per
run — driven against a `--net-io epoll` target and the pinned `redis_version=7.4.2` oracle.

| run | engine | result |
|---|---|---|
| A | epoll | 143/144 — one leg diverged, see below |
| B | uring (lane binary, the **control**) | **144/144** |
| C | epoll (repeat) | **144/144** |

```
DIFFER GATE (net-io=uring): pass=144 fail=0
DIFFER GATE (net-io=epoll): pass=144 fail=0
```

**The one divergence, and what was done about it.** Run A's `multi` suite at atomic=1 seed=7 reported
5 diffs: one key held `hello` on the target where the oracle held `-2`, which then made a later
`INCRBY` inside a transaction answer `-ERR value is not an integer` instead of `:-2`. It has not been
reproduced since, and every control points away from the engine:

| probe | result |
|---|---|
| that exact leg, **pre-lane base binary** `329fa10ec`, io_uring, 3 repeats | 3/3 pass |
| that exact leg, lane binary, `--net-io uring`, 3 repeats | 3/3 pass |
| that exact leg, lane binary, `--net-io epoll`, 3 repeats | 3/3 pass |
| the whole 144-leg matrix again on epoll (run C) | 144/144 |
| the whole 144-leg matrix on uring (run B) | 144/144 |
| **dense probe**: one long-lived epoll server, atomic=1, `multi` suite x24 alternating seeds | **24/24 pass** |

```
MULTI SOAK (net-io=epoll, atomic=1, one long-lived server): rounds=24 pass=24 fail=0
```

I am recording this rather than dropping it. What the evidence supports is: a rare, non-deterministic
divergence in the atomic MULTI path that needs a long-lived server, seen once in 288 epoll legs and
never in 144 uring legs or 24 dedicated soak rounds. What it does **not** support is attributing it to
this lane — the engine changes recv/send/wait, and the observed symptom is a transaction's own
delete-then-read overlay, which is engine-blind code this lane does not touch. The honest statement is
that it is unattributed and unreproduced, and that the dense probe designed to catch it did not.

### 5.3 The engine's own directed battery: `tests/netio.py`

New, and written so that a green run on the wrong boot is impossible: it asserts engine identity
first, and every epoll mechanism claim has a control that must read zero.

| section | proves |
|---|---|
| A | `CONFIG GET net-io` matches the expected engine; the epoll readiness counters moved. **CONTROL: on a uring boot both counters must be EXACTLY 0.** |
| B | boot-only: `CONFIG SET net-io` refused in both directions, engine unchanged after |
| C | 512-deep pipeline in ONE write (ROB window is 64) — the edge-triggered "stopped early, no second edge is coming, retry yourself" path; replies checked in order |
| D | 8MB reply — forces EAGAIN mid-send and resume from the byte frontier; compared **byte-exact**, so a wrong resume offset fails rather than merely being slow |
| E | BLPOP woken by another connection, 20 rounds, **latency asserted** — the park ceiling is 50 ms, so a dead doorbell still completes, just late. Only the latency distinguishes a working eventfd mailbox from a timeout covering for a missing one. |
| F | 300-connection churn including abrupt RST (SO_LINGER 0) and half-close with a reply in flight |
| G | `CLIENT KILL` on self delivers its reply and then closes |

```
netio(uring): 37 checks, 0 failures, epoll_events=0 epoll_recvs=0   worst_wake=0.3ms -> PASS
netio(epoll): 37 checks, 0 failures, epoll_events=208 epoll_recvs=202 worst_wake=0.4ms -> PASS
```

The uring line is the control: the counters read exactly 0, so their non-zero epoll readings are
measuring the engine and not a constant. `worst_wake` is 0.4 ms against a 50 ms ceiling — the
doorbell fires, it is not the timeout.

### 5.4 The claim that no io_uring syscall happens at all

The point of the lane is running where io_uring is unavailable, so this is the load-bearing check.
`strace -f` over the whole process tree (executor threads included), 50 SETs plus a GET, both engines:

```
  uring  io_uring_setup=8  io_uring_enter=468  io_uring_register=0  epoll_create1=0  epoll_wait=0
  epoll  io_uring_setup=0  io_uring_enter=0    io_uring_register=0  epoll_create1=5  epoll_wait=341
```

The uring row is the control — a detector that cannot report a non-zero io_uring count proves nothing
about the row that reports zero.

### 5.5 TLS, kTLS and the zero-copy send path

The gate's three TLS arms (client-auth `yes`, the default `optional` boot with a live kTLS engagement
probe, and forced userspace fallback with the full battery), all on an epoll-booted server:

```
TLS (net-io=epoll): PASS=11 FAIL=0
  certs ok                      TLS client-auth yes ok          TLS yes shutdown invariants ok
  TLS client-auth optional ok   kTLS engaged live ok            TLS optional shutdown invariants ok
  TLS full userspace battery ok TLS full shutdown invariants ok TLS send path error-free ok
  TLS slots all freed (32/32) ok
  TLS zc borrow gates fired (21) ok
```

The last two rows are the non-vacuous part: every TLS slot allocated was freed, and the borrow-
suppression gate actually fired 21 times rather than the battery having quietly avoided the path. The
plain zero-copy path has its own battery, which also passes under epoll (`tests/zc.py`).

### 5.6 Persistence over epoll (`--persist-io normal`, forced)

```
PERSIST (net-io=epoll): PASS=13 FAIL=1*
  netio directed battery (epoll)                 ok
  zc borrow battery                              ok
  persist-io forced to normal under epoll (got normal) ok   [both atomic modes]
  AOF byte-exact + DEBUG LOADAOF (atomic 0)      ok
  AOF writer fired (records=369)                 ok
  AOF replay after restart (atomic 0)            ok
  AOF byte-exact + DEBUG LOADAOF (atomic 1)      ok
  AOF writer fired (records=369)                 ok
  AOF replay after restart (atomic 1)            ok
  snapshot concurrent cut (save)                 ok
  snapshot cut reload verify                     ok
```

\* the one FAIL was my runner invoking `tests/evict_battery.py` with `HOST PORT` when it takes
`PORT SECTION`. Re-driven correctly it is 8/8 (§5.1) — a harness defect, named rather than hidden.

### 5.7 Sanitisers

Full ASAN+UBSAN build (`make asan`), epoll boot, both atomic modes:

```
  ASAN torture     (atomic 0/1): TORTURE PASS / TORTURE PASS
  ASAN ryow        (atomic 0/1): RYOW PASS / RYOW PASS
  ASAN atomic_torn (atomic 0/1): ATOMIC_TORN PASS / ATOMIC_TORN PASS
  ASAN atomic_ryow (atomic 0/1): ATOMIC_RYOW PASS / ATOMIC_RYOW PASS
  ASAN netio       (atomic 0/1): 37 checks, 0 failures -> PASS  (epoll_recvs=698760 / 720163)
  ASAN reports (atomic 0): 0        ASAN reports (atomic 1): 0
  stuck: live_conns=0 rob_not_quiesced=0 unsent_bytes_pending=0
```

This is the run that caught defect (a) in §4 before the fix; it is clean after it.

### 5.8 Build and config locks

```
release build: 0 warnings, 0 errors   (sizeof(Op)==336 and sizeof(Client)==1984 static_assert here)
ASAN build:    0 warnings, 0 errors
tests/config_parser_test.cc: PASS      (includes the new --net-io grammar + negative controls)
```

---

## 6. Indicative numbers

*(filled in below)*

---

## 7. Scope notes and limitations

### Refused or changed under epoll

**Nothing in the command or protocol surface is refused.** One operational knob changes:

| | |
|---|---|
| `--persist-io uring` | **forced to `normal`** under `--net-io epoll`, announced on stderr at boot. The uring persistence engine submits AOF/snapshot writes and fsyncs as SQEs on an io thread's ring; under epoll no ring exists. Erroring instead of forcing would make `--net-io epoll` unusable with any config file that names the default. `CONFIG GET persist-io` reports `normal`, so the change is observable, not hidden. |

TLS (memory-BIO userspace, socket-BIO userspace, and kTLS), the zero-copy borrowed-value send path,
AF_UNIX sockets, `CLIENT KILL`/`CLIENT PAUSE`, blocking commands, pub/sub, MULTI/EXEC, Lua, snapshots
and AOF all work under epoll and are covered by the evidence in §5.

### Accounting that has no epoll analogue

`sqe_starved` counts a submission queue that could not accept an entry. There is no submission queue
under epoll, so it stays 0; the equivalent backpressure signal is `EAGAIN`, which the engine handles
by leaving the connection staged for the EPOLLOUT edge rather than by counting. `epoll_events` /
`epoll_recvs` (INFO STATS: `net_io_epoll_events`, `net_io_epoll_recvs`) are the engine's own
counters, and are exactly 0 on a uring boot — which is what makes them usable as proof rather than
decoration.

### Not attempted in this lane

- **The 25GbE NIC rig.** Reserved; every number here is loopback and labelled INDICATIVE.
- **`tests/gate.sh`.** Owns port 7899 and cores 0-7, reserved for the mainline operator. The batteries
  it runs were run individually against epoll-booted servers instead, plus the same differ matrix
  `tests/differ_gate.sh` runs.
- **Tuning epoll.** No batching heuristics, no `epoll_pwait2`, no `recvmmsg`, no adaptive spin before
  the park. The engine is a correct portable alternative, not a competitor; io_uring stays the
  default and the one with the measured architecture behind it.
