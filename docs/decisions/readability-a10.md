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
