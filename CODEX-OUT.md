# cx-redisgap merge — 2026-09-13

Merged `cx-final` at `3adaaae06b2fa2fc32a429b13ed517d97535fbe0` into this lane,
whose binding commit was `0939cecc5`. Before starting the merge, committed
`FIXREDIS.md`, `REDISGAP.md`, and the existing `CODEX-OUT.md` as `a0fe79b25`.
Those reports retain their historical results; this report describes the merged tree.

## Conflict resolutions

| File | Lane wanted | Main wanted | Kept |
| --- | --- | --- | --- |
| `src/core/config.h` | Hash/zset Redis names, ziplist and TomoKV aliases; three boot bindings in padding; explicit validation. | One knob home and parser; `EncodingConfig` with full Redis ranges and list/set controls; current knobs and 624-byte Config lock. | Main's Config and EncodingConfig, plus the three padding fields. EncodingConfig now owns all alias metadata and the shared parser used by file/CLI and CONFIG SET. Redis names retain main's full range; the four original hash/zset compact aliases retain their bare-uint32 grammar, including leading zeroes. Removed the lane's duplicate alias table and compact-limit parser. |
| `src/cmd/t_server.cc` | Bind HLL initialization, AOF recovery setting and listener introspection; shared hash/zset alias values; Redis alias ordering. | Initialize the protocol bulk bound; enumerate and apply encoding controls through EncodingConfig; retain current live configuration publication. | Both initialization paths and all lane boot values. Main's generic encoding table, lookup and owner-limit application remain. GET includes canonical, historical and TomoKV aliases once per spelling. Repeating a Redis spelling is rejected; canonical plus historical alias is accepted in argument order, with the last value winning. Validation completes before any value is applied. |
| `tomokv.conf` | Document Unix permissions, AOF truncated-load policy, HLL threshold and hash/zset aliases. | Document Redis listpack controls, signed list budgets, full ranges and separate fixed integer-set limit. | Both sets of settings, with main's encoding semantics and the lane's alias/boot-binding documentation. The old list/set compact controls stay retired because their semantics differ from the current Redis controls. |
| `CODEX-OUT.md` | Preserve the lane notes. | Delete the old report during main's documentation cleanup. | Kept this requested merge report; the pre-merge notes remain in `a0fe79b25`. |

The release build also found one integration omission outside the conflict markers:
main's new `src/core/rl2s.cc` startup path called `LateUnixListener::open` without
permissions. It now passes `cfg.unixsocketperm`, as do `src/main.cc` and
`src/core/genthread.cc`. No listener was opened during this work.

The lane's AOF recovery bindings, HLL mutation cutoff and same-connection MSETNX
abandonment guard correction survive the merge. Main's newer owner/configuration
mechanisms and thread-mode controls remain intact. Config stays **624 bytes**;
the new boot fields occupy existing padding and the checked-in hot layout locks pass.

## Knobs bound by this lane

There are **11 Redis names for seven controls**:

| Control | Redis spellings | Binding |
| --- | --- | --- |
| Hash entry threshold | `hash-max-listpack-entries`, `hash-max-ziplist-entries` | Startup, live SET/GET, owner limits, canonical rewrite. |
| Hash value threshold | `hash-max-listpack-value`, `hash-max-ziplist-value` | Same; Redis memory-unit grammar. |
| Sorted-set entry threshold | `zset-max-listpack-entries`, `zset-max-ziplist-entries` | Startup, live SET/GET, owner limits, canonical rewrite. |
| Sorted-set value threshold | `zset-max-listpack-value`, `zset-max-ziplist-value` | Same; Redis memory-unit grammar. |
| HLL sparse cutoff | `hll-sparse-max-bytes` | Startup memory-unit parsing, HLL helper initialization, GET and rewrite. |
| Truncated AOF recovery | `aof-load-truncated` | Startup yes/no parsing; legacy recovery and final manifest increment recovery; GET and rewrite. Earlier manifest increments remain strict. |
| Unix socket permissions | `unixsocketperm` | Startup octal parsing, permission application before listening in every startup path, octal GET and rewrite. |

The four retained TomoKV aliases are `hash-max-compact-entries`,
`hash-max-compact-value`, `zset-max-compact-entries`, and `zset-max-compact-value`.
The lane also exposes the actual startup `port`, `bind`, and `unixsocket` values
through GET/rewrite and rejects runtime mutation of them.

**Compatibility limits retained from the lane:** HLL and AOF recovery remain
boot-only here, although Redis permits live CONFIG SET. HLL remains bounded by
UINT32_MAX. Their tests therefore check startup set/get round trips and rejected
live SET with unchanged GET, rather than claiming live Redis parity. Unix permissions
remain immutable at runtime. Main's full signed-64-bit hash/zset setting ranges replace
the lane's former uint32 ceiling for Redis spellings; the existing uint32 owner limits
saturate at the largest representable collection/element size. The historical range
and Config-size statements in REDISGAP.md describe the older lane, not this merge.

## Validation

All builds and executable tests below inherited **cores 112–127**, with at most
**eight make jobs**. No server, benchmark, load generator or gate was started.

| Check | Result |
| --- | --- |
| `taskset -c 112-127 make -j8` | PASS after adding the missing rl2s permission argument. |
| `taskset -c 112-127 make -j8 unit build/netcmd-unit` | PASS: config-parser-test, flipctl-unit, read-local-ring-unit, read-local-write-ring-unit, reorder-unit and waits-unit. |
| `taskset -c 112-127 ./build/netcmd-unit config` | PASS: explicit knob matrix, owner-limit effects, aliases, invalid-update rollback, embedded-NUL rejection, full ranges, canonical rewrite and concurrent rewrite. |
| Python compilation of `tests/knobs.py` and `tests/redisgap.py` | PASS; these network tests were not executed. |
| Whitespace/conflict checks for the merge edits and release dependency freshness | PASS. |

`tests/config_parser_test.cc` covers the new boot values, overrides and negative
grammar, plus every encoding spelling's canonical round trip.
`knob_matrix()` in `tests/netcmd_config_unit.cc` explicitly covers every lane binding
and main's list/set controls. It drives the real CONFIG validator and owner handler;
its private fixture initializes a live-config mailbox and shard without workers or
rings. The first fixture run lacked that mailbox and faulted; after supplying the
production initialization contract, the complete matrix and rewrite test passed.
`tests/knobs.py` retains its gate coverage of actual shard fan-out and now checks the
retained aliases and boot bindings. The manual `tests/redisgap.py` expectations were
updated for main's wider encoding ranges.

Logs are in `build/redisgap-merge-release-retry.log`,
`build/redisgap-merge-unit.log`, `build/redisgap-merge-netcmd-rebuild.log`, and
`build/redisgap-merge-config-matrix.log`.

The complete merge diff includes unchanged context-only whitespace in main's
`KNOB-REVIEW.patch` artifact. That file matches cx-final exactly; the merge edits
pass `git diff --cached cx-final --check`. The lane runner also writes to
`CODEX-OUT.md` while the agent runs; the committed version contains this report.

Release binary: `build/tomokv`.
SHA-256: `b083deeb6ad880e78647e4908630356b9641375eb46d8d0428aa8563e914f633`.

No gate row was added or retired. The existing parser row (line 1183), netcmd config
row (lines 1326–1329), and knobs battery (line 1986) all precede the quick-tier exit
at line 2742. The quick/full count delta is **0 / 0**; main's `EXPECT_QUICK=419`
and `EXPECT_FULL=436` remain unchanged, and `tests/gate.sh` matches cx-final exactly.
The maintainer still owns server boots, the gate and measurement; this is not a claim
that either mode has been boot-tested or the gate has passed on the merged binary.

CX-redisgap-merge-DONE
