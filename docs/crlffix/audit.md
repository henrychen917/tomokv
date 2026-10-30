# CRLF reply-site audit

The complete source inventory is [reply-sites.tsv](reply-sites.tsv), with the
same 966 definitions/call sites in [reply-sites.json](reply-sites.json). Each
entry records the exact file, line, expression and disposition; fixed replies
are included so an omitted literal cannot disguise an unexamined writer.
[Source hashes](reply-source-hashes.json) bind the inventory to the reviewed files.

The search covered every `.cc`, `.h` and `.inc` under `src/`: central and local
reply builders, direct `+`/`-` writes, formatted strings, buffer append/reserve
paths, coded replies, parser completions and MONITOR delivery. The disposition
below traces the dynamic values back to their inputs. Literal errors, fixed
metadata/status names and bulk/aggregate fields remain unchanged.

| Site/family (all individual callers are in the inventory) | Client-derived text | Disposition |
|---|---|---|
| `net/resp.h`: `reply_err`, `reply_line_text` | All error payloads | Central trim of terminal CR/LF, followed by one space per remaining CR or LF. Length overload preserves embedded NUL where the caller already used a length. C-string overload retains its previous termination behavior and wrapper structure. |
| `net/resp.h`: `reply_simple` | Status payloads | Central CR/LF mapping without trimming, matching Redis `addReplyStatusSafe`. Literal callers remain identical. |
| `cmd/functions.cc`: `reply_text_error`, `reply_err_string`, `function_list`, LOAD option | Unknown options, function/library/engine names, header metadata, compile/register errors | Raw writer removed. All replies use the central length-aware error builder. LIST explicitly selects mapping without trimming, as Redis `functionListCommand` uses `addReplyErrorSdsSafe`; LOAD's formatted error trims. Existing formatting limits are retained. |
| `cmd/functions.cc`: FCALL/FCALL_RO, function listing/help | Function/library names, source, descriptions, flags | Errors go through the helper; source/name/description results are bulk strings. Status flags/help come from fixed tables. |
| `cmd/scripting.cc`: `reply_text_error`, `reply_raw_error`, `script_runtime_error` | Compile/run errors, raised error tables, function invocation tag | Both raw writers removed. Final assembled error is sanitized, including the tag appended after the existing Lua error cleanup. Runtime errors use mapping without trimming, matching Redis's safe-SDS path. |
| `cmd/scripting.cc`: `append_lua_result` error table | Lua `{err=...}` (also FCALL) | Central formatted-error builder trims trailing CR/LF before mapping. Previously mapped terminal newlines incorrectly survived as spaces. |
| `cmd/scripting.cc`: `append_lua_result` status table | Lua `{ok=...}` (also FCALL) | Central safe status builder maps without trimming. No change to bulk, verbatim, double, bignum, collection or null conversion. |
| `cmd/t_stream_groups.cc`: `reply_nogroup`, `reply_nogroup_subcommand` | Stream keys and consumer-group names | Both manual line writers removed. Assemble the existing message and route through the central builder. Their previous per-field CR/LF mapping was already safe; quotes and other bytes are preserved. |
| `net/resp.h`: `resp_expected_bulk_error` | One malformed bulk-prefix byte | Manual `-`/payload/terminator writer removed. Central length overload retains Redis's embedded-NUL behavior and maps CR/LF. |
| `net/resp.h`: inline quoting, length/count, preauthentication and malformed-frame paths | Inline protocol input | Error strings are fixed or the single-byte formatter above. They reach central error formatting via IO completion. Fatal protocol errors close the connection, matching Redis. |
| `core/io_loop.h`, `core/reorder.cc`: unknown command, outer arity, `finish_locally`, protocol/error completion | Command name and leading arguments | Both modes already use `reply_err`; now inherit trimming as well as mapping. Metadata arity names are registry-owned. No parsing or successful dispatch instruction is added. |
| `cmd/commands.cc`: container/subcommand/arity helpers | Subcommand names, including FUNCTION, SCRIPT, CLIENT, OBJECT, CONFIG, ACL, COMMAND, XGROUP, XINFO, MEMORY, SLOWLOG, PUBSUB and LATENCY | Central errors already used. Redis's 128-byte/NUL bound on unknown subcommand names is preserved. |
| `cmd/t_server.cc`: CONFIG collection/normalization, HELLO and CLIENT validation | Config names/values, HELLO options, client metadata | All dynamic errors already use `reply_err`; fixed validation errors remain fixed. CONFIG GET/HELLO metadata use bulk/aggregate encoding. |
| `cmd/acl.inc`: denial, CAT, SETUSER modifier, DRYRUN, file handling | User/category/modifier/command names; ACL file errors | All dynamic lines already use `reply_err`. ACL lists/logs/users and DRYRUN descriptive results use bulk/aggregate encoding. Validated usernames and registry command names need no special status handling. |
| `cmd/climon.cc`, `cmd/tracking.cc`, `cmd/server_tail.cc`: CLIENT option/redirect/metadata errors | CLIENT arguments and tracking options | Central errors already used. CLIENT list/info/getname and tracking metadata are bulk/aggregate results. |
| `cmd/climon.cc`: `climon_monitor_format`, `climon_quote_arg`, delivery/forwarding | MONITOR command names, keys, values and other arguments | Deliberately emits a status line. Existing Redis-compatible quoting converts CR/LF to the two bytes `\\r`/`\\n`, escapes quotes/backslashes and encodes other controls. Header time/address are generated by the server. Kept unchanged; oracle battery compares escaped payloads and verifies following replies. |
| `cmd/t_string.cc`: OBJECT, TYPE, expiry/argument errors | OBJECT subcommand; command names/arguments | Errors are central; TYPE is a fixed type-name status; object encodings are bulk strings. |
| `cmd/t_hash.cc`, `cmd/t_hash_ttl.cc` | Hash/field expiry option names and argument errors | Central errors; data results remain length-delimited. |
| `cmd/geo.cc`, `cmd/pfdebug.cc` | GEO argument values/unit names, PFDEBUG subcommand | Central errors. PFDEBUG encoding statuses are fixed `dense`/`sparse` literals. |
| `cmd/slowlog.cc`, `cmd/server_tail.cc` | SLOWLOG/LATENCY/COMMAND options and validation details | Central errors. HELP/status flags are fixed tables; client strings and log argument arrays are bulk replies. |
| `cmd/multi.inc`, `cmd/scatter_engine.inc`, `cmd/xshard_commands.inc` | Transaction/scatter errors, LCS result errors, resolved command names | Central errors; cached/deferred RESP buffers originate in these builders or length-delimited reply encoders. No additional raw error writer. |
| `core/pubsub.inc` | Rejected command/subcommand in subscribed state | Central errors. Channel/message payloads are bulk members of arrays/pushes; HELP is fixed status text. |
| `cmd/cmdmeta.cc`, `cmd/server_tail.cc` metadata flags | Command/ACL/key-spec names | Status names come from compiled metadata, not request bytes. Unknown metadata lookup requests use central errors or empty/null bulk aggregates. |
| Module-like surfaces | MODULE names/filter strings | MODULE/CLUSTER/replication surfaces are deliberately unregistered. They use the ordinary unknown-command path, whose wording intentionally differs from Redis's registered MODULE command. COMMAND LIST FILTERBY MODULE is an empty aggregate with no echoed name and is tested. No module error callback bypass exists. |
| `persist/aof.cc`, snapshot/shutdown/DEBUG helpers and remaining command families | Persistence errors or fixed validation messages | Every line uses the central builder or a fixed literal; no unframed client payload found. |
| IO admission/protected-mode errors; `exec/op.h` and `net/resp.h` coded fixed replies | None | Direct writes are compile-time literals. Kept unchanged. |
| PING with payload, ECHO, key/value/member results, script source/results, verbatim strings | Arbitrary bytes | Length-delimited encoding is correct for CR/LF. Left unchanged; ECHO and Lua bulk results are positive byte-preservation controls. |

Redis source inspected first: local 7.4.10 `networking.c` (`addReplyError*`,
`addReplyStatus*`, `afterErrorReply`), then `functions.c` and `script_lua.c` to
identify which builder each API uses. `afterErrorReply` handles accounting and
logging, not sanitation. The Redis formatted implementation calls `sdstrim` on
the entire formatted string; the error code/prefix prevents client-controlled
leading CR/LF from being leading bytes of that string. Returned Lua errors
similarly have a leading `-` before trimming.

The lane does not claim to repair unrelated pre-existing wording/length limits,
unsupported commands, Lua APIs or embedded-NUL conversion differences. Ordinary
CR/LF-free replies retain their existing bytes. The battery's clean twins are
Redis-equal; MODULE's intentionally absent command surface is audited separately
instead of presenting that known difference as equality.

## Wave9 integration additions

The original 966-site inventory above is frozen lane evidence. These additions
audit the subsequently integrated source without rewriting that evidence.

| Lane / added or moved site | Disposition |
| --- | --- |
| protofix, `RespInlineDecoder::decode` and `resp_parse_inline` | Unbalanced quoting and allocation errors are fixed strings returned through `err`; the existing IO completion routes them through central `reply_err`. No direct error writer or request-derived line is introduced. |
| multifix, `command_client_pause` in `cmd/climon.cc` | Four moved validation replies (subcommand/arity, timeout integer/range, negative timeout, WRITE/ALL mode) call central `reply_err` with fixed strings. EXEC reuses this handler, including its winning-commit and IO-retirement paths. |
| multifix, literal Lua engine header | Existing compile/runtime error helpers still use the central length-aware builder. Removing the header for compilation introduces no new writer. |
| streamfix, `cmd_xadd` and `cmd_xautoclaim` | New corrupt-stream and transient COUNT-allocation errors call central `reply_err` with fixed strings. COUNT parse/range, exclusive ID bounds and group ID sentinels reuse central fixed-error helpers. |
| streamfix, MPOP parsing in `blocking.inc` and `xshard_commands.inc` | Invalid/nonpositive count and numkeys inputs converge on existing fixed `reply_err` messages. No user bytes or raw line writer are added. The CRLF-safe NOGROUP builders survive the merge unchanged. |
| blockfix2, XREADGROUP re-probes and EXEC execution | Missing-group and wrong-type wake paths re-enter the existing stream reply helpers. The merged NOGROUP helpers retain crlffix's length-aware central builder. No new raw error/status writer is introduced; copied replies originate in those builders. |
| at412c, `script_escalation.inc` and scatter script phases | All newly reachable OOM/WorkError exits call `script_engine_error_reply`, which delegates to `reply_work_error`/central `reply_err`. FIFO waiting and escalation replace BUSY/TRYAGAIN replies with retained work; no new refusal text or raw writer. |
| at412c, DEBUG escalation/apply controls in `t_server.cc` | New validation and missing-server errors are fixed literals passed to central `reply_err`. |

The 14 added/moved error call sites after the crlffix merge are enumerated in
[wave9-added-sites.json](wave9-added-sites.json). Four call the script engine's
central WorkError bridge; ten call `reply_err` directly. Protofix precedes this
merge and is covered by its decoder row above. No added raw error/status writer
was found. The integration's CR/LF stream key/group check also verifies that the
next PING reply remains framed after a blocked-reader NOGROUP wake.

## Wave10 integration additions

The original inventory and wave9 supplement remain frozen. The 16 added or moved
reply calls are enumerated in [wave10-added-sites.json](wave10-added-sites.json);
two encode tracking arrays/bulk strings, and the other fourteen emit errors.

| Lane / site | Disposition |
| --- | --- |
| scriptfix2 FUNCTION option, arity and RESTORE errors | `reply_wrong_args` / `reply_err_string` converge on the central length-aware `reply_err`. The merged LIST unknown-argument path retains crlffix's no-trim setting. Header, registration and compile errors are intermediate strings/Lua values until this safe builder emits them. |
| scriptfix2 EVAL shebang and readonly/OOM errors | Header metadata passes through `reply_text_error` and central sanitation. Literal admission errors contain no request bytes. SHA/function case normalization affects lookup, not framing. |
| scriptfix2 Lua API and deep replies | `redis.error_reply` and `redis.status_reply` construct Lua tables; the existing result encoder uses central error/status builders with their respective trailing-newline policies. Stack-limit errors are fixed `reply_err` literals. The crlffix job now includes both APIs, each with clean/CR/LF/CRLF/trailing/edge payloads and following PING/ECHO synchronization. |
| exec1s-d sparse EXEC preparation | The moved MSET arity errors are fixed literals through `reply_err`; sparse storage adds no raw writer. |
| blockfix3 NOGROUP accounting | The reply-site increment precedes the existing central sanitized builder. The old lane's manual writer was not restored. Readiness probes do not increment the counter. |
| pubtrackfix BCAST batching | Keys remain length-delimited bulk members of an array; no error/status writer is added. Subscription confirmations likewise retain structured RESP. |
| infofix offline AOF loading | Denial and timeout helpers use central errors; LOADAOF's Redis-compatible failure text is fixed. CPU/DOCS/latency output remains bulk/aggregate data. |
| snapfix2 and rlfix4 | No new error/status writer. Parser errors retain wave9's central builders and protofix decoder. |

No added direct `-`/`+` writer was found. This is a source audit; runtime results
are recorded separately in the wave10 job receipts.

Wave10 integration repair: FUNCTION LOAD unknown options must reach the central
`reply_err` builder before CR/LF mapping. `script_clean_error` erased the terminal
CR/LF distinction and retained two spaces on the trailing/edges cases. The raw
length-bearing string restores Redis's trim-before-map order; the existing
`function-load-option` oracle cases rejected the merged predecessor in every
mode, engine, atomic setting and database runtime.

## Wave11 integration additions

[Added or moved error sites](wave11-added-sites.json) enumerate the merged
phase-14 changes relative to e2b237926. Existing lane inventories remain frozen.

| Lane / site | Disposition |
| --- | --- |
| flipfix5, `cmd_debug_impl` FLIP-STAGE-HOLD | Integer/range and missing-server errors are fixed literals through `reply_err`; success uses fixed `reply_ok`. INFO's refusal counter is length-delimited numeric output. |
| scriptfix3, `cmd_eval` private-cache fallback | Validation errors and allocation failure reach `reply_text_error`, which calls the central length-aware `reply_err`. Metadata owns the original source/SHA; warm lookups add no error writer. |
| wave11, `compile_eval` metadata owner retention | An allocation failure clears the Lua stack and emits the fixed `out of memory caching script` text through `reply_text_error` / central `reply_err`. A failed insertion publishes no compiled entry. |
| climonfix5, script admission extracted into `script_nested_execute` | AOF failure and memory rejection call the existing central helpers. Every deferred Lua error buffer is completely initialized on its error branch. Successful admission produces no error. |
| shared shebang metadata and compiled no-writes closure | Retains wave10/scriptfix2's full quoted flag grammar and diagnostic text. Parse errors pass to `reply_text_error`; readonly runtime errors retain `reply_raw_error`'s map-without-trim policy. PAUSE classification reads flags and never emits a reply. |
| climonfix4/5 nested MONITOR | New `climon_monitor_script_format` uses the existing `climon_quote_arg` for every command argument, escaping CR/LF and all control bytes. Only generated timestamp/DB/Lua markers are concatenated outside quoted arguments. Pending/forwarded lines retain those already-escaped bytes. RESET exclusion changes recipients, not framing. |
| CLIENT metadata and PAUSE accounting | Added names are registry-owned metadata. CLIENT INFO/LIST remain length-delimited bulk output. Container arity uses the existing centralized helper. No new raw error writer. |
| persistent EVAL/FUNCTION interpreters and FUNCTION library environment | Existing compile/run/result builders survive unchanged, including wave10's FUNCTION LOAD option trim-before-map repair. Lua error/status tables still use distinct central error/status builders. |
| flushmerit | Harness only; no production reply site. |

Source review found no added unescaped request-derived status/error writer.
The existing `crlffix` and `scriptfix2` gate jobs exercise malformed headers,
Lua/FUNCTION errors and frame synchronization on the merged executable;
wave11's job receipts record their actual results separately.
