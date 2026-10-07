# ccfix — Redis 7.4 compatibility, WIP receipt

**Status: WIP; do not merge as a completed CC11/CC18 fix.** CC12 and CC13 are implemented. CC11's command-flag suppression is replaced with source-lookup classification, but an existing pending-MVCC scatter path bypasses the notification sink. CC18 rejection accounting, storage, reset, and output are implemented; **executed-error accounting is not connected, and `failed_calls` remains zero**. The added differential deliberately requires the correct value and will fail on that gap. No server, benchmark, differential, or gate was run by this lane.

The unresolved CC18 constraint is concrete: PRE GET inlines WRONGTYPE into a call to the generic `Op::Sink::append(char const*, size_t)`, also used for successful reply bytes. A dedicated error hook changes the GET body's call target; detecting errors inside generic append adds checks to successful replies. Neither was silently substituted for the owner's cold-path/byte-identity requirements. See [PRE instructions](docs/ccfix/PRE-get-error-arm.txt). A clarification asking whether only the error arm may change was sent; no relaxation was received before this receipt. `note_command_failed` currently has only a serverless unit caller. A follow-up must implement the real error producer, cover nested/script/transaction errors without counting rejections, and rerun these audits.

## Baselines and builds

`origin/cpp` was merged first by fast-forward. PRE is merge-base **b1d931ee2a271f28c9c9c91e2556c8fa36000a4d**, newer than the requested 7213a9405. Production POST source is commit **bd4a20ebf**; later commits contain receipts/tooling only. Branch: `cx-ccfix`. Nothing was pushed.

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/ccfix/PRE/tomokv` | `23b3df7e63aaec6316ec12f3bc563f0a1c7acf2b51ebd8c74c9dba0b2c8f9062` |
| POST | `build/ccfix/POST/tomokv` | `ff58fe0503a9032bf754d4714078f9f9760b4b62b15e40659b60dca0ec852084` |
| Review/default copy | `build/tomokv` | `ff58fe0503a9032bf754d4714078f9f9760b4b62b15e40659b60dca0ec852084` |

`cmp` confirms the two POST paths contain identical bytes. Both database namespace variants are linked in each binary. PRE was built from an archive of the merge-base. Build and serverless work were pinned to CPUs 112–127 (instruction intervals on CPU 112); `make -j8` succeeded without compiler warnings. Build commands:

```sh
taskset -c 112-127 make -C build/ccfix/pre-src -j8 BUILD_ROOT=/home/user/Projects/cx-ccfix/build/ccfix/PRE all
taskset -c 112-127 make -j8 BUILD_ROOT=build/ccfix/POST all
```

[Build manifest](docs/ccfix/build-manifest.json) records section sizes and hashes. GNU `size` text is 8,798,261 → 8,800,229 bytes (+1,968); data 89,704 → 89,704; bss 1,146,456 → 1,146,584 (+128). All locked object layouts are unchanged: `Op=336`, `Client=1984`, `ThreadCtx=1408`, `Shard=1440`, `FlatStore=944`, `Rob<64>=192`, `AtomicEntry=144`, `Config=624`, in both namespace variants. The additional counters occupy two extra planes in the existing heap allocation; cold `StatBaseline` owns two additional vectors. No locked instance layout changed, so no PAD arm was built. There is no claim that changed text/global placement has no performance effect. See [complete layout receipt](docs/ccfix/layout.json).

## Oracle and per-item semantics

The inspected local vanilla source is Redis **7.4.10**, revision `f103d127b9747965e28f20615ef790332661fc68`, under `/home/user/Projects/redis`. [Source hashes](docs/ccfix/oracle-sources.json) identify `notify.c`, `db.c`, `networking.c`, `server.c`, `acl.c`, `t_set.c`, and `bitops.c`. Round-3 `cmd-complex.md` CC11/12/13/18 and `cmd-server.md` commandstats findings were read. Oracle behavior below is established from those sources; live wire comparisons remain for the maintainer's harness.

### CC11: source read lookups and keymiss

Redis attaches keymiss to `lookupKeyRead*`; `LOOKUP_WRITE` suppresses it. COPY reads argv 1; SINTERSTORE/SUNIONSTORE/SDIFFSTORE read argv 2 onward; BITOP reads argv 3 onward. Missing destination write lookups do not notify. COPY of the same object is rejected before lookup.

PRE rejects every keymiss from a command carrying Write. POST classifies the actual source argv Slice in the armed `notify_flat_emit` path. Slice pointer, length, and namespace identity distinguish a source from a destination even when their key bytes match. Ordinary command implementations and the disabled notification prefix are untouched. No new knob, reader retry, seqlock, or store overwrite is introduced.

| Command, all named sources absent | Redis keymiss count | PRE count | POST sink-path count |
|---|---:|---:|---:|
| `COPY nosuchkey dst` | 1 | 0 | 1 |
| Each set STORE, two source args | 2 | 0 | 2 |
| `BITOP AND/OR/XOR dst a b` | 2 | 0 | 2 |
| `BITOP NOT dst a` | 1 | 0 | 1 |
| `GET nosuchkey` | 1 | 1 | 1 |
| `SET nosuchkey v`, missing DEL, missing destination only | 0 | 0 | 0 |
| `COPY nosuchkey nosuchkey` | 0 | 0 | 0 |

The missing-source COPY/STORE/BITOP command reply remains `:0\r\n`; missing GET remains `$-1\r\n`. One keymiss for `nosuchkey` on `__keyevent@0__:keymiss` has exact RESP2 bytes:

```text
*3\r\n$7\r\nmessage\r\n$22\r\n__keyevent@0__:keymiss\r\n$9\r\nnosuchkey\r\n
```

**Remaining path:** `scatter_engine.inc`'s `find_value` at lines 2969–2974 takes `atomic_find_tracked` when `atomic_has_records()` is true, bypassing `store_find<true>`/`find_notify`. The sink fix cannot create an event on that path. Do not claim full concurrent keymiss compatibility from this patch or the serverless classifier test. This requires an armed lookup hook with the disabled-path proof retained. The new wire suite exercises quiescent local and cross-shard paths; it is not a forced pending-MVCC-window witness.

### CC12: canonical CONFIG spelling

Redis chooses A when all NOTIFY_ALL classes are set; otherwise emits `g $ l s h z x e t d n`, followed by K, E, m. In particular, n is inside the non-A branch. POST implements that exact order. These PRE/POST spellings were obtained by compiling and calling each arm's actual header serializer, without a server:

| Input | PRE | POST / Redis |
|---|---|---|
| empty | empty | empty |
| AKE | AKE | AKE |
| AKEn | AKEn | AKE |
| gnK | gKn | gnK |
| gKn | gKn | gnK |
| Em | Em | Em |
| KEA | AKE | AKE |
| $lshzxe | $lshzxe | $lshzxe |
| g$lshzxetdnKEm | AKEmn | AKEm |
| n | n | n |
| nKmE | KEmn | nKEm |
| AEmn | AEmn | AEm |

[Exact frames for every input](docs/ccfix/flag-bytes.json). For AKEn, PRE GET bytes end `$4\r\nAKEn\r\n`; POST ends `$3\r\nAKE\r\n`; both begin `*2\r\n$22\r\nnotify-keyspace-events\r\n`. CONFIG SET replies `+OK\r\n`. The same exact unit expectations abort against PRE at the AKEn case and pass against POST; [negative control](docs/ccfix/flags-negative-control.txt).

### CC13: ACL LOAD error prefix

Redis `addReplyError` prepends `-ERR ` when its text does not start with `-`. Tomo's generic `reply_err` prepends only `-`; the ACL LOAD diagnostic therefore needs `ERR ` added at that call site. POST does so without changing other error helpers.

The harness boots both servers with the same absolute aclfile pathname F, saves its contents, writes `user ccfix_broken bogusrule\n`, compares both complete replies, verifies PING still works, and restores the file in `finally`.

```text
PRE:   -F:1: Syntax error. WARNING: ACL errors detected, no change to the previously active ACL rules was performed\r\n
POST:  -ERR F:1: Syntax error. WARNING: ACL errors detected, no change to the previously active ACL rules was performed\r\n
Redis: -ERR F:1: Syntax error. WARNING: ACL errors detected, no change to the previously active ACL rules was performed\r\n
```

F is replaced with the full configured filename, identically on both endpoints; no basename normalization or error-code normalization occurs in the test. Live wire verification is pending.

### CC18: rejections and commandstats, incomplete

Redis `rejectCommand`/`incrCommandStatsOnError` counts pre-execution errors as rejections; these never reach `call()`. `afterErrorReply` and `call()` account for error replies from executed commands as failures. POST changes ACL/NOAUTH rejection sites to `note_command_rejected`, preserving the existing successful `note_command` source and generated instructions. Three per-thread planes share the existing allocation: calls, rejected_calls, failed_calls. RESETSTAT snapshots all three and INFO includes rejection-only rows.

After RESETSTAT and one ACL-denied GET, the commandstats GET line is:

```text
PRE:  cmdstat_get:calls=1\r\n
POST: cmdstat_get:calls=0,rejected_calls=1,failed_calls=0\r\n
```

After one subsequent executed WRONGTYPE GET:

```text
PRE:             cmdstat_get:calls=2\r\n
POST WIP:        cmdstat_get:calls=1,rejected_calls=1,failed_calls=0\r\n
Required target: cmdstat_get:calls=1,rejected_calls=1,failed_calls=1\r\n
```

These are source-derived expected wire lines; no live commandstats observation is claimed. Redis's corresponding three numeric fields match the required line, with its two timing fields between calls and rejected_calls. The new differential ignores the oracle timing fields, requires the target's exact three-field order, and **asserts `(1,1,1)` rather than accepting WIP's `(1,1,0)`**. It also covers successful GET, NOAUTH GET, and RESETSTAT.

**Owner-approved output deviation:** emit `calls,rejected_calls,failed_calls` only. `usec` and `usec_per_call` are omitted, not zero-filled. No per-command timer was added. This differs from Redis's full INFO surface.

**Consumer check:** [redis-py parse_info](https://github.com/redis/redis-py/blob/27225cf0dcc683ce963437495b07ad7fdc83fc83/redis/_parsers/helpers.py) splits comma-separated `key=value` members by name. Its actual function, extracted from the pinned source and executed serverlessly, returns all three counters correctly. [redis_exporter parseMetricsCommandStats](https://github.com/oliver006/redis_exporter/blob/072bd8bdabb60de075206fbebc9698edb1fff8f1/exporter/info.go) is positional: field 0 is calls and field 1 is interpreted as microseconds; it reads rejected/failed only when there are at least five fields. Thus `calls=1,rejected_calls=2,failed_calls=3` is interpreted as calls=1, duration=2 microseconds, with no extended counters. That exporter does **not** tolerate this mandated omission. The exporter result is a source audit (Go unavailable), not an executed Go test. [Pinned source hashes](docs/ccfix/consumer-sources.json), [results](docs/ccfix/consumer-parser-results.txt).

## Two hot-path audits

The complete object inventory is [final-audit/bodies.json.gz](docs/ccfix/final-audit/bodies.json.gz), with [summary](docs/ccfix/final-audit/summary.json). It compares all 86 production objects in both namespace variants. Relocation addresses are resolved to the same callee/data object and internal offset; constant switch tables are compared by exact bytes. Opcode bytes, registers, immediates, local branches, target identity, and member offsets remain part of equality. Literal linked addresses necessarily move when cold code grows; this is address-resolved body identity, not a claim that entire ELF ranges have identical relocated displacement bytes.

All **1,486/1,486** selected hot-path occurrences match, including the four executor run bodies. There are 16,830 object-function occurrences; 16,741 match and 89 differ/are added/are removed. Of 1,213 command-handler occurrences, 1,208 match; the five exceptions are root CONFIG and root/db0 INFO plus their cold clones. Ordinary GET/SET and all other command-handler occurrences match. [Every changed body and its reason](docs/ccfix/changed-bodies.md), including incidental compiler inlining/data-placement changes; [machine-readable full symbols](docs/ccfix/changed-bodies-with-reasons.json). These incidental changes are disclosed and still need the mainline null.

The existing linked `r7shadow_noop.py --inventory splitlocal` reports **391/396**, not a falsely reported green result. Its only differences are two `CSWTCH` ordinal changes in xshard_execute and three anonymous jump-table label/address changes in db0 IO loops. [Unmodified checker receipt](docs/ccfix/linked-audit.log), [full linked inventory](docs/ccfix/linked-audit.json.gz). Supplemental [linked table proof](docs/ccfix/linked-data-proof.json) verifies identical switch bytes `0000010405` and identical in-function case offsets for all three jump tables. All five function opcode/object-target comparisons match as well. The opcode-negative control flips a PRE GET instruction in memory and the audit detects it; [receipt](docs/ccfix/audit-negative-control.txt). No altered production object was executed.

Cold additions initially crossed GCC inline budgets. The final Makefile adds one instruction of budget to each main TU and pins db0 t_server's budget at 31,500, restoring PRE's executor/IO and RANDOMKEY bodies. This is compiler configuration, not runtime work. The final object audit asserts that any changed ordinary handler or selected hot body fails the check.

**Notifications off:** moving lookup classification after the mask gate adds no instruction to its disabled path. A serverless perf-event instruction witness calls the actual production notification gate 100,000 times with all notifications disabled, and also checks the save-observer-only mask. It separately witnesses the existing calls counter. No listener, IO ring, worker, timer, server, or load generator is started; setup is outside the counted intervals. Kernel/hypervisor instructions are excluded and counter multiplexing is rejected.

| Interval, 100,000 production calls | PRE instructions | POST instructions | Delta |
|---|---:|---:|---:|
| mask 0, keymiss | 1,800,053 | 1,800,053 | 0 |
| mask 0, string | 1,800,053 | 1,800,053 | 0 |
| save-only, keymiss | 2,000,053 | 2,000,053 | 0 |
| save-only, string | 2,400,053 | 2,400,053 | 0 |
| note_command | 700,038 | 700,038 | 0 |

[PRE](docs/ccfix/instructions-PRE.csv) and [POST](docs/ccfix/instructions-POST.csv) receipts are byte-equal. The separate db0 [PRE](docs/ccfix/instructions-PRE-db0.csv) and [POST](docs/ccfix/instructions-POST-db0.csv) witnesses produce the same five counts, also byte-equal. Counts include the identical witness loop and perf-enable/disable boundary overhead; they are not server instructions/op, cycles/op, IPC, or throughput measurements. The original clean/armed selection code and ordinary handlers also pass the byte audit, covering the caller side of the off-path claim.

The offline audits can be reproduced with these commands (the legacy linked checker deliberately returns 1 for its five label-only differences; run the supplemental proof afterwards):

```sh
taskset -c 112-127 python3 tools/ccfix_audit.py build/ccfix/PRE build/ccfix/POST docs/ccfix/final-audit
taskset -c 112-127 python3 tests/r7shadow_noop.py build/ccfix/PRE/tomokv build/ccfix/POST/tomokv build/ccfix/final-linked --inventory splitlocal
taskset -c 112-127 python3 tools/ccfix_tables.py build/ccfix/PRE build/ccfix/POST build/ccfix/final-linked docs/ccfix/final-audit docs/ccfix/linked-data-proof.json
taskset -c 112 build/ccfix/PRE/instr
taskset -c 112 build/ccfix/POST/ccfix_instr
taskset -c 112 build/ccfix/PRE/instr-db0
taskset -c 112 build/ccfix/POST/instr-db0
taskset -c 112 build/ccfix/POST/ccfix_unit
```

## Tests, rows, and maintainer request

`tests/_differ_ccfix.py` joins `tests/differ.py`'s discovered suite list; the existing `tests/differ_gate.sh` owns both listeners and supplies the shared aclfile. Added checks are the twelve CONFIG round trips, full ACL LOAD error bytes, local/cross-shard subscriber counts for all requested source reads, destination/self-copy controls, and commandstats ACL denial/WRONGTYPE/success/NOAUTH/reset. The subscriber uses a publication marker on the same channel to delimit each exact count; missing events produce a count failure, never a skip or a relaxed tolerance. Source/destination equality is explicitly tested. Existing INFO shape assertions now require the three named counters.

**Gate rows: +0 quick / +0 full.** No EXPECT or fixture edits. Existing counts remain **497 / 514**. The quick-tier exit is `tests/gate.sh:3276`; the existing differential collection rows are at lines **3304** (`differ-split`) and **3315** (`differ-armed`), both after that exit. The new suite is inside those rows, not an additional gate row.

Executed checks: both builds; POST serverless flag/classifier/counter-storage assertions; PRE flag negative control; PRE/POST instruction witnesses; object and linked audits plus data-target inspection; locked-layout compile witnesses; Python compilation; shell syntax; `git diff --check`. Counter-storage assertions explicitly do not prove error-producer integration. Wire differentials, thread-mode boots, full gate, and null are **not run**.

Mainline owns measurement. The requested generic fourteen are the already-established **h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64** from `tests/headline_cells.txt`, copied unchanged to [generic14.cells.txt](docs/ccfix/generic14.cells.txt). Use the gate's own ABBA instrument, matched offered load, these PRE/POST hashes, unchanged cell definitions/load plans, and `notify-keyspace-events` empty. Preserve the instrument's documented save setting in both arms; the separate serverless witness above covers both mask-0 and save-observer-only cases. No PAD is named. Report per-cell rate, cycles/op, IPC, and instructions/op, using mainline's validated per-cell null resolution; do not infer a pass from instruction equality or invent a tolerance. For correctness reproductions use the gate geometry: 16 shards, GATE_RATIO, GATE_CORES (default 0–7, 6 IO + 2 EX); run both split and armed fused existing differential rows. The known CC18 failure means this WIP is not a candidate for a green full gate. Complete the error hook and pending-MVCC notification path, rebuild/rehash, and renew the audits before a final merge verdict.
