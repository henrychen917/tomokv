# AT15 — transaction admin replies

Lane `cx-at15`, merged `origin/cpp` first: PRE is `649116c91` (fast-forward from
`b38916d88`). No server, load generator, benchmark, live witness, or gate was run;
all builds and serverless executions were restricted to CPUs 112–127. No push.

## Redis 7.4 table correction and owner decision group 5

The installed oracle source `/tmp/claude-1000/redis74/src/commands.def` and the
checked-in generated `src/cmd/cmdmeta_generated.inc` contradict the audit's
examples. INFO, DEBUG, SUBSCRIBE/PSUBSCRIBE/SSUBSCRIBE and their unsubscribe
partners have **no** `no_multi` flag. MULTI and WATCH have dedicated runtime
checks, also without that flag. SAVE **does** have it. The generated TomoKV table
marks exactly SAVE, SHUTDOWN, and the TomoKV extension FLIP `no_multi`.
`server.c:3972` supplies `ERR Command not allowed inside a transaction`;
`multi.c:93` and `multi.c:456` supply the exact MULTI/WATCH errors below.
No generated metadata or fixture was edited.

The witnesses require the literal replies
`-ERR MULTI calls can not be nested\r\n` and
`-ERR WATCH inside MULTI is not allowed\r\n`. INFO must produce `+QUEUED\r\n`
before EXEC and a bulk (RESP2) or verbatim (RESP3) element inside its array;
DEBUG SLEEP 0 must produce `+QUEUED\r\n` followed by `*1\r\n+OK\r\n` at EXEC.

Redis policy now comes from the generated flag bit, resolved through subcommand
metadata, with no dispatch/route-flag admission check. Two dedicated control
checks retain their Redis behavior: nested MULTI and WATCH fail without dirtying
an otherwise valid transaction. The new witness also adds a dispatch `NoMulti`
bit to INFO and requires it to remain admitted; SHUTDOWN is refused despite
having no dispatch `NoMulti` bit.

**Unresolved engine policy, explicitly retained for owner group 5:**

- Six subscription controls still refuse at queue time. Their IO home/ack and
  asynchronous push protocol cannot be invoked by the synchronous child handler.
  Redis queues these; this remains a deliberate compatibility difference.
- FLUSHDB/FLUSHALL still refuse. Whole-store replacement has no transaction-private
  namespace tombstone, so enabling bare lowering would expose effects before EXEC
  commits and can collide with the transaction's own WATCH reservations.
- ACL still refuses: its registered handler is a stub; the real implementation
  requires `acl_command_entry` on the owning IO loop.
- DEBUG RELOAD/LOADAOF now use the same explicit queue refusal. Their bare lowering
  starts loading/replaces whole stores, without an EXEC-private image. Previously
  they queued and returned the invented unsupported error inside EXEC.

All these policy refusals use exactly
`-ERR Command not allowed inside a transaction\r\n`, followed by
`-EXECABORT Transaction discarded because of previous errors.\r\n` at EXEC.
These exceptions mean **the complete Redis-only admission policy is not yet
achieved**. They are not described as Redis metadata restrictions. No policy
approval is inferred from the outstanding clarification.

## Implementation

INFO with every section selection queues. KEYSPACE/default/all use owner fan-out;
other sections and keyless CONFIG/DEBUG commands execute in an all-owner stage.
CONFIG GET/SET/GET therefore observes the ordered old/new values rather than
running all GETs during reply retirement. CONFIG SET uses existing validated
all-shard lowering. Configuration failures remain EXEC array elements.

DEBUG SLEEP 0 returns an OK element at EXEC. Positive sleeps arm a deadline after
all preceding shard work joins, then park the transaction tasks until the deadline;
no IO or executor thread sleeps. The existing integer accumulator holds the
kind-specific duration/deadline: no object layout grew. DEBUG permission checks
and duration parsing reuse `debug_sleep_prepare`.

INFO's transaction census resolves physical and side-only keys at the transaction
cut with its connection overlay; a plain physical census would miss private
inserts/deletes. The walker is isolated in `src/cmd/multi_admin.cc` to avoid
perturbing ordinary dispatch inlining. INFO around SWAPDB labels counts using the
map at that command's position, before the live map is published at final commit.
Owner reference initialization now belongs to `multi_dispatch_started`, still
before the first owner task is posted, so the production admission API can also
be exercised directly by the serverless witness.

Removing the unsupported name guesses also admits RANDOMKEY, SPOP, SRANDMEMBER,
HRANDFIELD and ZRANDMEMBER through existing owner/MVCC paths. Deterministic
singleton differential vectors cover the element commands.

## Verification and artifacts

`tests/at15_unit.cc` links to actual production objects, with 16 shards and eight
configured workers (2s: 6 IO + 2 EX). No socket, IO ring, listener or worker loop
is started. Both database variants, both thread modes, atomic 0/1 and RESP2/3
are covered. Positive sleep requires an observed retry and the full deadline;
INFO insert/delete asserts exact before/after keyspace bytes.

The SAME witness objects link to frozen PRE objects in `docs/at15/prove.py`.
Each invocation includes four atomic/protocol arms; failing PRE invocations stop
at the first asserted failure. The PRE table does not imply later arms ran after
an earlier expected failure.

| Witness | PRE | POST |
|---|---|---|
| INFO sections / exact EXEC bulk or verbatim framing | Fails (invented error element) | Passes |
| DEBUG SLEEP 0 / positive deferred sleep | Fails at SLEEP 0 | Passes |
| CONFIG GET/SET/GET order | Fails (SET refused) | Passes |
| Metadata SHUTDOWN refusal / route-bit independence | Fails at SHUTDOWN | Passes |
| Nested MULTI / WATCH / SAVE / explicit subscription policy | Passes | Passes |
| INFO sees its own SET and DEL | Not run on PRE | Passes |

Logs, binary hashes, the complete changed-body inventory and hot-body audit are in
`docs/at15/`. `tests/at15.py --self-test` rejects five malformed/unsupported INFO
reply controls. Four shell-row tests reject missing builds and failing witnesses.
The existing EXECABORT/WATCH serverless battery is also rerun after admission
reference initialization moved. Live and differential results remain pending.

## Gate accounting

One added row: `MULTI admin command replies`, `tests/gate.sh:1587`, inside
`storage_units`; collected at line 3155, before the quick exit at line 3285.
Delta **+1 quick / +1 full**: maintainer-owned EXPECT counts should become
**498 / 515** (currently 497 / 514). EXPECT constants and fixture contents are
unchanged. The owner may add the new label to the row-label fixture.

`tests/differ.py`'s existing `multi` suite invokes the directed AT15 wire comparison
in `tests/at15.py`, so `tests/differ_gate.sh` discovers it without another public
gate row. INFO compares required sections and exact RESP framing rather than
server-specific counters. Deterministic INFO keyspace / own-write and INFO/SWAPDB
vectors also enter the existing `multi` and `multidb` streams. No tolerance was
widened, and subscription policy differences are not silently normalized away.

## Maintainer measurement request

1. Run PRE and POST against Redis 7.4, DEBUG enabled, at the gate geometry:
   `--shards 16 --ratio 6:2`, `GATE_CORES=0-7`; repeat in 1s with read-local armed,
   atomic 0/1 and databases 1/16. Run:
   `python3 tests/at15.py --target 127.0.0.1 TARGET --oracle 127.0.0.1 ORACLE --subscription-policy`.
   POST must pass all supported reply checks in RESP2/3. The optional subscription
   witness prints and asserts the **different** exact target/oracle transcripts
   for group 5, independently of the supported-command comparator.
2. Run the existing differential `multi` and `multidb` suites at seeds 7/19 plus the
   gate-selected rotating seed, in both supported geometries and atomic settings.
   INFO keyspace after SET/DEL and after each SWAPDB must agree byte for byte.
3. Run `tests/gate.sh iteration`, both thread modes, after the maintainer updates
   EXPECT counts and the row-label fixture. New row must pass; no main command
   regression is accepted.
4. If assessing rate effects of the cold code placement, use the gate's own ABBA
   instrument for GET/SET/MGET/MSET at p1 and p32 in 1s/2s, PRE vs POST at matched
   offered load, with the PAD-A control below as a separate PRE/PAD-A pair. Report
   rate, cycles/op, instructions/op and IPC. Verdict: zero regression; this
   correctness change makes no performance-gain claim. No data layout changes.

## Frozen binaries and byte audit

| Arm | Frozen binary | SHA-256 |
|---|---|---|
| PRE | `build/at15-pre/tomokv` | `3558521e3c1161dbce2412a5d8252c5a61dc57df5f34c4a18c9683bd20323860` |
| POST | `build/at15-post` | `ef4ff8935edf5d222b70299615e5f99a041e41f370594fc88e2cc691ecaad49a` |
| PAD-A | `build/at15-pad-a` | `60ab5ca429cb982b953b31a9a25112100818fbd3bc18619d052688d51c824617` |

PAD-A is **type A, a PRE-behaviour twin with POST's aggregate `.text` size**.
It links the identical frozen PRE objects plus 11,696 unreachable NOP bytes;
both PAD-A and POST have a 7,794,684-byte `.text` section. It does **not** recreate
POST's per-function placement, so a flat PRE/PAD-A result cannot rule out every
instruction-layout effect. The exact link command, padding receipt and builder
are in [pad-a.json](docs/at15/pad-a.json) and
[build_pad.py](docs/at15/build_pad.py). GNU `size` (which includes additional
read-only sections in its text total) reports PRE 8,798,261 and POST 8,811,157:
+12,896 text bytes, +16 data bytes, unchanged BSS. All structure size locks build.

The unmodified `tools/lbstall_artifacts.py compare build/at15-pre build
docs/at15/hot-bodies.json` reports **1,482 / 1,482 relocation-resolved equal**
protected bodies, **1,480 raw-byte equal**. Ordinary GET/SET and parse/dispatch
bodies are raw-byte identical. The two raw differences are the `FlatStore::erase_in`
clones in the two `t_server.o` variants: only direct-call displacement differs,
with the same resolved target. `xshard_plain_prepare`, including its cold clones,
also remains equal in both variants. The DB0 xshard compile cap preserves that
ordinary write preparation body as the cold MULTI code grows.

The complete changed-body list is [changed-bodies.json](docs/at15/changed-bodies.json):
**107 changed/added/removed bodies**, including 17 bodies in the new census
objects. Per-object counts (DB0 / namespaced): `cmdmeta.o` 1 / 1,
`multi_admin.o` 8 / 9, `t_server.o` 8 / 6, `xshard.o` 35 / 39.
Compiler inlining and relocation changes affect some other cold bodies; this
report does not claim every changed body belongs to MULTI. The inventory uses
the same canonicalizer with support for the four-byte TLS relocation 23, as
shown in [audit_bodies.py](docs/at15/audit_bodies.py). The stock hot-body audit
is unmodified. Forty PRE/POST witness invocations and the final 16-arm serverless
matrix are recorded in [prove.log](docs/at15/prove.log),
[pre-post-witness.log](docs/at15/pre-post-witness.log), and
[serverless.log](docs/at15/serverless.log). Performance remains unmeasured.
