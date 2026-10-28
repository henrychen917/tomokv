## scriptfix2

Base: `a214652ec262aa9a5eeaeadf129c0ef76ba6c99c`. Branch: `cx-scriptfix2`. No push.
This is a compatibility change, with no throughput claim. Ten roots are implemented;
two have implemented subsets and two are stopped for owner decisions. The table below
is the scope of the claim, not a claim that all fourteen roots are closed.

| Root | Result and remaining boundary |
| --- | --- |
| EVAL-SHEBANG | Header/token grammar, flag validation, line positions, no-writes, RO admission and existing shard-budget admission implemented. Exact Redis global OOM/eviction semantics remain stopped. Cluster/replica flags are accepted on this single-node server. |
| EVALSHA-SHA-CASE | Cache and interpreter lookups normalize SHA case; diagnostic SHA stays lowercase. |
| FCALL-NAME-CASE | Lookup, routing metadata, collision checks and retained callbacks normalize ASCII case. Registered spelling remains available for diagnostics/listing. Unrelated library loads/deletes retain mixed-case callbacks. |
| FUNCTION-LOAD-DENYOOM | STOPPED: exact global memory admission requires an owner-approved maxmemory model change. LOAD/RESTORE admission is unchanged. |
| FUNCTION-LOAD-ENV | Library initialization sees only the registration redis API. Closures acquire the runtime environment after initialization; escaped registration permissions are revoked. |
| FUNCTION-REGISTER-ARGS | Positional/named argument validation, case-insensitive field labels, name validation and exact errors. |
| FUNCTION-SHEBANG-META | Quoted metadata grammar, NAME case, missing/duplicate names and error precedence. |
| FUNCTION-SUBCMD-ARGS | LOAD options, duplicate LIST options and subcommand arity/error replies. |
| LUA-REDIS-API | error_reply, status_reply, log/LOG_*, version fields and replicate_commands implemented. acl_check_cmd and set_repl remain STOPPED; see below. |
| LUA-SANDBOX-GLOBALS | os.clock, text load/loadstring, coroutine, collectgarbage, string.dump and Redis's seeded PRNG semantics restored. Filesystem/process APIs remain absent. |
| SCRIPT-ERROR-WORDING | No-argument, invalid-type, arity and explicit error-value replies match the oracle probes. |
| SCRIPT-NUMBER-ARG | Full signed-integer conversion and the existing independent Redis-compatible double formatter replace Lua's 14-digit formatting. Each argument owns a rooted Lua string through dispatch. |
| SCRIPT-REPLY-DEPTH | Replies beyond depth 32 work; recursive objects terminate with Redis's Lua-stack-limit inline error. The existing total-element budget remains. |
| ACL-SCRIPTS-NEED-ALLCOMMANDS | STOPPED: the harness row explicitly calls this a deliberate safety boundary. Nested calls have no caller ACL check. |

The original harness reproductions were run before production edits against PRE and
Redis in both modes. Every assigned root differed. The initial and delivered-PRE receipts
are under `docs/scriptfix2/`; rebuilding the same frozen base changed debug-path bytes,
so the delivered PRE was reproduced again. Oracle binaries under `redis/src` and
`redis74/src` have identical SHA-256:
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.

### Owner decisions and retained failures

* `ACL-SCRIPTS-NEED-ALLCOMMANDS`: `src/cmd/acl.inc` deliberately requires
  `AclAllCommands` for ScriptRoute commands. Removing that guard without propagating
  caller identity and checking nested commands would bypass the existing ACL boundary.
  No owner approval to remove it was found in `/home/user/Projects/round4-read/REGISTER.md`.
* `FUNCTION-LOAD-DENYOOM` and complete EVAL shebang OOM parity: TomoKV admits against
  per-shard object budgets; Redis checks global allocator memory and performs eviction
  before admission. Lua/library/allocator/table overhead is not the same budget.
  The October 27 multifix owner register entry identifies the same architecture gap
  for MULTI. This lane does not substitute an arbitrary threshold or weaken an OOM test.
* `redis.acl_check_cmd`: exact ACL/key/channel decisions need the invoking client's
  identity at the owner-side Lua callback and the same nested admission rules.
* `redis.set_repl`: per-command propagation masks cannot be implemented by a no-op
  helper. The current AOF path records final key post-images; mixed suppressed and
  propagated commands need a persistence design decision. Replication is absent by design.
* The existing whitelist, declared-key rule, 100,000-instruction limit and absence of
  Redis's busy window are unchanged. The upstream one-second `os.clock` loop still hits
  the instruction limit; the pcall argument test ends with prohibited PING. Their named
  skips now explain those dependencies. Two error_reply Tcl checks also require the
  unrelated missing INFO errorstats surface; their exact wire replies are directed-tested.

Function names that differ only by case inside one library are accepted by Redis's
case-sensitive library dictionary, while its global dictionary exposes one according
to hash-table iteration. TomoKV selects the last registration consistently for callback
and routing flags; it does not claim to reproduce Redis's randomized collision winner.

### Gate coverage and count change

`job_scriptfix2` adds twelve independently reported roots × two thread modes × two
network engines = **48 rows**. Each row runs both compiled database engines
(`--databases 1` and `16`) against the Redis oracle, at 16 shards and split ratio 6:2.
The two stopped roots are excluded from positive rows and remain in original reproductions.
The API and shebang rows cover the implemented subsets explicitly listed above.

The collector is before the quick-tier exit, so **DQ=+48, DF=+48**. Maintainer-owned
constants remain untouched: **807/824 should become 855/872**. The independently
maintained label fixture exactly matches all 872 source-declared full-tier labels.
The count-sensitive receipt checker must remain red until the owner updates the constants.

The Tcl manifest promotes **78 assertions (53 distinct names)**: functions 67→85,
scripting 70→130. The complete passing selection is 35 files and 1,721 assertions per
mode, up from 1,643 at this lane's base. Exact names are in
`docs/scriptfix2/tcl-promotions.json`. Tests and support files from Redis are unmodified.

### Proof receipts

Final proof results are recorded in `docs/scriptfix2/proof.json` and the associated
gate ledgers. All commands were confined to CPUs 96–111 and owned ports 20500–20599.
Builds used `-j16`. Gate geometry used server CPUs 96–103 and load CPUs 104–111.
Only selected correctness jobs were invoked; partial gate runs do not produce a full
iteration verdict or performance receipt.

The broad differential found and rejected an intermediate numeric-argument lifetime
bug. The final directed tests include multiple numeric arguments with different lengths,
plus LRANGE's `0,-1` boundaries. Intermediate runs invalidated by binary relinking or
stopped after that finding are retained as rejected evidence, not counted as final passes.

`tools/scriptfix2_mutant.py` builds twelve selectable cold-path regressions in a disposable
source copy, links production objects and changes no production source/object. Its
changes and binary hash are recorded in `docs/scriptfix2/mutations.json`. Negative controls
must produce failing rows; an exit status alone is not the witness. PRE and the planted
regression reject both Tcl modes and all twelve directed roots.

### Instructions, layouts and arms

`docs/scriptfix2/artifacts.json` records SHA-256s, all 40 command-scope comparisons,
the object inventory and every locked structure's size and member offsets in both
compiled namespaces. The fixture calls production executor entry points with no sockets
or worker threads. It counts the entry and callees, excluding argument preparation,
dispatch setup and cleanup. MGET/MSET use eight repetitions of one local key.
Each reported count is the minimum of nine user-space retired-instruction readings.
These counts are instruction evidence only.

Batch-one PRE → POST retired instructions, slowlog timing disabled (the other thirty
comparisons, including batch 32 and enabled timing, also have zero deltas):

| Command | 1s PRE → POST | 2s PRE → POST |
| --- | ---: | ---: |
| GET | 1163 → 1163 | 1702 → 1702 |
| SET | 1746 → 1746 | 2285 → 2285 |
| INCR | 1878 → 1878 | 2417 → 2417 |
| MGET | 5230 → 5230 | 5769 → 5769 |
| MSET | 9193 → 9193 | 9732 → 9732 |

The generic object audit also enumerates discarded weak definitions. Three emitted
FlatStore copies change inside scripting.o; the production link selects unchanged copies
from main.o. The raw generic-audit rejection and the explicit weak-definition resolution
are retained. No selected ordinary hot-path body changes. All eight locked sizes and
member offsets match PRE in both compiled namespaces.

Arms are PRE, POST and **PAD-A (A: behaviour twin)**. The PAD executes unmodified PRE
objects and adds unreachable padding/import references to match POST's `.text` address,
total size and PLT imports. **This is a total-text-size control, not an exact function-
placement or data-section-layout twin.** Its limitations and exact sizes are recorded in
`docs/scriptfix2/pad-a.json`; it must not be used to claim that every placement effect
has been eliminated. Original reproductions verify its PRE behavior in both modes.

| Arm | Binary | SHA-256 |
| --- | --- | --- |
| PRE | `build/scriptfix2/pre/tomokv` | `3031f4fe0b0dfde2e001493e8521227b9bcec87bee178349bb9ce12a41ec541d` |
| POST | `build/scriptfix2/tomokv-post-verified` | `cb5dbeae537f1171a54171ddc37f7b2517500360bd6fc8c9208763a75994a317` |
| PAD-A | `build/scriptfix2/tomokv-pad-a` | `b30227d4eedb22d7eed68f1f13c76f490f973f17e64073923801f114961e0a9c` |

POST `.text` is 8,461,255 bytes, versus PRE's 8,457,095 (+4,160). PAD-A matches
POST's text address 129,424 and size. Superseded disposable source checkouts are deleted
after retaining their hashes/counts; `tools/scriptfix2_pad.py` can recreate the frozen
PRE source from Git for relinking against the retained PRE objects.

### Maintainer merit request — NOT RUN in this lane

Use the gate's matched-offered-load ABBA instrument on a quiet box. Run PRE, POST and
the labelled PAD-A; retain per-cell cycles/op, IPC and instructions/op. Rate at matched
offered load is the verdict; instruction counts alone are not a performance verdict.
The compatibility changes have no proposed throughput gain. Ordinary cells are null
regression controls. A PAD shift must be reported as a layout confound.

Run the fourteen generic cells exactly as specified in `docs/compat3/merit-cells.txt`:
`h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0 v1g_l0 d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`.
Also run four **null** split cells: GET and SET at p1 and p32, eight server cores,
16 shards, 6:2, with the matched client/offered-load geometry of the corresponding
generic cell. Retain all individual repetitions and apply the gate's existing decision rule.

Add EVAL, EVALSHA, EVAL_RO, FCALL and FCALL_RO cells in both thread modes at p1/p32:
constant return; declared-key GET; declared-key INCR for writable variants; and a
multi-numeric-argument hash/list script. Run uppercase SHA/function names in warm-cache
variants and normal lowercase names as controls. For shebang/registration/API/deep-reply
cases unsupported by PRE, report compatibility/latency results without manufacturing a
PRE throughput comparison between different semantics. Include cold SCRIPT LOAD and
FUNCTION LOAD/REPLACE with one callback, and a FUNCTION refresh with an unrelated library.

Performance benchmarks, the full `tests/gate.sh iteration`, ABBA and NIC measurements
are **NOT RUN**: those remain assigned to the maintainer. No throughput claim is made.
