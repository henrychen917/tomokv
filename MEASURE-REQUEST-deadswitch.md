# Deadswitch — tested cleanup and retained live experiments

Worktree/branch: `/home/user/Projects/cx-deadswitch`, `cx-deadswitch`.
Initial and final `origin/cpp`: `dab740964`. Tag before edits:
`deadswitch-before-20261009`. The final fetch/merge was already up to date;
a fresh POST build and complete byte/layout proof followed it. No push.

**Default production cleanup is byte-proved. Live AOF validation remains pending.**
The task explicitly asks for AOF runs on CPUs 112–127 while the shared rules
say “Never run a server, a benchmark, or the gate.” Clarification was requested;
no answer had arrived when this report was prepared. No server, gate, load
generator or performance measurement was started. This is not a live gate receipt.
The AOF common-budget follow-up is also not implemented; its live 16-frame
syscall budget is retained rather than silently retuned.

| Candidate | Test | Verdict | Action taken | Bytes |
|---|---|---|---|---|
| 1. Reorder 128 preset | All production objects: nm + objdump, both queues/namespaces; existing 32/128 unit suites | DEAD production preset | Remove historical preset whitelist; preserve generic bounds and 128-unit coverage | 1492/1492 hot, 17078/17078 full; entire ELF identical |
| 2. AOF writer 16 | Literal 1/4096 production arms; actual writer budget witness, both engines/namespaces; 24 existing persistfix schedules/controls | LIVE | Retain. Shared `aof-writer-batch` and live recovery validation remain pending | Both mutants: 1492/1492 hot, 17076/17078 full; only the two writer-pass immediates change |
| 3. Receive 16 KiB | Six consumers, converted argument types, generated-envelope check, complete body/ELF comparison | DEAD duplicate spelling | Use `kRbufInitial` in ordinary and generated IO | All bodies and loadable sections identical |
| 4. Masked queue 64 | Full two-namespace build and static layout assertions; complete body/ELF comparison | DEAD independent literal | Derive compatibility alias from `tomo::kCacheLine`; assert equality | All bodies and loadable sections identical |
| 5. QuietJitter default 2 | Compile with default removed and retained; inspect all callers | LIVE in tests | Retain; two no-argument calls at config_parser_test.cc:556,558 are the finding | No production source change |
| 6. TTL sidecar selector | Both full builds, complete layouts/body inventory, storage suites and arming negative control | EXPERIMENT | Retain default 0; build inline, sidecar and labeled PAD-B arms | Sidecar: 1186/1492 hot equal; 15985/17199 full union equal, 1214 deltas explained/retained |
| 7. Literal 16 B | Full instantiation/build and complete body/ELF comparison | DEAD duplicate spelling | Share `kInlineLiteralMax` | All bodies and loadable sections identical |
| 8. Database-map 256 | Payload/DB-domain assertions; PRE writes plain/group AOF, POST parses/replays; reject 260-byte control | DEAD duplicate spelling; live wire contract | Derive from `DatabaseMap::Payload`, **not sizeof(Map)**; lock version-1 lengths | All bodies and loadable sections identical |

`sizeof(DatabaseMap::Map)` is **260**, because it includes the epoch. Its wire
payload is **256**. Both the plain and group PRE-written AOF fixtures replay on
POST and restore every mapping byte. The epoch poison never enters the payload.
Snapshot normal/uring writers and loader use the same payload size.

The final default PRE/POST proof is **1492/1492 hot and 17078/17078 full emitted
bodies**, zero changed bodies. All loadable section contents, addresses, sizes
and alignments match except the build-ID note. Debug ELF hashes differ. The full
checker additionally selects four executor run bodies (1496/1496). Receipts are
under `docs/deadswitch/final-*`; candidate receipts are numbered `01` through `08`.

All eight locked sizes and all named field offsets match in both namespaces:
Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144, Config 624. No Makefile/compiler-budget override changed.
Tests/tools name, literal and encoded-spelling grep receipts are committed.

## Arms

All paths are relative to this worktree; exact hashes are in
`docs/deadswitch/binaries.sha256`.

| Arm | Path | Purpose |
|---|---|---|
| PRE | `build/deadswitch/pre/tomokv` | Frozen merged base |
| POST | `build/deadswitch/post/tomokv` | Fresh final default build |
| AOF-1 | `build/deadswitch/aof-1/tomokv` | PRE with only writer constant = 1 |
| AOF-4096 | `build/deadswitch/aof-4096/tomokv` | PRE with only writer constant = 4096 |
| TTL-inline | `build/deadswitch/ttl-inline/tomokv` | Final source, default selector 0 |
| TTL-sidecar | `build/deadswitch/ttl-sidecar/tomokv` | Same source, selector 1 |
| TTL-PAD-B | `build/deadswitch/ttl-pad-b/tomokv` | **B inverse control:** sidecar behavior + padding restoring inline text size |

TTL `.text`: inline 7,845,285 B; sidecar 7,817,411 B; PAD-B 7,845,285 B.
PAD-B uses identical sidecar production objects, preserves all 9229 selected
sidecar text-function addresses/sizes and CET/ISA properties, and appends 27,874
unreachable NOP bytes. It controls aggregate size; it does not recreate all PRE
function placement and must not be labeled a kind-A behavior twin. None of the
default cleanup changes needs a PAD because its runtime sections are identical.

The TTL full inventory explains/indexes every delta and retains instruction and
relocation diffs in `06-changed-bodies.json.gz` and `06-body-diffs.txt.gz`.
387 deltas are explicitly compiler code-generation changes in unchanged source
bodies, not claimed neutral. The strict TTL identity tools exit 1, as expected
for changed code; their output is retained. No performance result is inferred.

## AOF correctness still requested — CPUs 112–127

The production scheduler witness queues 384 undecided GCMT chunks. Ordinary
epoll passes consume 1/16/384 in the 1/PRE/4096 arms; uring and drain-all consume
256 in every arm. Both namespaces are tested. Both runtime engines share one
emitted writer body, so “uring binary bytes identical” is not literally true:
the changed immediate is in the shared body, while uring still selects 256.

All existing serverless ack/remote/shutdown/refusal schedules pass for all three
budgets. All nine clause-deletion controls fail at their named assertions.
The PRE and 4096 frame-order suites pass. **Budget 1 fails the frame-order
arming assertion** `ready GCMT and OPEN large record coexist`; this is retained,
not suppressed or treated as a recovery pass. See `02-persistfix-schedules.json`.

Run the actual AOF jobs on PRE, AOF-1 and AOF-4096, serially on the quiet box.
The jobs include persistfix kill/term in both modes and the selected engine.
The resource plan was validated without starting the gate (`02-live-gate-plan.txt`).

```sh
cd /home/user/Projects/cx-deadswitch
mkdir -p build/deadswitch/live
for arm in pre aof-1 aof-4096; do
  GATE_ONLY_JOBS='aof-epoll aof-uring' \
    GATE_LEDGER="$PWD/build/deadswitch/live/$arm-ledger.tsv" \
    tests/gate.sh quick \
      --candidate-binary "$PWD/build/deadswitch/$arm/tomokv" \
      --server-cores 112-119 --load-cores 120-127 --load-smt '' \
      --ports 18790-18819 >"build/deadswitch/live/$arm.log" 2>&1
  printf '%s\t%s\n' "$arm" "$?" >> build/deadswitch/live/status.tsv
done
```

Preserve every arm/engine result and failure. These selected jobs are PARTIAL,
never a full gate receipt. They retain the gate's 16-shard, eight-core, ratio-3
split geometry. Before merging a common-budget change, define one
`aof-writer-batch` policy shared by both paths and the uring reserve sites, then
test that concrete change. This lane has not assumed a default or landed it.
The ordinary PRE->POST persistfix load/recovery battery is still requested in
addition to the completed serverless wire-format replay proof.

## TTL correctness and measurement request

Run `edgetime` and `hexpire` differential suites in each arm, split and armed
fused, both atomics and RESP modes. The committed seed file contains all current
permanent seeds, 7/19/20/23. The suite runner itself supplies the atomic/RESP loops.

```sh
for arm in ttl-inline ttl-sidecar ttl-pad-b; do
  for geometry in split armed-fused; do
    GATE_LOAD_CORES=120-127 GATE_DIFFER_GEOMETRY="$geometry" \
      GATE_DIFFER_PROOF_SUITES="$PWD/docs/deadswitch/06-differ-suites.txt" \
      GATE_DIFFER_PROOF_SEEDS="$PWD/docs/deadswitch/06-differ-seeds.txt" \
      GATE_DIFFER_OUT="$PWD/build/deadswitch/differ-$arm-$geometry" \
      tests/differ_gate.sh "$PWD/build/deadswitch/$arm/tomokv" \
        18790 18791 112-119 3
  done
done
```

The generic mainline **14-cell null** is m02/m03/m05/m06/m26/m27/m50/m51/m53/m54/
m74/m75/h05/h06. Exact recipes and the validated offline inventory are committed
as `06-null14-cells.txt` and `06-null14-plan.json`. Use the gate's own ABBA
instrument and reviewed 32-core 16:16 ABBA geometry; the eight-core geometry
above is correctness-only in the current calibration file.

```sh
python3 tests/abbagate.py --collect-null 1 --subset full \
  --cells docs/deadswitch/06-null14-cells.txt \
  --reference-binary build/deadswitch/ttl-inline/tomokv \
  --candidate-binary build/deadswitch/ttl-inline/tomokv --build-reference 0 \
  --server-cores 0-31 --load-cores 32-111 --load-smt '' --ports 18830-18849 \
  --output build/deadswitch/null14
# Null collection deliberately reports PARTIAL/exit 3; inspect its null-control evidence.
for arm in ttl-sidecar ttl-pad-b; do
  python3 tests/abbagate.py --subset full \
    --cells docs/deadswitch/06-null14-cells.txt \
    --reference-binary build/deadswitch/ttl-inline/tomokv \
    --candidate-binary "build/deadswitch/$arm/tomokv" --build-reference 0 \
    --null-result build/deadswitch/null14/results.json \
    --server-cores 0-31 --load-cores 32-111 --load-smt '' --ports 18830-18849 \
    --output "build/deadswitch/abba-$arm"
done
```

Use matched offered load and the frozen null-derived per-cell bands. Report
rate, cycles/op, instructions/op, IPC, p99 and p99.9 for PRE, POST and PAD-B;
`cycles/op = instructions/op / IPC`. Retain individual rounds and failures.
No averaging away a losing cell, widening a band, or claiming gain from
instruction count alone. Compare POST with PAD-B as well as each with PRE.

**No expiry performance d-cell exists in either requested inventory.**
`wb_rule_cells.txt` has `d128g_l0`, plain GET p128 with no expiry setup;
`headline_cells.txt` has no expiry d-cell. The differential suites are correctness
traffic, not TTL rate evidence. Mainline must supply an explicit TTL-heavy rate
recipe and prove that expiry/deadline traffic fired before deciding the bake-off.
The selector remains an experiment until correctness, generic null, TTL-heavy
rate/tail evidence, and the control comparisons support a keep/delete decision.

## Gate accounting and handoff

Rows **+0 quick / +0 full**. `tests/gate.sh` is unchanged, including
`EXPECT_QUICK=502` and `EXPECT_FULL=519`; no new call exists on either side of its
quick-tier exit. Witnesses here are offline/serverless artifacts, not new gate
rows. Run the maintainer's full iteration gate before merge. Append measurement
results to `MEASURE-RESULT` with arm hashes and retain failed rows.

Remaining requested work is explicit: live AOF/persistfix recovery, the shared
AOF budget policy/change, TTL differential/performance/control measurements,
and the owner's gate. No part of that list is reported as passed.
