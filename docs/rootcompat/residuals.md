# Remaining compatibility work

## SETRANGE / APPEND / SETBIT above 4 GiB (item 11)

The unchanged diagnostic job `rootcompat-stringlimit` configures `proto-max-bulk-len` to 5 GiB. Redis 7.4.10 accepts `SETRANGE large 4294967296 x`, the following `APPEND large y`, and `SETBIT large 34359738368 1`. PRE rejects the growth; the APPEND then operates on an absent key. The same mismatch remains on POST. Small configured-limit and signed-offset rejection checks match the oracle. The witness frees each large oracle value before the next allocation and sends no large reply.

This is a representation limitation, not just an error-message check:

- `src/cmd/t_server.cc::command_proto_max_bulk_len` clamps the configured value to `kProtoMaxBulkLenRepresentable`.
- `src/cmd/t_string.cc::cmd_setrange` narrows the allocation size to `uint32_t` before writing at the 64-bit offset. Removing only the clamp would allow an out-of-bounds write.
- `cmd_append` narrows the resulting length when creating the store Slice. `cmd_setbit` uses 32-bit byte offsets and growth sizes.
- `src/store/kvobj.h` has a 32-bit `vlen`, 32-bit raw-length accessors and 32-bit string-allocation/copy interfaces.
- `src/base/slice.h::Slice` uses the other four bytes after its length for database identity. Widening its length also changes its layout in the normal namespace; that type is embedded in layout-locked operation structures.
- `src/net/resp.h` uses 32-bit bulk-reply lengths and parser argument lengths. A wide stored string needs consistent read, mutation, persistence and reply handling too.

A complete fix needs a reviewed wide-string representation, with ownership, immutable replacement/QSBR, persistence, read-local and large-reply coverage. This lane leaves the clamp in place and makes no claim that item 11 is closed. The owner scope question is still unanswered.

## HX-3 (item 12, allowed S2 deferral)

`FlatStore::find` uses `atomic_resolve` for every key while any version is live. That is a logical read and does not physically reap an unrelated expired key. `find_notify` suppresses `expired` in precisely that case. Removing its predicate would emit repeated events without a matching physical deletion, and could expose an expired predecessor while a candidate exists. A correct repair must coordinate the resolver and physical reaping, exceeding the task's one-function/no-algorithm condition. The held-version witness remains red and the source is unchanged.

## Tracking allocation failures

Item 3 fixes queue-cap overflow and allocation failure while adding to an existing queue by retaining a whole-cache invalidation. The pre-existing failure to allocate the first `NotifyShardState` still returns failure and counts a dropped event. The cap witness does not inject that allocation failure. This separate OOM path is not claimed fixed by the cap proof.

## Intermittent pub/sub reply counts observed during Tcl validation

The first final 2s Tcl attempt reports PUBLISH count 1 after UNSUBSCRIBE and PUNSUBSCRIBE completed, where Redis's assertion requires 0. Both exact failures also reproduce on the frozen PRE binary, in separate controls: UNSUBSCRIBE in `proof/pre-tcl-control/`, and PUNSUBSCRIBE in attempt 2 of the eight fresh jobs under `proof/pre-pubsub-release/`. The latter bound uses 16 shards, ratio 6:2, CPUs 48–55, both modes; all eight 1s legs pass. The final isolated full Tcl subset passes in both modes. These baseline wrong-reply races remain unmodified and unskipped; the passing isolated run is not proof that they are repaired.

The final POST diagnostic gate `CioCco` rechecks the large-string limit, HX-3 and absent generic error counters: all three remain red as described above and in `../../MEASURE-REQUEST-rootcompat.md` (the lane-root report). First-sidecar-allocation OOM remains uninjected.
