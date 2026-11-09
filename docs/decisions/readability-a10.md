# Network/client readability decisions

Entries dated 2026-11-08 record rationale extracted from comments at baseline
`7595a6705a`. Dates identify this transcription, not the original experiments.
Historical measurements below are inherited observations, not measurements or
performance conclusions from this lane.

## 2026-11-08 — epoll transport selection

`EpollSet` / `IoLoop::run`: retain an epoll readiness engine alongside the default
per-thread io_uring/DEFER_TASKRUN engine for systems where io_uring is unavailable
or unwanted. The previous header attributed measured wins to io_uring without
supplying a result. Routing and retirement remain shared. Migration pre-registers
a destination descriptor and a rollback duplicate before the owner change.

## 2026-11-08 — buffer peak sampling

`IdleBuffers::visit` / `purge_reclaimed`: sample capacity and cursors on cron,
including capacity growth between samples, instead of adding per-receive/reply
peak stores. Keep Redis-compatible thresholds and a separate OpenSSL output pin.
A relaxed global CAS coalesces purges because idle owners may perform no later
allocation that would drive allocator decay.

## 2026-11-08 — Unix listener replacement

`LateUnixListener::open`: probe existing sockets before unlinking. Unlike the
unconditional replacement described for Redis 7.4, a successful connect or an
error other than ECONNREFUSED rejects this bind. The probe/unlink TOCTOU window
remains; the source now states that limit rather than promising that an accepting
endpoint can never be detached.

## 2026-11-08 — protocol-source provenance wording

`resp.h` file header: replace the discussion of the abandoned fork and its licence
with the parser's input/storage contract. The project context identifies this as
a ground-up implementation; this comment-only lane does not independently audit
source provenance.

## 2026-11-08 — strict fast length parsing

`parse_len_crlf` / `resp_length_slow`: direct decimal scanning separates incomplete
input from invalid syntax. The old comment described a strtol implementation
that treated a truncated header as zero. The current fast path rejects zero,
signs and exceptional headers; the cold decoder supplies compatibility grammar
and overflow checking. The 512 MiB fast bound protects the multiply/add operation.

## 2026-11-08 — compile-time parser limits

`resp_parse_t`: keep constant-limit and caller-limit template instantiations.
The inherited comment reports that carrying limits as runtime arguments added
83 instructions/op on loopback and reduced the wire p128 GET result by 5.1%.
It attributes the difference to losing immediate folding. This lane does not
rerun or validate those historical numbers. The source describes the template
choice and the exceptional-header continuation instead.

## 2026-11-08 — resumable request storage

`RespFrontier` / `resp_suspend` / `resp_resume`: save incomplete multibulk progress
as frame-relative offsets, so realloc, quiescent compaction and IO-owner transfer
do not invalidate it. The pending bit shares Client's inline cursor; consuming
a frame resets both protocols without an extra complete-frame dispatch store.

## 2026-11-08 — fixed-reply helper inlining

`reply_ok`, `reply_nil`, `reply_pong`, `reply_null_array`, `reply_emptystr` and RESP3
counterparts: preserve always_inline around the coded-reply attempt. The inherited
comment reports a GCC threshold crossing that made cmd_get call reply_null and
added 22 instructions per split GET miss on deterministic replay. `reply_int`
keeps its separate compiler inlining decision because it contains the digit loop.

## 2026-11-08 — fixed-reply table and integer formatting

`FixedReply` / `format_reply_code` / `format_reply_code_int` / `u32_to_dec_direct`:
keep the fixed 16-byte table copy inline and integer formatting out of line.
The inherited account describes a switch producing an out-of-line jump table
(`notrack jmp *%rax`) and stack canary. It also describes roughly 30 integer-loop
instructions replicated at roughly twenty retire instantiations, calls at those
sites without forced inlining, and scratch-array stack protection. Callers must
reserve kReplyCodeMax even when the wire reply is shorter. These are historical
compiler observations; no new assembly-cost conclusion is asserted here.

## 2026-11-08 — materialize coded replies out of line

`op_materialise_code`: consumers that splice reply bytes, including the borrowed
value flush in assemble_mget, need an ordinary byte buffer before retirement.
Keep SmallBuf growth out of WbEngine's per-op retire lambda. The inherited comment
reports 186 to 263 instructions when this growth path was inlined, with a cost
on a split GET cell but no quantified rate. Preserve both the internal code-zero
check and any call-site guards.

## 2026-11-08 — unified connection layout

`Client`: the inherited 2026-08-24 note describes replacing ConnIn/ConnOut and their
64-byte firewall after removing multi-sender architectures. The current IO owner
parses and sends. Keep receive/send scalars packed and executor routing fields on
one tail line; `obuf_bytes_` and `atomic_groups_io_` stay on IO-private lines. The
old note attributes a pure-MGET regression, without a number, to executor reads
of Client atomic bookkeeping. Op carries the needed snapshot instead.

## 2026-11-08 — connection output capacity and cursor width

`Client::fill_buf`, `swap_buffers`, `submit_legacy`: two 512-byte inline buffers
replace the historical two 16-KiB allocations. On-demand capacity remains after
clear. A 64-bit `wsent_` covers output buffers beyond 4 GiB; a 32-bit cursor wrapped
and resent from earlier offsets. The one-byte fill index preserves offsets 32..47.
The 1984-byte Client lock includes segment/iovec/msghdr state; the old note gives
1408 bytes as the earlier layout and cites a 64-core zero-copy A/B without results.
The TLS slot is at 1980; the historical audit's offset 12 is the interaction clock.

## 2026-11-08 — independent parse-barrier claims

`BarrierOwner`, `barrier_release`, `barrier_release_quiesced`: use one bit per
mechanism, not a shared boolean. Blocking waits for an empty ROB and barrier
producers end the parse pass; independent bits protect against future relaxation
and the DEBUG BARRIER-HOLD overlap. The old six-owner/seventh-spare-bit wording
is stale: seven production bits and the debug bit are assigned. This lane changes
no barrier behavior or field width.

## 2026-11-08 — out-of-band frame boundaries

`Client::append_oob` / `WbEngine::defer_oob`: never attach a push to a live Op's
reply buffer. A borrowed GET keeps its bulk header there, so that insertion
splits header/body and can race a worker's SmallBuf growth. Never overwrite a
live direct-reply region in fill spare capacity. Seal older fill bytes into the
segment queue before a frame, then respect its dispatch frontier; a parked
blocking operation remains the explicit bounded-latency exception.

## 2026-11-08 — client release and queued completion pointers

`Client::safe_to_release`: ROB quiescence alone does not consume a pending
Client* retire notification. The inherited ASAN incident describes IO retirement
through flush_ready, disconnect/free, then a late notification drain. The claimed
retire flag, receive/send pins and WATCH references remain separate lifetime
fences. This is a corrected description, not a lifetime-protocol change.

## 2026-11-08 — ring fallback and explicit completion service

`Ring::init` / `submit_and_reap`: retry initialization without optional flags when
the kernel rejects them. The former fork anecdote is not a contract of this tree.
DEFER_TASKRUN requires an event-requesting enter even on a busy loop; the inherited
comment reports about 3.9 ms per depth-one operation, matching p99, when only plain
submit was used. No timing result is produced by this lane. `sqe` retries once
and can still return null; source comments now acknowledge the existing callers'
back-pressure path.

## 2026-11-08 — tagged eventfd wakeups

`Ring::msg_to`, `post_mail`, `for_each_mail`: the snapshot barrier needs its
SnapshotManager pointer as well as a wake, so epoll uses a mutex-protected tag
mailbox before ringing eventfd. This preserves Channel/ThreadCtx notification
interfaces without an io_uring setup syscall. The old assertion that only parked
peers contend is not established by post_mail; the comment states the actual
mutex publication and retained-tag behavior after an eventfd write failure.

## 2026-11-08 — send classification without a shadow count

`Ring::note_send_pending` / `sq_ready`: classify batches containing SEND because
depth-one request/response clients wait for the send before producing another
arrival. Query liburing's own tail/head state for queue occupancy; no generic
per-SQE shadow counter is needed.

## 2026-11-08 — sender architecture history

`WbEngine`: the inherited 2026-08-24 header records deletion of dedicated-writeback
and executor-writeback variants. Its historical figures were +2–4% at 64c/p32,
−22..−35% at p1, −8% at p32 up to 32 cores, −8% overload with double the tail, and
large-value wire-wall ties with worse tail; a p1..p32 sweep was −33% to +4% with a
p16–32 crossover. It also says exwb won no measured cell. A later sentence in the
same header contradicts its overload account, so neither is promoted to a current
claim. The header's width-law discussion and fork WbGuard anecdote are historical:
this implementation's current IO owner retires, stages and sends without a sender
mutex. The removed WbGuard discussion described capturing one lock target to avoid
locking and unlocking different re-derived objects, observed on a NIC but not
loopback. Neither deleted architecture is proposed here.

## 2026-11-08 — coded-reply staging without scratch arrays

`stage_coded_reply`: render into the fill frontier or materialize into op.reply for
segment/borrow paths. The inherited account says a scratch array changed retire
lambdas from 139–196 to 237–280 instructions and added two to three stack-canary
sequences, including on uncoded GETs. Keep buffer-growth code in the out-of-line
helper. No compiler-cost or throughput experiment is rerun here.

## 2026-11-08 — compile-time coded retirement

`WbEngine::serve_impl` / `serve_tls_impl`: preserve Coded as a template parameter
and the macro expansion inside each method's lambda context. The inherited note
reports roughly 0.9% split-path work loss with a runtime forwarding boundary,
compared with a dead-pad placement control (placement −0.11..−0.30%; binary
−0.83..−1.48%). These inherited observations explain the preserved code shape;
this lane adds no PAD arm and draws no new performance conclusion.

## 2026-11-08 — chunked ROB slots

`Rob::slot`: allocate eight contiguous Ops per touched chunk instead of a heap
allocation per slot. The inherited comment reports a 3% SET/p32 loss for scattered
slots. It also used an obsolete approximately 328-byte context size; the current
336-byte Op lock makes a full 64-slot window 21 KiB. Chunk allocation, reuse and
oversized-buffer shrink behavior are unchanged.

## 2026-11-08 — read-local sidecar capacity

`ReadLocalRobState` / `Rob::read_local_resolve_pending_body`: ring capacity follows
the ROB window, while the precise blind-MSET keyset policy stays at 16 keys.
The inherited independent instrument (`scratchpad/ringsize`) observed 63 live
writes at depth 64/all writes and 19 at depth 32/41% reads. The invariant remains
structural: prune before inserting the incoming Op's distinct window id.

## 2026-11-08 — sidecar footprint and MGET fence

`ReadLocalRobState` / `Rob::arm_current_local_mget_fence`: the inherited size
account gives 1216 bytes, jemalloc's 1280-byte class and +965 RSS bytes per owning
connection versus a 296/320-byte sixteen-slot sidecar. Allocate on the first write
after arming, not accept; keep the MGET fence in Rob so read-only MGET does not
allocate write history. No RSS measurement is performed here.

## 2026-11-08 — coded-reply eligibility

`Rob::acquire` / `acquire_read_local`: the inherited comment reports fused SET
−2.4% and DEL −3.2% cycles/op, but a split GET result of −1.4% on both ABBA repeats.
Keep the ordinary split acquisition's eligibility off. The source now also
acknowledges the SplitLocal parser's Fused=true specialization and WbEngine's Coded
template, which the old claim of shared, unreachable split coded blocks overlooked.

## 2026-11-08 — staged-write resolver boundary

`Rob::acquire_read_local` / `resolve_read_local_write`: the inherited note reports
a 917-byte combined body that GCC would not inline into the parser. Keep an inline
shell and a noinline resolver gated by the Staged tag, not general armedness;
read frames with no candidate skip sidecar resolution. Publication/rollback and
ring age ordering remain the same.

## 2026-11-08 — pending-read admission and summary reset

`Rob::pending_read_local_count` / `complete_pending_read_local_mask`: admission
counts unpublished-to-owner local work, not completed replies still waiting for
flush_ready's bounded serving FIFO after the AOF fence. The inherited observation
says counting in_flight halved operations per rotation. The stale “PHASE 2” pointer
now identifies that step by content. Clearing the complete pending set also
clears its filter, including chunk completion; the old note cites `fcab80884` and
a missing chunk reset that accumulated false hits across read-heavy batches.

## 2026-11-08 — owner-conflict walk shape

`Rob::read_local_owner_conflicts_before`: keep the predicate-templated body together.
The inherited `scratchpad/robdiet/bisect.csv` D-versus-C account reports +2613 bytes
of fused parsing, +1367 bytes of fused draining and 0.13 points more instructions
per read for a forced-inline shell across roughly a dozen predicates.

## 2026-11-08 — tag rejection before the exact write walk

`Rob::read_local_write_conflicts` / `read_local_write_tag_may_match`: keep the empty
check inline (the old combined function was reported as 612 bytes/out of line),
and compare tags in sixteen-lane groups selected by the live-slot bitmap. The
inherited GCC 13.3 account describes a flat 64-lane loop as eight scalar
instructions per iteration, 599 instructions/145 cycles per rejected probe, and
an initial −8% result at 61% reads. It reports mean live histories of six writes
at 61% reads and nine at 41%, and attributes the grouped form to vpcmpeqw plus
bit-weight OR reduction. The old pending-read filter comment separately estimated
under 1% false hits for about eight pending GETs; no such estimate is asserted by
the current source comment.

Inherited `scratchpad/ringsize/probe_cost.sh` table, one connection / 20M probes:

| Live writes | 1..15 | 19 | 40 | 63 |
| --- | ---: | ---: | ---: | ---: |
| Sixteen-slot instructions | 32 | 88 | n/a | n/a |
| Grouped sweep instructions | 49 | 73 | 97 | 121 |
| Sixteen-slot cycles | 5.1 | 15.1 | n/a | n/a |
| Grouped sweep cycles | 8.1 | 11.7 | 16.2 | 19.5 |

At 19, the sixteen-slot history uses a conservative generation, ending every
probe in a false conflict. The old note describes the trade as 17 instructions /
3 cycles more while the smaller ring fits, and 15 fewer instructions after it
fills. The exact descriptor walk remains bounded by the ROB window; nineteen was
an observed mix, not a capacity guarantee.

## 2026-11-08 — arming transient and overflow-force lifetime

`Rob::read_local_arm` / `mark_current_write` / `read_local_write_enter_overflow`:
the inherited 2026-09-27 ruling accepts the bounded owner-path transient for
pre-arming writes and sidecar allocation failure. The latter can reset arming, so
“at most once” is not a valid lifetime claim. The arming fence freezes the newest
unrecorded id rather than extending like an overflow generation. Change force_
with overflow transitions, not speculatively during resolution: an abandoned
candidate must not erase an active generation (write-ring unit case 8).

## 2026-11-08 — interface-first candidate exclusions

`Client` has 347 in-class code lines, `WbEngine` 592 and `Rob` 485 by the lane's
lizard inventory; `Ring` has 242 and does not reach the approximately 300-line
threshold. Client::migration_protocol_idle is a file-path patch site in
`tools/archive/tools/flipfix6_diag.py`. WbEngine is read/patched by
`tests/wbland_checks.py` and inspected by `tests/racefix.py`; Rob is explicitly
comments-only for A20. No class-body split is attempted, so none is kept or
reverted. Definitions and includes retain their order and locations.

## 2026-11-08 — cold CLIENT dispatch placement

`IoLoop::climon_armed_gate` / `climon_start_client_command`: retain the armed gate
inside the notification branch, with separate cold command and retirement entry
points. The inherited header reports +64.9 instructions/op for an abandoned
per-dispatch MONITOR feed hook on an idle server, and says its patch was retained
out of tree. That historical measurement is not reproduced or validated here.
The header's “exactly one call” claim did not cover the other cold entry points.

## 2026-11-08 — canonical client identifiers

`client_parse_i64`: reject leading plus, leading zeroes and negative zero, including
`CLIENT UNBLOCK 05` and `CLIENT KILL ID 05`. The inherited comment describes those
forms as previously accepted; the present contract describes their rejection.

## 2026-11-08 — REPLY ON waits for suppressed predecessors

`IoLoop::climon_start_client_command` / `climon_serve_suppressed`: a synchronous
REPLY ON can run before an older pipelined MGET finishes. Preserve SkipNow until
ROB quiescence so the suppressing writer consumes the earlier reply's header,
borrowed bulks and CRLFs. The current slot is unpublished, so in_flight counts
older operations and permits immediate ON when none remain. The inherited note
reports a leak of that assembled array before ON's +OK when this drain state
was omitted; the source now explains the hazard without a change narrative.

## 2026-11-08 — tracking receipts and MULTI compatibility control

`IoLoop::tracking_register_read` / `tracking_prepare_multi`: the clientcompat_post
path collects EXEC receipts during execution preparation; the retained compatibility
control can collect queued receipts without selecting them for execution. The
inherited comment labels these POST and PAD-A/PRE. Experiment symbols and code
remain intact. `tracking_ack_enable` uses deferred timer readiness for the current
ROB dispatch slot; its condition does not defer IO-local EXEC children.

## 2026-11-08 — tracking ownership and conservative membership

`track_filter_add` / `tracking_broadcast_flush`: the global membership bits remain
set across flushes, avoiding a race with remote registration. The inherited filter
comment incorrectly said a flush clears them. Each IO owns its registration maps,
but remote event transport uses ThreadCtx's pub/sub mutex; the inherited claim
that no armed path has a lock was broader than the code. Observation helpers can
receive unselected operations and return at the receipt tag check.

## 2026-11-08 — invalidation wire compatibility

`IoLoop::tracking_emit_invalidation` / `tracking_deliver_frame` /
`tracking_reply_trackinginfo`: whole-cache invalidation uses RESP3 null and RESP2
null bulk; RESP2 delivery requires a redirected subscriber. A missing redirect is
detected on delivery, retains TRACKING ON and the redirect ID, sets the info flag,
and sends a broken-redirect push on each eligible RESP3 attempt. TRACKINGINFO
uses a RESP3 set for flags and an array for prefixes. The inherited comments cite
oracle confirmation; these checks are not newly measured compatibility results.

## 2026-11-08 — BCAST pass boundary

`IoLoop::tracking_bcast_flush`: pubsub_pass_flush drains notification events,
flushes accumulated BCAST keys, then clears the pending bit. flush_ready's bounded
reply-serving pass follows. The inherited “after command retirement” description
misidentified this boundary. Keep each prefix's sorted key array and last-writer
NOLOOP decision, including writes whose own delivery is suppressed.

## 2026-11-08 — TRACKING validation and prefix ordering

`IoLoop::tracking_client_subcommand`: the inherited differential-test notes name
seed 20 for ordered collision precedence and seed 23 for the implicit empty prefix.
Preserve state-before-value validation for CACHING, mode-before-prefix validation
for TRACKING, and for each supplied prefix compare held prefixes before later
supplied prefixes. OFF parses options but skips the enable-gated constraints;
the old claim that OFF accepts “anything” was too broad. ON replaces optin/optout/
noloop modifiers, rejects explicit contradictions, and ON BCAST without PREFIX
adds one implicit empty prefix even to an explicit prefix set. Sort that prefix
first and avoid duplicate registration/allocation/accounting on repeated ON BCAST.

## 2026-11-08 — epoll still obeys connection lifetime fences

`EpollSet` / `Client::safe_to_release`: synchronous socket syscalls remove the
kernel's outstanding receive-buffer reference. They do not remove ROB, retire-post,
WATCH or OpenSSL reservation fences. The inherited overview's claim that a closing
epoll connection is immediately releasable was too broad; the source now names the
remaining fences.

## 2026-11-08 — shutdown and migration caller exceptions

`EpollSet` registration hooks can execute on a migration's source IO against the
destination epoll descriptor. The event batch remains destination-owned; kernel
registration calls do not imply serialized access to the entire wrapper.
`WbEngine`, `Rob::drain`, `Ring` CQ draining and `Client` cursor cleanup also run
from shutdown_clients_after_join after issuer cancellation and worker joins.
The coordinator rebinds joined-owner callbacks, disables completion followups and
attempts nonblocking ready-prefix output. Contracts explicitly include these
callers instead of treating every use as a running IO-thread operation.
