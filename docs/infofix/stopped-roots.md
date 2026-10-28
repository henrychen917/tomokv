# Stopped roots: source boundaries for the owner

These are source-audit conclusions, not claims that the features are impossible.
The original PRE/Redis protocol differences remain in `pre-repros.json`; POST
still differs for these roots in `post-repros.json`. No positive regression row
or fake successful counter was added for an unimplemented root.

## INFO-CMDSTAT-FIELDS

`src/cmd/t_server.cc` explicitly says to omit unmeasured timing and unimplemented
failed_calls. `ThreadCtx::note_command` counts executions, but neither it nor the
default GET/SET execution path measures individual command duration. The armed
latency path has two clock reads per execution. Enabling that path for every
command would violate this lane's zero-added-instructions contract. Printing
zero usec/usec_per_call would misrepresent successful executions.

Owner decision: permit always-on measurement, or retain the deliberate omission.
Failed-call accounting also depends on the following root.

## INFO-ERRORSTATS

`ThreadCtx::note_command_failed` has storage but no callers. Formatting an error
does not establish whether it is a rejected command, an executed failed command,
a nested Lua command, or an error from a discarded optimistic attempt. In
particular, `script_execute` can run multiple attempts; the armed-only
`latency_tracking_script_begin`/`script_children` mechanism explicitly discards
earlier attempts and publishes children only at the accepted parent retirement.
That mechanism journals command ID/duration, not error prefixes or call outcomes,
and is absent while tracking is off.

A general reply_err hook therefore cannot establish the required counts. A
correct implementation needs accepted-attempt error accounting and retirement
integration, including nested errors that a script catches and does not return.
That is the architecture extension stopped here. The exploratory formatter hook
was removed; it is not part of POST.

Owner decision: authorize that accounting mechanism and settle its instruction
budget before exposing errorstat_<PREFIX> and failed_calls.

## DEBUG-RELOAD-OPTIONS

The assigned upstream tests are `unit/functions`: "FUNCTION - test debug reload
different options" and "FUNCTION - test debug reload with nosave and noflush".
They require a duplicate-library error for NOFLUSH and preservation/merging of
saved and current function libraries for NOSAVE NOFLUSH MERGE.

`SnapshotLoadPlan` in `src/snapshot/snapshot.h` contains database mapping, hash and
epoch metadata, and shard sections. The writer/reader in `snapshot.cc` persists
key data; there is no function-library snapshot payload or merge transaction.
Accepting the three words would not provide those semantics. Changing snapshot
format and function restoration is the architecture extension stopped here.

Owner decision: authorize function-library persistence and its reload merge rules.

## Remaining COMMAND DOCS Tcl boundary

Registered-command documents are repaired. The unmodified upstream CLI hint file
also asks for MIGRATE, which is intentionally absent from the source registry.
The promoted test remains required and fails on that name; it was not restored
to the known-failure list. Advertising metadata for an unimplemented command
would contradict the existing COMMAND LIST/INFO/DOCS absence contract.

Owner decision: retain the command restriction and account for this upstream test
boundary, or authorize the missing command surface.

## LAT-HIST-2 measurement boundary

POST amortizes histogram bookkeeping and commit flushing across homogeneous GET
batches. It keeps individual timers so short calls and long outliers remain
separate histogram samples. Replacing those observations with one shared batch
duration fails the real-executor negative control. Whether this candidate recovers
the reported armed cost is for the requested quiet-box measurement; it has not
been measured here.
