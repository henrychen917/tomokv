# DUMP / RESTORE compatibility boundary

TomoKV implements `DUMP` and `RESTORE` as a self-compatible key-copy and backup codec. Redis RDB
wire compatibility is an explicit non-goal: a Redis `DUMP` payload is rejected by TomoKV, and a
TomoKV payload is rejected by Redis with the ordinary payload-version/checksum error. Supporting
Redis wire payloads would require its RDB type tags, legacy compact containers, LZF, and historical
loaders; none of those are used by TomoKV's store.

The version-1 envelope is:

```
[ 8-byte "TOMODMP\0" magic ]
[ u16 little-endian version = 0x8001 ]
[ u8 TomoKV Type ][ u8 snapshot encoding ]
[ payload bytes emitted by SnapshotTypeHooks::read_save ]
[ u64 little-endian XXH64(payload), seed 0 ]
```

The type payload is not a new serializer. `DUMP` drains the same per-type snapshot hooks used by
native snapshot files, and `RESTORE` validates the envelope before passing the payload to the same
hook's `load` function. Magic, version, type range, and XXH64 must all validate before any store
mutation. Version `0x8001` reserves a clearly non-RDB format namespace; the leading magic/header
and XXH64 footer also deliberately differ from Redis's payload plus trailing RDB-version/CRC64
layout.

`RESTORE key ttl payload` follows Redis TTL grammar: `ttl` is relative milliseconds, `ABSTTL`
makes a nonzero value an absolute Unix-millisecond deadline, and zero means persistent. An absolute
deadline already in the past returns `OK` without creating a key; with `REPLACE`, an existing key is
removed. `DUMP` never embeds the source TTL, so preserving it is explicit: read the source `PTTL`
and pass that value to `RESTORE`.

`REPLACE`, `ABSTTL`, `IDLETIME seconds`, and `FREQ frequency` use Redis's option grammar and range
checks. TomoKV has no portable per-key idle/frequency state in this codec, so valid `IDLETIME` and
`FREQ` values are accepted and intentionally ignored. They remain mutually exclusive. Without
`REPLACE`, an existing destination returns exactly `BUSYKEY Target key name already exists.`
