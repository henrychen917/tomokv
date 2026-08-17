# Own-read widening

## Problem

A connection can pipeline an atomic write followed by a read. The read samples global timestamp
`T` once, but its own earlier write may still be installing or may commit above `T` while different
key owners execute the read. Strict `commit_ts <= T` resolution would then permit a torn own read.

## Identity

Each installed version records two immutable values before its owner job retires:

- `origin_client_id`: the real connection that installed it;
- `install_order`: a connection-global program-order number.

The identity survives stamping and commit. It does not point at `csGroup`, so reply reassembly and
group free cannot make it dangle. Connection ids are monotone for the connection lifetime, and
same-key commands from one connection remain ordered on the same owner queue.

## Resolution

When `mset_pending_count != 0`, the resolver first walks the newest-install-first physical chain.
The first non-canceled own node is the program-order newest own write:

- timestamp zero: return it immediately;
- nonzero timestamp: stop, because an older own pending group must not override it.

The stamped-index scan applies normal greatest-rank resolution to every timestamp `<= T`. It also
tracks own versions above `T` and selects the greatest `install_order` among them. An own-above-`T`
candidate overrides the normal result; a tombstone means own absence.

This covers the transition exactly:

- before shared publication, every key can find the own physical version;
- after publication, every key can find the same own timestamp above the old `T`;
- unrelated post-snapshot groups fail the connection-id test.

## Response edge

Final reply publication occurs after the successful shared timestamp and global clock release.
Consequently a nonpipelined next read samples `T >= own commit_ts`. If another writer currently
holds the encoded clock latch, its odd word still exposes the already-published high-bit timestamp,
so this ordering is not lost.

## Removed machinery

No read waits for pending writes. The former Bloom signature, exact membership vectors,
per-connection publishing records, read-hold gate, and per-client commit FIFO are not part of
visibility. `mset_pending_count` is only a relevance gate for the physical own scan.

See `src/server.c::csMsetOwnVersionAt`, `src/server.c::kvobjVersionAt`, and
[version-bag snapshot resolution](version-resolve.md).
