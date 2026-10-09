# 8 — Database-map wire length: duplicate spellings removed; live format locked

PRE's `sizeof(DatabaseMap::Map)` is **260**, not 256: it contains a 256-byte
mapping base and a 4-byte epoch. Serializing `sizeof(Map)` would include runtime
epoch state and change the format. POST names the base `DatabaseMap::Payload`,
derives `kPayloadBytes` from its size, ties that size to the full uint8_t DB domain,
and locks both version-1 wire formats to 256 bytes with static assertions.
Both AOF record serializers, the AOF load guard, and all twelve snapshot map
length/storage/checksum spellings use the payload quantity. No version bump.

`map_format_unit.cc` links to the actual PRE production objects, writes a plain
mapping and a committed-group mapping through AofProducer/AofManager, and syncs
two disposable AOFs. Each uses a nonidentity swap and an epoch poison value.
The same fixture linked to POST reads the untouched PRE files with
`aof_read_plan` and `aof_load_shard`, checks every mapping byte, and rejects an
otherwise parsed record enlarged to 260 bytes. It requires nonempty output,
the exact 256-byte payload, and a real committed group; an empty/no-op fixture
cannot pass. No listener or worker is started. The live persistfix recovery
battery remains separately requested, not claimed as run.

```
python3 docs/deadswitch/build_unit.py build/deadswitch/pre docs/deadswitch/map_format_unit.cc build/deadswitch/pre/map-format-unit
# Fresh paths are required: writer uses O_EXCL.
build/deadswitch/pre/map-format-unit write build/deadswitch/pre-write.aof
build/deadswitch/pre/map-format-unit write-group build/deadswitch/pre-write-group.aof
python3 docs/deadswitch/build_unit.py build/deadswitch/08-map docs/deadswitch/map_format_unit.cc build/deadswitch/08-map/map-format-unit
build/deadswitch/08-map/map-format-unit read build/deadswitch/pre-write.aof
build/deadswitch/08-map/map-format-unit read build/deadswitch/pre-write-group.aof
```

PRE `dab740964` versus cumulative POST `build/deadswitch/08-map/tomokv`:
**1492/1492 hot, 17078/17078 full bodies; zero changed bodies**. Every loadable
section also matches in bytes/address/size/alignment, excluding build-ID; debug
metadata differs. Static layout locks pass in both namespaces. The complete
tests/tools map/decimal/hex/octal grep is retained as `08-encodings.txt`.
Gate rows +0/+0. No compiler-budget adjustment or PAD.
