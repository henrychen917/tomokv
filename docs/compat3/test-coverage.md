# Affected-test search and gate job coverage

`affected-test-search.txt` retains the full `rg -n` result over `tests/` for XCLAIM, ENTRIESREAD, XPENDING, XREADGROUP, LIBRARYNAME, allow-oom, no-writes, allow-stale, read-only scripts, pmessage, Invalid min-idle-time, the exact generic OOM prefix, and the FCALL_RO write-flag error. The following mapping preserves whole gate jobs, including their controls and other rows. No existing assertion or timeout was relaxed.

| Matched battery/source | Gate jobs selected |
|---|---|
| `compat3_pubsub.py`, `compat3_streams.py`, `compat3_functions.py`, shared `compat3_lib.py` | `compat3` on final POST, PRE and PAD-A; each row owns all 24 declared legs and an oracle. |
| `streamgroups.py`, `pubsub.py`, `resp3.py`, `scriptsurf.py`, `contarity.py`, `netcmd.py`, `bitfield.py` | `feature-split-0`, `feature-split-1`, `feature-armed-0`, `feature-armed-1`; all feature batteries and shutdown/lane witnesses stay present. |
| `notify.py`, `pubsub.py`, `lua_scripting.py` | `notify` |
| `notify_order.py` | `notify_order`, `notify_aof` |
| `xacct.py`, `xscript.py` | `debug-0`, `debug-1`; both jobs also retain their original script/atomic batteries. |
| `aclfix.py` | `aclfix`; additionally `acl_recheck` and `auth` (the latter again with a fused adapter) for required ACL proof. |
| `clientfix.py` | `clientfix` |
| `perfio.py` | `perfio_stream`, `netio-1s`, `netio-2s` |
| `netcmd_stream_unit.cc` | `netcmd_units`, with its production build prerequisite |
| `multidb.py` | All eight `multidb-{1s,2s}-{read-local 0,1}-{atomic 0,1}` jobs |
| `mdbstamp_checks.cc` | `atomic_units` (runs `multidb-unit`) |
| `atomic_hazards.py` | `atomic_batteries`, retaining the complete torn/RYOW/hazard/shutdown chain |
| `aof.py` | `aof-epoll`, `aof-uring` |
| `globcase.py` | `globcase` |
| `evict_battery.py` | All eight `evict-{lruclock,lfu}-{split,armed}-{0,1}` jobs |
| `differ.py`, `_differ_aclkeys.py` | Standard `differ-split`, `differ-armed` selectors (both atomic modes plus mode equivalence), once per engine. |
| Script support affected by `scripting.cc` and APPLY | Additional `scriptfix`, `script_bounds` jobs |

`replyschema.py`, `aclkeys_unit.cc`, and `aclkeys_wake_unit.cc` have no job reference in this version of `tests/gate.sh`; their matching text is retained, not silently counted as executed coverage. The live ACL wake path is covered by `_differ_aclkeys.py` and all eight multidb jobs. The label fixture and `gate.sh` matches are declarations; the explicit source/fixture check reports the six newly required labels. Performance benchmark jobs and full iteration are outside the authorization and are not run.

All selected executions use `GATE_ONLY_JOBS` with `tests/gate.sh iteration`; this invokes partial correctness mode, never a full iteration or its ABBA/NIC tier. `verify.py` records the exact selectors, binary wrappers and CPU/port arguments. Per-job ledger/output and finalizer records, not the script driver's exit alone, decide each result. Final outcomes belong in the root MEASURE-REQUEST report and the saved gate receipts.
