# Atomic version bags

## Two local chains

An atomic whole-value install prepends a metadata object to the physical `version_prev` chain. The
table always points at the newest physical install. Existing nodes are not moved or freed by the
install.

Each physical head also carries `stamped_head`, the head of an owner-local unordered index linked by
`stamped_prev`. A new physical head inherits the current index and immediately prepends itself while
its metadata is still private, before the vmeta/table-head release publication. The group still has
a zero commit marker. A later cancellation marks that already-indexed entry;
readers skip it because its shared marker never becomes nonzero.

The metadata objects form one fixed-size allocation class. A bounded TLS pool on each install
worker recycles blocks after their final grace, with low-water trimming for idle RSS; cold
non-owner and quiescent teardown paths continue to free directly.

The chains have different jobs:

- `version_prev`: own-uncommitted lookup, stable physical unlink, and storage lifetime;
- `stamped_prev`: normal snapshot selection among timestamped candidates.

No chain is globally ordered by commit time. Readers select the greatest visible rank while local
retirement keeps the transient population bounded.

## Shared commit record

Every version in one write group release-points at the same `tomoCommit`. `commit_ts == 0` makes all
of them normally invisible. The last owner release-stores one nonzero timestamp, atomically
changing the visibility predicate for the whole group.

The commit record has one reference per version plus a transient group reference. The version
reference remains until object or metadata retirement has passed the relevant QSBR grace.

## Local prune

After commit publication, each owner's complete record becomes one tagged epoch payload in a
private logical-retire FIFO. After the batch's physical grace and snapshot frontier pass, one owner
lock scope walks the stable record. Each version callback's rank is its local retirement boundary:
it may stable-filter physical versions with lower `(commit_ts, version_order)` ranks and the raw
rank zero. It never consults a global visibility cursor and never removes a pending zero-timestamp
or higher-rank physical version.

Canceled versions use an owner-epoch physical grace without the snapshot frontier and are removable
only after that grace. A lower committed version
whose owner-local retirement is still pending can be unlinked after the successor's grace, but is
marked `detached` instead of physically retired. Its owner's later epoch callback schedules
post-unlink grace.

The callback filters `stamped_prev` to the same live set and release-publishes the repaired index
through the surviving physical head. If the table head changes, whole-key expiration and hash-field
subexpiration indices move with it.

## Promotion

When exactly one committed live value remains and no uncommitted sibling exists:

- a sole tombstone deletes the physical key;
- a sole ordinary value can release-publish the single-committed license, then eventually detach
  and QSBR-retire its metadata, restoring the raw read path.

Canceled siblings do not count as committed values but remain physically protected until their own
graces complete.

## Lifetime invariants

- Install only prepends; it never frees a predecessor.
- Logical unlink follows a successor's pre-unlink grace.
- Physical free follows a separate post-unlink grace.
- Pending owner-local maintenance keeps detached storage allocated until that owner reaches it.
- Commit-record and reclaim charges release before the version metadata or object is freed.
- Owner/bucket lifecycle references survive every owner-affine callback.

See `src/db.c` (`tomoVerMetaNew`, `tomoVersionPruneAfterGrace`) and
[version-bag snapshot resolution](../algorithms/version-resolve.md).
