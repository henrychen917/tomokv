# Retired atomic key-signature probe

The atomic path no longer builds or probes a key-set Bloom signature.

The former own-read HOLD design mapped every written key to one bit of a 64-bit word. Eight-key
groups therefore collided frequently even when their key sets were disjoint. A small-group vector
of full hashes could settle some filter hits exactly, while a per-connection publishing ring kept
departed group signatures available to readers. This machinery was a source of false conflicts
and per-group allocation/copy overhead.

Own-read visibility has since moved to version identity:

- every installed version carries immutable `origin_client_id`;
- an owner-local scan may select the reader connection's uncommitted, non-canceled version; and
- committed resolution accepts the newest version at or below the snapshot, or the reader's own
  stamped version above that snapshot.

Because this exact resolver is the live correctness mechanism, the old `key_sig`, exact-hash
vector, publishing-record ring, builders, copies, and retirement helper have been deleted. The
three `_atomic_probe_retired_*` words in `csGroup` and the one client-tail pointer word are always
zero/NULL layout reserves. They preserve the `tomokv-atomic no` object/cache geometry and are not
read as membership state or allocated in atomic mode.

Routing continues to hash keys for owner and bucket selection. Those hashes do not participate in
visibility or conflict detection.

## Invariants

1. No read or write admission decision depends on a lossy key-set signature.
2. Same-connection read-your-own-write is determined exactly by `origin_client_id` on the key
   owner.
3. Other readers remain bounded by their captured committed-sequence snapshot.
4. The layout-reserve fields remain zero/NULL and cause no allocation.

See [own-read widening](own-read-widening.md), [version resolution](version-resolve.md), and
[atomic admission and reclaim backpressure](atomic-window.md).
