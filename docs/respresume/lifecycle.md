# Frontier lifetime audit

The frontier belongs to `Client`, not to its ROB scratch slot or its IO thread.
Its 32-byte descriptor occupies offsets 96–127. The allocation contains only
`{uint32_t offset, uint32_t length}` pairs relative to the unconsumed frame.
There are no pointers into the receive buffer in suspended state. Capacity is
allocated on the first incomplete multibulk, never on accept or a complete frame.
The active flag is bit 31 of the existing inline cursor at offset 76; inline
requests have a fixed 64 KiB bound and cannot use that bit.

| Path | Frontier treatment and reason |
|---|---|
| Ordinary and R7 parse entry | One predicted-false pending-bit check before the existing inline/auth/limit selection. Both call the same cold resume implementation. |
| Complete frame, never suspended | Writes only the existing Op/parse state. Does not read or write the descriptor or allocate frontier storage. Passing its address is not a descriptor access. |
| First incomplete multibulk | Save expected count, completed argument offsets, next unparsed position, and any decoded bulk length. Mark pending in the existing inline cursor word. |
| Incomplete array header | Expected count is zero. No argument has completed; resume validates the unfinished count line. |
| Repeated incomplete read / no-input retry | Append only newly completed offsets. A decoded payload length and its payload offset survive a split body or terminator. |
| Array count above 1 Mi / exceptional bulk header | Validate the exceptional header once it is available; continue at the current argument, without rewalking an already decoded argv prefix. The stateless compatibility wrapper retains its existing behavior. |
| Resumed frame complete / Empty / protocol error | `Client::resume_multibulk` clears the active bit and resets the descriptor; bursts exceeding 512 saved arguments release their storage. Materialized Op slices now refer to the current buffer. |
| `advance_parse` (including AUTH/HELLO/RESET/ACL/MULTI consumption) | The pre-existing `inline_scanned_ = 0` store also clears multibulk validity. No additional per-command store. Connection-local state changes occur after their own complete frame, before parsing a following frame. |
| Dispatch refusal after a complete frame | Existing complete-frame retry semantics remain. The no-replay guarantee concerns incomplete reads, not downstream dispatch refusal. No Op or pointer is pinned while awaiting input. |
| `read_space` / realloc / TLS and epoll receive drains / io_uring receive completion | Appending does not change relative offsets. Growth is still permitted only with ROB quiescence and no live kernel receive pointer. The frontier imposes no new exception to those rules. |
| `reset_rbuf_at_quiescence`, nonempty remainder | Preserve the frontier while moving the unconsumed frame to offset zero. Its offsets already use that frame as origin. |
| `reset_rbuf_at_quiescence`, empty buffer / buffer shedding | Clear the active cursor word; no old frame remains. Existing quiescence and receive guards remain in force. |
| Protocol error / UINT32 buffer saturation / output-limit close / QUIT / killed client | Error paths consume/discard through `advance_parse`; `mark_closing` and `mark_dead` clear validity and release oversized frontier storage. |
| Query-buffer limit / pre-AUTH query limit | Existing byte accounting remains `rlen - rpos`, including the complete prefix of a pending request. The silent-close path destroys/marks the same Client. The change does not consume partial input to evade either limit. |
| Final close / Client destruction | `RespFrontier`'s destructor frees its private offset allocation, independent of ROB argv/reply lifetime. |
| Accept, ordinary and R7 adoption, AF_UNIX handoff | Fresh Client has inactive cursor and empty descriptor. Adoption of the same Client preserves its unconsumed frame. |
| `set_ifid_thread` (FLIP, client-LB, migration commit/rollback) | The descriptor and allocation transfer with the same Client at the existing ownership publication edge. No source-IO state is retained. |
| `replace_fd` on epoll rollback | Only the fd is replaced; the same receive buffer and frontier remain valid. |
| TLS migration | Existing production admission rejects owner-local TLS engine state. TLS parsing otherwise uses the same buffer/frontier code; the change does not permit TLS migration. |

**Migration deliberately preserves, rather than zeros, a pending frontier.** An
owner change does not discard or replace the pending frame. Zeroing it would
force completed arguments to be parsed again, contradicting the primary goal.
The production handoff witness poisons a completed bulk header and then uses the
actual client-LB request or FLIP prepare/commit path, installs the destination
catalog/routing, and finishes through the destination's ordinary/R7 parser.

The tag reset is logical invalidation: stale descriptor scalars cannot be read
while the bit is clear. The next suspension initializes every live scalar before
publishing the bit. Small offset allocations are retained for reuse; larger
ones are shed on resumed completion/error/close. This is storage for a suspended
frame, not an optional configuration surface.

All footprint assertions remain: Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob 192, AtomicEntry 144, Config 624. `post/netcap-unit.log` prints
the production sizes. No shard ownership, write ownership, read-local overwrite,
QSBR, atomicity, or RYOW mechanism changes.
