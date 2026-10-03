# Findings

Source review for the docsregen lane, 2026-10-03, after merging `origin/cpp`
(at `b47544aad`). This replaces the September review's stale claims. Anchors
refer to this source revision; audit reports are leads, not evidence that a
finding still reproduces. No server, benchmark, or gate was run.

## Configuration corrections

These are the five contradicted claims identified by the cmd-server audit
(SV16), re-derived from the parser and CONFIG implementation:

| Previous claim | Current evidence |
| --- | --- |
| Only the combined balancing flag parses. | Independent `key-lb` and `client-lb`, each 0/1 and default 1: `src/core/config.h:306`, `:851`, `:857`. CONFIG GET reports both as immutable: `src/cmd/t_server.cc:343`. |
| Config is 528 bytes; 624 is stale. | `static_assert(sizeof(Config) == 624)` remains at `src/core/config.h:430`. |
| CONFIG REWRITE appends nonempty values verbatim. | `config_quote` quotes whitespace/quotes/backslashes and hex-escapes control/non-ASCII bytes (`src/cmd/server_tail.cc:653`); the writer calls it at `:723`. `requirepass "two words"` remains quoted. Loader support is at `src/core/config.h:1239`. |
| The CONFIG table omits port, bind, and unixsocket. | All three are registered with immutable=true (`src/cmd/t_server.cc:314`); unixsocketperm follows at `:320`. They participate in REWRITE. |
| The old scheduler and combined-balancer spellings are current. | `overlap` and `reorder` parse at `src/core/config.h:795`, `:836`; separate balancing controls parse at `:851`. Reorder is 1s-only after resolution (`src/core/config.h:437`, `src/main.cc:192`). The retired spellings are rejection cases in `tests/config_parser_test.cc`'s `retired` table. |

[CONFIGURATION.md](CONFIGURATION.md) now covers every accepted boot spelling,
including encoding aliases, and distinguishes the 68 canonical CONFIG rows
from the seven extra boot directives. `databases` accepts 1..256 and is
immutable (`src/core/config.h:933`, `src/cmd/t_server.cc:395`). Snapshot boot
loading is automatic from dir/dbfilename after AOF precedence
(`src/main.cc:245`), not selected by a separate input flag.

## Configuration round-tripping

REWRITE preserves original directives not owned by the runtime table,
including inline users and placement (`src/cmd/server_tail.cc:681`). It
canonicalizes encoding aliases (`:694`), writes save clauses separately
(`:707`), and emits escaped single-token values (`:723`). The fixed AOF preamble
declaration is skipped (`:643`). A startup file is required (`:674`).

Preservation does not export CLI overrides for directives absent from the
CONFIG table: a ratio supplied only on the command line is not inserted into
the file. The old claims that REWRITE drops every non-table directive or
cannot quote a password with spaces have been removed. Runtime persistence
and a complete rewrite/restart check still require mainline verification.

## Configuration validation

The old u64-to-u32 narrowing finding for stream limits and latency threshold
no longer describes the code. Their CONFIG kinds are `Uint32` / `Uint32Bytes`
(`src/cmd/t_server.cc:402`, `:417`), normalized through `cfg_parse_u32_limit`
(`:481`, `src/core/config.h:503`), which rejects values beyond UINT32_MAX.

Three parser limitations remain visible without a server: ratio parsing uses
`sscanf` without complete-consumption validation (`src/core/config.h:818`);
`pin yes` emits no token and cannot undo a preceding `pin no` (`:1342`);
and memory-suffix overflow retains unsigned saturation/multiplication behavior
(`:86`). They are not advertised as preferred input forms.

Zero-copy has different zero semantics in two paths: the GET gate requires a
nonzero threshold (`src/cmd/t_string.cc:354`), while scatter computes
`min(zc-min, ValueSlot::kInline)` and may borrow at zero
(`src/cmd/scatter_engine.inc:2985`). The reference therefore does not claim
that zero disables every borrow allocation.

## Reader contract

Read-local has complete runtimes in both modes (`src/main.cc:325`,
`src/core/rl2s.cc:97`), including 2s with overlap 1 (`src/core/rl2s.cc:93`).
Lane-full and quota admission **defer, never demote**
(`src/core/io_loop.h:3443`). Safety failures and same-connection dependencies
can still require owner execution. The RYOW ring predicate is
`read_local_write_conflicts` (`src/net/rob.h:557`, `:644`); pre-arming writes
are fenced until retirement (`:808`).

The earlier retry and in-place-overwrite findings are no longer production
behavior. MGET retains `kAttempts = 2` at `src/core/ex_loop.h:1155`, but the
unconditional jump at `:1291` reaches `owner_demotion` before another attempt.
The retry is reachable through the test/measurement control described there.
GET likewise returns owner fallback on validation failure (`:1311`).
`try_overwrite_read_local` unconditionally returns `NotPossible`
(`src/store/flatstore.h:2712`); the old overwrite-selector header is absent.

**Per-operation sequence validation remains a law concern.** The
per-operation capture acquire-loads `probe_sequence`, reads table/object state,
and compares the sequence again (`src/store/flatstore.h:943`); payload validation
checks it again at `:925`. MGET also checks filter-cell epochs or touched-shard
generations across the whole command (`src/core/ex_loop.h:1009`, `:1035`). These
are sequence-bracket validation paths even though they demote instead of retrying.
Removing retries does not establish an unqualified absence of per-operation
sequence validation. This is a remaining conflict with a law that bans those
checks; documentation changes do not resolve it or weaken the law.

## Command inventory

A static recount of the `CommandSpec kTable` rows in the 18 families assembled
by `command_registry_init` (`src/cmd/commands.cc:124`) gives **245 names**.
The previous 246-count table had 43 entries in `t_server.cc`; its current table
has 42 (`src/cmd/t_server.cc:2787`). The other family counts total 203. This
counts registered names, including aliases and standalone/unsupported handlers,
not full Redis command semantics. The registry copies those rows at
`src/cmd/commands.cc:158`; mainline can confirm with `COMMAND COUNT`.

## Retired descriptions and verification

[ARCHITECTURE-CONTROLPLANE.md](../ARCHITECTURE-CONTROLPLANE.md) now points to the
round-3 as-built reorder/controller descriptions and current source. Links to
absent historical design documents have been removed from this findings file.
The remaining dangling reference in the WAITAOF error (`src/cmd/server_tail.cc:212`)
is a source change outside this docs/tests lane; it was not silently repaired.

The new serverless drift guard checks exact name-set equality (including aliases)
and rejects a fake documented knob in a throwaway copy. The parser fixture reads
the actual worked-example block and validates its defaults and 6:2 / 16-shard
placement without opening a listener. The lane report records these checks and
exact mainline boot commands. These checks establish neither live boot success
nor concurrency correctness or performance.
