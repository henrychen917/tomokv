# infofields: SV9 / SV7 / SV6

Implemented INFO identity/configuration fields, a monitor-thread 100 ms / 16-slot
rate sampler and peak tracker, save-status reporting, and MONITOR's generated
`admin` / `skip_monitor` exclusions. No new runtime knob or per-event increment.

**Known remaining deviation:** non-admin commands refused by ACL/NOAUTH can still
reach MONITOR. Moving the feed after authorization changed ordinary dispatch and
parse bodies; the task explicitly permits retaining that ordering in this case.
The new `monitor` differential remains strict and is expected to FAIL on this
deviation. This is not a claim of full SV6 parity or a green gate.

No server, oracle, benchmark, load generator, or gate was executed by this lane.
All wire values below are source-derived contracts, not invented live captures.
The maintainer must append live correctness and performance results.

## Revisions and artifacts

Worktree `/home/user/Projects/cx-infofields`, branch `cx-infofields`. Initial
`origin/cpp` merge advanced `0e894d165` to
`d81b6d3a2b095224d59049dc60342a6ca1574674`. PRE is that merged baseline, built
from its archived source. Both subsequent fetch/merge checks, including the one
immediately before the final build/proof, were already up to date at that commit.
Runtime source is committed as `6e5dd0873bfed5337eaec3352f7522b683c23663`
(after `adff69820` and `3a9deabcf`). No push.

Both builds use the repository's default optimized/debug build, including both
database namespaces. Build commands were pinned to cores 0–15. PRE source is in
`build/infofields/PRE-source`; full build logs are
`build/infofields/build-PRE.log`, `build/infofields/build-POST-final.log`, and
`build/infofields/build-snapshot-final.log`. The last log rebuilds both changed
snapshot objects with the final TU-local budgets and relinks POST; unchanged
objects retain their default-build bytes. Compiler: GCC 13.3.0, repository
`-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread` plus jemalloc flags.

| Arm | Artifact | SHA-256 |
| --- | --- | --- |
| PRE | `build/infofields/PRE/tomokv` | `3a7f8c99d31c0e8606b68ab4b0dbad5833702d56e74e7d3ba6cf5333a4451db5` |
| POST | `build/infofields/POST/tomokv` | `9dc7169c5a68946cfa18a01f05079ae9abb922bc27a47b19b2eb43c6a6b64b81` |
| POST copy | `build/tomokv` | `9dc7169c5a68946cfa18a01f05079ae9abb922bc27a47b19b2eb43c6a6b64b81` |

[SHA256SUMS](docs/infofields/SHA256SUMS) and the final proof identify the actual
ELFs. The POST copy has the same bytes. No PAD arm: none of the locked object
sizes or member offsets changes. Executable text does grow (recorded below), so
these results make no causal performance claim about text placement. This is a
correctness/telemetry change, not a measured optimization.

## Redis field contract

Reference: vanilla Redis **7.4.10**, especially
[server.c](https://raw.githubusercontent.com/redis/redis/7.4.10/src/server.c),
[server.h](https://raw.githubusercontent.com/redis/redis/7.4.10/src/server.h), and
[replication.c](https://raw.githubusercontent.com/redis/redis/7.4.10/src/replication.c).
Source digests: [redis-source-SHA256SUMS](docs/infofields/redis-source-SHA256SUMS).
The local oracle is `/home/user/Projects/redis74/src/redis-server`, SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.

The task's initial section list put `role` and `cluster_enabled` in Server, but
its exact-Redis-placement rule conflicts with that list. Redis 7.4.10 emits them
in **Replication** and **Cluster**, respectively. The implementation and tests
use those actual sections, without duplicate Server fields. Error prefixes
belong to **Errorstats**, not Stats.

Notation: every displayed line includes the exact terminating `\r\n`; `<u>` is
unsigned decimal, `<f2>` decimal with exactly two fractional digits, and `<path>`
is the actual absolute path. Placeholders describe variable bytes, not literal
angle-bracket text. Values intentionally differ across implementations.

| Section / field | Redis 7.4.10 bytes / meaning | PRE | POST bytes / meaning |
| --- | --- | --- | --- |
| Server / run_id | `run_id:<40 lowercase hex>\r\n`, boot identity | absent | same grammar; 20 getrandom bytes at boot; stable across INFO and RESETSTAT |
| Server / executable | `executable:<absolute path>\r\n` | absent | same grammar; realpath of `/proc/self/exe` |
| Server / config_file | `config_file:<loaded absolute path or empty>\r\n` | absent | same grammar; realpath of loaded `Config::conf_path`, or `config_file:\r\n` |
| Server / io_threads_active | `io_threads_active:0\r\n` or `io_threads_active:1\r\n` | absent | `io_threads_active:1\r\n` |
| Replication / role | standalone master: `role:master\r\n` | absent | `role:master\r\n` |
| Cluster / cluster_enabled | standalone: `cluster_enabled:0\r\n` | absent | `cluster_enabled:0\r\n` |
| Persistence / loading | `loading:0\r\n` or `loading:1\r\n` | already present from psfix | unchanged |
| Persistence / rdb_last_bgsave_status | `rdb_last_bgsave_status:ok\r\n` or `rdb_last_bgsave_status:err\r\n` | absent | same bytes; initial ok, RDB completion ok, admitted RDB failure err |
| Stats / latest_fork_usec | `latest_fork_usec:<u>\r\n` | absent | `latest_fork_usec:0\r\n`; no fork |
| Stats / instantaneous_ops_per_sec | `instantaneous_ops_per_sec:<u>\r\n`; mean of 16 cron rates | same name/grammar, 8-slot INFO-driven sampling excluding INFO | same name/grammar, 16-slot cron mean including INFO in existing command totals |
| Stats / instantaneous_input_kbps | `instantaneous_input_kbps:<f2>\r\n` | absent | same grammar, mean input bytes/s converted with `(float)rate / 1024` |
| Stats / instantaneous_output_kbps | `instantaneous_output_kbps:<f2>\r\n` | absent | same grammar, mean output bytes/s converted with `(float)rate / 1024` |
| Memory / used_memory_peak | `used_memory_peak:<u>\r\n`; tracked outside INFO | same grammar; observed only while rendering Memory | same grammar; also observed by every cron sample |
| Memory / maxmemory | `maxmemory:<u>\r\n` | absent | same grammar, current CONFIG value; default `maxmemory:0\r\n` |
| Memory / maxmemory_policy | `maxmemory_policy:<policy>\r\n` | absent | same Redis spelling, current CONFIG value; default `maxmemory_policy:noeviction\r\n` |
| Memory / mem_fragmentation_ratio | `mem_fragmentation_ratio:<f2>\r\n`; RSS/allocator basis | absent | same grammar; jemalloc resident/allocated, `mem_fragmentation_ratio:1.00\r\n` when unavailable |
| Stats / total_reads_processed | `total_reads_processed:<u>\r\n` | absent | omitted, reason below |
| Stats / total_writes_processed | `total_writes_processed:<u>\r\n` | absent | omitted, reason below |
| Errorstats / errorstat_&lt;ERR&gt; | `errorstat_<ERR>:count=<u>\r\n` when that prefix exists | absent | omitted, reason below |

Section headers are `# Server\r\n`, `# Memory\r\n`, `# Persistence\r\n`,
`# Stats\r\n`, `# Replication\r\n`, and `# Cluster\r\n`. Selected-section INFO
must contain the requested header and required names. New fields retain Redis's
spelling, line formats, and sections; the field-name differential deliberately
does not compare dynamic values. TomoKV's existing extension fields remain.

## Sampler and save status

`Server::monitor_controllers()` runs on the existing main/monitor thread after
workers launch. It now caps its cold wait at the next 100 ms sample and remains
active when both LB and flip controllers are off. No sampler call is added to an
IO/EX pass. Each tick sums existing per-thread `total_commands()` and
`LoopSignals::net_input_bytes/net_output_bytes`. Those counters already have
their producers; this change adds no producer stores.

Three zero-filled 16-element rings share a cursor. Each slot is the integer rate
`delta * 1e9 / elapsed_ns`; the reported rate is the integer arithmetic mean over
all 16 slots, including zero slots during warm-up. A late tick uses actual elapsed
time, with no fabricated catch-up samples. INFO only reads the published mean:
it does not advance time, replace slots, or change the cursor. RESETSTAT clears
all slots and latches current existing totals. Counter rollback is clamped to
zero. A cold mutex serializes sampling, reading, reset, and peak observation.

Peak tracking uses the same existing accounting basis as `used_memory`:
published shard object bytes plus published keys times the 12-byte slot charge.
The tick samples it even if nobody requests INFO Memory. Existing Memory-time
observation remains, so a current peak can still be seen immediately. This is a
100 ms sampled peak; a shorter write/delete burst entirely between ticks is not
guaranteed to be captured. Jemalloc resident/allocated is used only for the
fragmentation ratio, not as a denominator for dataset admission accounting.

Save status is a process-wide cold atomic outside the locked structs. It starts
ok, becomes ok on successful RDB completion, and becomes err on abort or failure
to create an admitted snapshot's temporary file. That early error uses an
explicitly cold, non-inlined helper to retain ordinary code generation. Busy refusals do not overwrite
the previous completed status. AOF rewrite success/failure and teardown do not
change this RDB status. Existing failed-SAVE/retry and rewrite checks in
`tests/psfix.py` now assert err/ok/unchanged, respectively; successful SAVE and
BGSAVE in the psfix differential assert ok.

Omissions allowed by the task:

- `total_reads_processed` / `total_writes_processed`: the existing `epoll_recvs`
  counter covers the fallback transport only; `WbEngine::sends_submitted` counts
  submissions, not Redis's processed write events. There is no existing complete
  per-thread pair with Redis's semantics across io_uring. Neither field is emitted.
- `errorstat_*`: per-thread failed-command storage exists but has no producers.
  ACL rejection counters cannot reconstruct all error prefixes/counts, including
  handler, script and transaction errors. No error hook or hot increment was added.
- `appendonly`: engine-level immutability is unchanged, per owner decision group 5.

## MONITOR implementation and strict generator

`climon_monitor_feed()` resolves generated command metadata, including container
subcommands, and excludes either `admin` or `skip_monitor`. This matters for
CONFIG GET: the parent CONFIG metadata itself has no flags. The generated-bit
mask is checked at compile time to contain exactly both names. The old explicit
MONITOR guard stays to preserve unrelated code generation.

The attempted authorization/feed reordering is retained only as
[rejected-acl-order.patch](docs/infofields/rejected-acl-order.patch). Its
[trial audit](docs/infofields/trial-acl-body-audit/summary.json) found **55 of
1,584** selected hot body instances changed, including ordinary parse/dispatch
instantiations in main, genthread, rl2s and reorder. The final source leaves
`src/core/io_loop.h` and `src/core/reorder.cc` byte-for-byte at PRE. The final
broader audit, not this rejected trial, is authoritative for delivered binaries.

The new `monitor` property generator uses exactly two connections per server:
A subscribes with MONITOR; B creates the limited ACL user before subscription,
then drives a deterministic mix. It includes ordinary SET/GET/PING, binary
quoting, CONFIG GET/SET (admin), EVAL (skip_monitor), redacted AUTH, RESET,
command-denied SET, key-denied GET, denied CONFIG GET, and NOAUTH GET. A final
PING marker bounds collection. The expected stream contains eight visible lines.

Each line must be a RESP simple string with a six-digit fractional timestamp,
`[0 <actual driver endpoint>]`, and Redis's exact quoted/escaped argument bytes.
Only the varying timestamp and checked endpoint are removed for cross-server
comparison. AUTH's two arguments must both be `(redacted)`. Missing lines,
unexpected admin/refused lines, malformed framing and an empty witness fail.
There is no skip, tolerance expansion, or xfail.

Expected delivered-POST discrepancy: the command-denied SET, key-denied GET and
NOAUTH GET are still visible because authorization follows the armed feed.
Denied CONFIG is excluded by its admin flag. The strict generator therefore
exposes the preserved ordering defect, as required; it must not be reported green.

## Offline proof and executed checks

Authoritative proof: [final-proof/summary.json](docs/infofields/final-proof/summary.json),
[every changed body and its reason](docs/infofields/final-proof/changed-bodies.json),
[all object receipts](docs/infofields/final-proof/objects.json),
[all body receipts](docs/infofields/final-proof/bodies.json.gz), and
[linked body receipts](docs/infofields/final-proof/linked-ordinary.json.gz).
The tool is `tools/infofields_artifacts.py`; it never executes an ELF.

| Offline metric | PRE | POST / comparison |
| --- | ---: | ---: |
| Object files examined | 94 | 94 |
| Function instances examined (union) | 17057 | 17057 |
| Changed function instances, all explained | — | 81 |
| Ordinary object bodies equal | 4828 | 4828 |
| Ordinary bodies literally raw-byte equal | — | 4764 |
| Static instructions across ordinary object bodies | 1,133,435 | 1,133,435 |
| Linked ordinary bodies proven | 3013 | 3013 |
| Linked bodies literally raw-byte equal | — | 449 |
| Locked size/member layouts equal | all 8 types, both namespaces | all 8 types, both namespaces |
| Unexplained changed bodies | — | 0 |
| .text bytes | 7,812,565 | 7,818,021 (+5,456) |

“Equal” means identical opcode/operand bytes after address relocations are
canonicalized, with matching named call/data targets and referenced constant
bytes. Literal address displacements naturally change when cold text grows.
The summary separately reports raw-byte-equal object and linked counts; no claim
is made that all literal linked displacement bytes are identical. The linked
proof ties each selected body to an identical object body, masks only its actual
relocation fields, and validates the exact GOT MOV-to-LEA linker relaxation in
both arms. Static instruction counts are not dynamic instructions/op or IPC.

The constant canonicalizer honors ELF merge-entry width: a referenced four-byte
float must not accidentally include its unrelated following constant. Controls
reject an opcode mutation and a mutation of the referenced constant, while
accepting a change only to its unreferenced neighbor. See
[byte-controls.json](docs/infofields/final-proof/byte-controls.json).

Changed code is confined to boot identity, INFO/CONFIG RESETSTAT, the existing
monitor timer, MONITOR-armed filtering, save completion/abort/start status, and
helpers emitted by those cold translation units. Full symbol names, PRE/POST
sizes and instruction counts, and individual reasons are in the changed-body
receipt; no unexplained changed body is accepted by the tool.

[All sizes and all DWARF member offsets](docs/infofields/final-proof/layouts.json)
match in **both** `tomo` and `tomo_db0`:

| Type | PRE bytes | POST bytes |
| --- | ---: | ---: |
| Op | 336 | 336 |
| Client | 1984 | 1984 |
| ThreadCtx | 1408 | 1408 |
| Shard | 1440 | 1440 |
| FlatStore | 944 | 944 |
| Rob&lt;64&gt; | 192 | 192 |
| AtomicEntry | 144 | 144 |
| Config | 624 | 624 |

Compiler budget overrides are limited to edited translation units. These are
build-time GCC parameters, not runtime knobs; `inline-unit-growth=0` accompanies
each listed `large-unit-insns` value.

| Edited TU | Normal PRE → POST | db0 PRE → POST |
| --- | --- | --- |
| climon.cc | default → 25735 | default → 25670 |
| t_server.cc | 31261 → 31310 | 31582 → 31630 |
| snapshot.cc | 14554 → 14584 | 14427 → 14457 |

Local executed checks, all serverless:

- Default PRE and POST builds completed.
- `tests/infofields_test.py`: 6 tests pass, including omitted/misplaced field,
  rate-bound, malformed MONITOR, extra admin/refused line and empty-stream controls.
- `tests/differ_test.py`: 24 existing tests pass.
- `tools/infofields_controls.py`: production cron arithmetic passes; a throwaway
  eight-slot implementation fails, and one with tick-time peak tracking removed
  fails. Tests cover warm-up, decay, read-only getters including cursor/time,
  actual elapsed intervals, reset and counter rollback.
- Python syntax checks and `bash -n tests/differ_gate.sh` pass.
- The offline byte/link/layout proof and mutation controls pass.
- `tests/` text/encoding references were searched with grep; retained receipt:
  [test-text-audit.txt](docs/infofields/test-text-audit.txt).

## Maintainer measurement request — not executed here

1. **Correctness geometry:** use `--shards 16`, cores `0-7`, ratio `6:2` for split.
   Repeat armed fused on the same cores, and both atomic modes and RESP versions.
   `tests/differ_gate.sh` already owns these boots and discovers the new property
   generator. A focused harness command (run the two geometries serially) is:

   ```sh
   REDIS74_ROOT=/home/user/Projects/redis74 \
   GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis74/src/redis-server \
   GATE_DIFFER_PROOF_SUITES=docs/infofields/suites.txt \
   GATE_DIFFER_PROOF_SEEDS=docs/infofields/seeds.txt \
   GATE_LOAD_CORES=8-15 GATE_DIFFER_GEOMETRY=split \
   tests/differ_gate.sh build/infofields/POST/tomokv 7899 7900 0-7 6:2
   ```

   Repeat with `GATE_DIFFER_GEOMETRY=armed-fused`. Suite/seed files contain one
   item per line. Run against PRE too for failure controls. The new INFO checks
   should reject missing PRE fields. POST's monitor suite is expected to expose
   the documented refusal-feed defect; retain that failure. Existing psfix boots
   additionally cover the directed failed-SAVE/status/retry assertion.

2. **Rate/peak verdict:** within the existing `infofix` suite, the harness offers
   2,000 PINGs/s to each server, in batches of 20 every 10 ms. Seventeen idle
   samples prime the ring before a silent loaded interval. After more than two
   seconds of load, two INFO Stats polls one second apart must each be within
   **15% of measured offered rate on both servers**. The driver itself must stay
   within 5% of 2,000/s and must not fall 100 ms behind. Both byte rates must be
   positive. During the peak witness, an 8 MiB value lives for six 100 ms ticks
   with only INFO Stats polled, is deleted, and only then is Memory read: its peak
   must retain the allocation while current used memory falls below it. These
   controls reject lazy INFO-only sampling and lazy Memory-only peak tracking.

3. **Ordinary workload regression:** A=the SHA-pinned PRE above; B=SHA-pinned POST.
   Use the gate's ABBA instrument and matched current null controls, with no
   concurrent lane or compile. Request cells
   `h07,h08,h15,h16,h23,h24,h39,h40,h47,h48,h55,h56` from
   `tests/headline_cells.txt`: GET/SET, p1/p32, 512 connections, fused read-local
   off/on and split read-local off, overlap/reorder on, atomic=1. Use its recorded
   32-physical-core geometry (split 16:16), server cores `0-31`, no server SMT,
   load cores `32-111`, no load SMT; retain the instrument's per-cell shard count
   and frozen workload/load settings. This performance geometry is separate from
   the required eight-core correctness reproduction. Example:

   ```sh
   python3 tests/abbagate.py \
     --reference-binary build/infofields/PRE/tomokv \
     --candidate-binary build/infofields/POST/tomokv --build-reference 0 \
     --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
     --only h07,h08,h15,h16,h23,h24,h39,h40,h47,h48,h55,h56 \
     --output build/infofields/MEASURE-ABBA
   ```

   Record each arm's throughput, cycles/op, instructions/op, IPC and latency;
   a partial-cell invocation is a diagnostic, not a full gate PASS. Rate at a
   matched load is the verdict, not the static instruction count. Add paired
   matched-offered-rate observations at 50% and 80% of the slower arm's stable
   rate for each shape if the saturated result could hide periodic collector
   cache-line costs. Freeze that offered rate for all ABBA legs. Ordinary traffic
   has no MONITOR or INFO polling; a separate INFO Stats-at-10-Hz diagnostic can
   report polling cost. Any regression outside the matched-null envelope remains
   unresolved; identical-arm spread above 2% is an invalid run, not acceptable noise.

4. **Controller-off witness:** boot both thread modes at the correctness geometry
   with existing `--key-lb 0 --client-lb 0 --flip-auto 0`. Repeat the INFO rate and
   peak properties to show the monitor still ticks without either planner. Check
   orderly termination with and without a loaded config file; config_file must be
   empty or that file's absolute path, respectively. Do not infer these boots from
   the static proof.

Append PRE/POST live field captures and per-cell results to `MEASURE-RESULT`.
No rate, cycles/op, IPC, runtime field capture, or live-test PASS is supplied here.

Gate row delta is **+0 quick / +0 full**. The new generator is inside existing
aggregated differential jobs, collected at `tests/gate.sh:3393` and following,
after the quick-tier exit at line 3361. Existing infofix feature rows remain
before that exit. No gate collection line was added or retired; maintainer-owned
`EXPECT_QUICK=500` and `EXPECT_FULL=517` are untouched.
