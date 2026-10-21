# moverfix2: R7 inventory attribution

The delivered POST stays byte-for-byte identical to `c100f703f`'s POST. The only
production-test change is the normal namespace's explicit R7 count, 146 -> 145;
DB0 remains 146. No source, Makefile, layout, byte normalizer or negative-control
function changes. Required gate totals remain 677 quick / 694 full; the checked-in
EXPECT constants remain untouched.

## Exact missing bodies and their origin

This is a net loss of one body, not one deleted function. All three relevant
symbols originate in `build/src/cmd/xshard.o`, instantiated by the unchanged
KEYS/RANDOMKEY branch of `xshard_execute` in `src/cmd/scatter_engine.inc`:

| Instantiation (complete demangled names in inventory.json) | PRE bytes | POST bytes |
|---|---:|---:|
| `FlatStore::atomic_for_each_unique_key<FlatStore::atomic_for_each_side_key<xshard_execute(...)::{lambda(Slice)#1}>(...)::{lambda(uint64_t, Slice)#1}>(...) [clone .isra.0]` | 2394 | absent |
| Same instantiation, `[clone .cold]` | 5 | absent |
| `FlatStore::scan<xshard_execute(...)::{lambda(KvObj*)#1}>(...) [clone .constprop.0]` | absent | 1071 |

The first exact mangled symbol is:

```
_ZN4tomo9FlatStore26atomic_for_each_unique_keyIZNS0_24atomic_for_each_side_keyIZNS_14xshard_executeERKNS_4TaskERNS_5ShardERNS_2OpEjEUlNS_5SliceEE_EEvmOT_EUlmSA_E_EEvSD_.isra.0
```

Its cold fragment adds `.cold`. `inventory.json` binds the object and linked
inventories to SHA-256s. The clone already disappears in the object, before the
linker. This is compiler inlining, not merging or deletion of the scan source.
`forensics.py` verifies the whole `flatstore_atomic.inc` file and both KEYS scan
calls are unchanged from PRE `8656f9fa9`.

GCC's late called-once inlining pass puts the 599-IPA-instruction unique-key
clone through `atomic_for_each_side_key` into `xshard_execute` on normal POST;
`normal-128550-ipa-excerpts.txt` records both the decision and final inline-copy
relationship. Its cold fragment is absorbed into the caller as well. The scan
clone remains out of line. On normal PRE, GCC instead inlines the 248-instruction
scan clone into a 3628-instruction caller and retains the two unique-key bodies.
Moverfix's extraction of the phase-two mover/pop code changes that caller and
its inlining choices; it did not remove the KEYS/RANDOMKEY implementation.

DB0 is a separate compile of the same unit with `-DTOMO_SINGLE_DATABASE=1
-Dtomo=tomo_db0` and its own budget, 127250. This makes `Slice::ns` a constant and
removes namespace work from key identity/accessors. Its unit starts at 99356 IPA
instructions, versus 100670 for normal POST. The DB0 dump records scan inlining
into a 3475-instruction caller and retains the 2219-byte unique-key body plus its
5-byte cold fragment on both PRE and POST. Thus its count remains 146. These
are the observed compiler choices; no claim is made that source-level symmetry
requires identical inlining in the two namespaces.

## Restoration trials

`trials.py` uses the Makefile's real compile command with only the per-unit
`large-unit-insns` value changed. Every emitted body is compared to the frozen
current POST object using the existing ccfix canonicalizer. No trial is executed.
The baseline trials reproduce both POST objects' entire canonical body inventory.
All commands, object digests, changed names and sizes are in `trials-*.json`.
The complete IPA dumps are under `build/moverfix2/trials`; their digests and
retained line-numbered excerpts are recorded in `forensics.json`.

| Namespace / budget | Unique-key bodies | Scan bodies | Changed object bodies | Selected hot changes |
|---|---:|---:|---:|---:|
| db0 / 127250 | 2 | 0 | 0 | 0 |
| normal / 100000 | 0 | 0 | 568 | 14 |
| normal / 120000 | 0 | 0 | 246 | 9 |
| normal / 127000 | 0 | 1 | 64 | 3 |
| normal / 128042 | 0 | 1 | 19 | 3 |
| normal / 128350 | 0 | 1 | 12 | 1 |
| normal / 128500 | 0 | 1 | 1 | 0 |
| normal / 128550 | 0 | 1 | 0 | 0 |
| normal / 128600 | 0 | 1 | 4 | 0 |
| normal / 128750 | 0 | 1 | 11 | 0 |
| normal / 129000 | 0 | 1 | 24 | 0 |
| normal / 130000 | 0 | 1 | 54 | 4 |
| normal / 131000 | 0 | 1 | 79 | 7 |
| normal / 132000 | 0 | 1 | 98 | 8 |
| normal / 134000 | 0 | 1 | 131 | 9 |
| normal / 136000 | 2 | 0 | 174 | 10 |
| normal / 138000 | 2 | 0 | 197 | 11 |
| normal / 140000 | 2 | 0 | 213 | 11 |

None of these 17 normal-budget trials restores the two helpers while preserving
all current hot bodies. The lowest tested value retaining them, 136000, changes
174 object bodies, including 10 selected hot bodies. A full compile-only link
with that object was also inspected (`restore-linked.json`): five linked hot
bodies change, including `FlatStore::find` (806 -> 1117 bytes), `find_notify`,
`insert`, `insert_notify` and `erase_notify`. The link also loses the
`xshard_execute` lambda `<false, false>` body, so even its R7 count remains
145/146. Restoring these helpers alone is not an inventory repair.

The fallback permitted by the task therefore retains the delivered POST and
records the precise per-namespace count in `tests/r7shadow_noop.py`, following
13d6fabbc. All GET/SET/MGET/MSET code remains exactly the current POST, because the
entire delivered binary is unchanged. Identity remains a proxy: these trial
differences are reported, not presented as measured performance regressions.
No trial or new arm is proposed for measurement.

Correctness receipts and final binary hashes are recorded in the `## moverfix2`
section of `MEASURE-REQUEST-moverfix.md` and the verification files in this folder.
