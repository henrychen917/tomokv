# Atomic write-path structural diets

This lane implements the owner-approved 7.3, 7.5, and 7.6 changes only. The
collapse-once-per-pass idea (7.4) remains held and is not changed here.

## 7.3: DEL/UNLINK group key storage

Atomic DEL/UNLINK records need stable key bytes after the request can retire, but
they do not need an empty `KvObj` per key. Give an owner-span `AtomicEntry` an
optional trailing offsets array plus packed key bytes. `atomic_prepare_group`
sizes that tail from the span's total key bytes, and the sole shard owner copies
each key before publishing the entry. Other atomic groups retain their existing
object-backed key identity. This changes one allocation per key into the one
record allocation already made per owner span, without changing `AtomicEntry`,
`KeyRef`, or any locked object layout.

The record remains immutable after publication. Its group lifetime pin still
keeps hashes and the decision words alive; the copied tail keeps only DEL/UNLINK
key bytes alive. Foreign readers retain the existing pre-exchange safety-filter
publication and never follow the owner record.

## 7.5: one probe for exchange-or-insert

While `atomic_exchange_physical` probes the current table, retain its first
tombstone and terminal empty slot. If no current-table object matches, probe the
old table once (when rehashing), detach any match there, and install a non-null
replacement directly into the retained current-table slot. A truly new key thus
does not call `insert_into` and repeat the current-table probe.

The read-local twin performs the identical probe and slot choice inside its
existing mutation bracket, using release slot stores and the existing QSBR
retirement discipline. Ordinary `insert()`/SET behavior is untouched; table
live/tomb counts, object bytes, expiry indexing, and the one-copy-across-two-
tables invariant change at the same logical points as today.

## 7.6: one key-position oracle

Replace the three command-specific answers with one fixed-capacity span list
produced beside `classify`. Each span names an argv start, count, stride, and
whether those keys need a local snapshot pre-image. Dynamic forms (numkeys
families, streams, scripts, SORT STORE, and GEO store variants) are parsed
there; simple forms use the same compact representation. Generic
`key_count_for`/`key_arg_for` flatten the plan for routing; the localfast
program-order fence walks all spans; the local snapshot COW gate walks only
snapshot-write spans. There is no heap allocation for the span list, and none
of these three consumers retains a per-command position table. The separate
local AOF post-image policy is outside this oracle: its emitted set is not the
snapshot-write subset (for example, existing COPY logging names both source
and destination).

This preserves routing order, including destination-first STORE forms, because
downstream scatter code indexes results by the flattened order. Parse failure is
returned to the existing caller; option parsers retain their parser-produced
reply, while count-only owner replay cannot fail after IO validation. The XREAD
and XREADGROUP locations therefore have one source of truth for routing, fences,
and snapshot preparation.

## Laws and measurement

All mutations remain on the shard's single owner. Published values and atomic
records remain immutable, read-local readers acquire only the existing table and
safety metadata, and no retry/seqlock is added. No numeric knob is introduced.
The locked layouts (`Op`, `Client`, `ThreadCtx`, `Shard`, `FlatStore`, `Rob<64>`,
`AtomicEntry`, and `Config`) must remain at their existing static assertions.

The coordinator should validate with the atomic gauntlet (`atomic_torn`,
`atomic_ryow`, `atomic_hazards`, `multi_exec`, `s6` at atomic=1, and `bplus.py`).
Compare DEL-heavy allocation/instruction counts for 7.3 and MSET-new-key owner
probes/instructions for 7.5; use the main-command regression cells and the same
owner-write-path instr/op capture for 7.6.
