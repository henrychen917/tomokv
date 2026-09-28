execfix — atomic-0 MSETNX checks an obsolete snapshot after FLUSHALL

Branch/worktree: `cx-execfix`, `/home/user/Projects/cx-execfix`, based on `eaebd00ef`.
Production fix: `612fb9546`; initial reproducer: `ddb17b6b3`; expanded controls: `1148341da`.
Status: committed fix and serverless reproduction complete; live recurrence, boot checks and
throughput verdict remain PENDING mainline. No server, benchmark or gate was run, and nothing
was pushed. Builds and unit processes were confined to cores 112–127; builds used `make -j16`.

The supplied log at
`/home/user/Projects/cx-signalacct/build/gate-run.QzyqjP/jobs/debug-0/gate-execfix-0.txt`
contains `('MSETNX', 0, [1])`. The maintainer reports one failure in three tracked observations.
The tuple means the **bare** operation incorrectly returned zero; EXEC returned the expected one.
Both arms start empty. The battery has no concurrent writer in this arm.

`tests/execfix.py:438` defines the breadth sequence, with MSET immediately before MSETNX.
`tests/execfix.py:466` flushes and waits for each reply before continuing. In particular the
preceding wrapped MSET can leave committed MVCC records when FLUSHALL runs. The existing helper
proves distinct shards, despite its name/comment saying distinct owners. The new serverless
fixture explicitly proves both distinct shards and distinct routed executors.

Reproduction and limits

`tests/execfix_unit.cc` includes the production xshard/MULTI implementation and links the other
release objects. It initializes 16 shards and eight logical workers, opens no socket or io_uring,
and starts no server loop. Split uses six IO plus two EX; fused uses eight owners. The final
fixture selects the first eight permitted CPUs (112–119 under the required outer affinity).
The early PRE runs used `even_ifid=6`, `even_ex=2` within 112–127 instead of explicit placement.
Both compiled database runtimes are tested; `execfix-unit-db0` is the default databases=1 variant.

Every round executes the battery's MSET setup and its full bare-versus-wrapped MSETNX pair:

```text
FLUSHALL; MSET a 1 b 2
FLUSHALL; MULTI; MSET a 1 b 2; EXEC
FLUSHALL; MSETNX a 1 b 2
FLUSHALL; MULTI; MSETNX a 1 b 2; EXEC
```

Shard order and transaction retry order are shuffled reproducibly. `serial` alternates retaining
and cleaning the preceding transaction's records. `parallel` additionally runs FLUSHALL shards
on their two respective owners concurrently. `window` retains records and holds one real
`Server::atomic_commit_reserve()` / `atomic_commit_publish()` bracket across the NX pair, delaying
the safe watermark without introducing a writer on either key. Each round checks that the window
opened; both FLUSHALLs must acknowledge while the watermark trails the drawn sequence. It also
checks the actual stored values, then publishes and reclaims before starting fresh state.

| Arm / schedule | Atomic | Discrepancies / trials | Interpretation |
| --- | --- | --- | --- |
| Unmodified PRE, serial, split | 0 | 0 / 1,000 | No delayed publication |
| Unmodified PRE, parallel FLUSHALL, split | 0 | 0 / 10,000 | Unforced timing did not reproduce |
| Unmodified PRE, directed window, split | 0 | 1,000 / 1,000 (100%) | Exact `0` versus `[1]` discrepancy |
| POST, directed window, each of 1s/2s × db0/multi | 0 | 0 / 1,000 each | 0 / 4,000 total; 2,000 lagging flushes per configuration |
| Fix removed, final fixture, each of 1s/2s | 0 | 1,000 / 1,000 each | Negative exits 1 with the exact discrepancy |
| Unmodified PRE, serial / parallel, split | 1 | 0 / 1,000; 0 / 10,000 | Unforced atomic-1 controls |
| PRE, directed window, split | 1 | 1,000 / 1,000 | Existing broader stale-cut defect |
| POST, directed window, each of 1s/2s × db0/multi | 1 | 1,000 / 1,000 each | Same existing defect, deliberately unchanged |

These are reproduction frequencies in controlled correctness trials, not throughput measurements.
**The 100% rate is conditional on a deliberately held publication window.** There is no measured
live recurrence rate from this lane. The historical log has no cutoff/ticket trace, so it cannot
prove which publication interleaving produced that particular failure. The directed test proves
a sufficient production-code mechanism for the exact discrepancy; the unforced 10,000-run
attempt did not establish the historical trigger.

Evidence: `build/execfix-pre-{serial,parallel,window}-{0,1}.log`,
`build/execfix-post-results.json`, `build/execfix-post-execfix-unit*.log`, and
`build/execfix-nofix-{1s,2s}-0-window.log`. No failure was counted as a passing correctness case:
atomic-1 window runs retain exit 1 and are recorded as known unchanged failures.

Mechanism and scope

1. `src/cmd/scatter_engine.inc:1514` distinguishes enabled atomic writes from residual MVCC
   tracking. An earlier EXEC leaves tracking active even under atomic 0. Before the fix,
   `needs_snapshot` consequently registered a finite cutoff for ordinary MSETNX.
2. `src/store/flatstore_atomic.inc:708` implements FLUSHALL over recorded keys by installing
   tombstones, with origin connection zero (`:720`) and a committed ticket (`:742`). The
   physical clear then leaves older protected versions in the chain.
3. `src/core/server.h:2717` publishes a conservative safe watermark. A committer that is not
   last leaves that watermark unchanged. There is also an allowed overlap without a surviving
   in-flight committer: A samples `drawn`; B reserves, installs and decrements while A is still
   counted; A decrements last and publishes its earlier sample. The resulting cutoff can lag
   B's acknowledged write. This interleaving follows from the code; it was not captured in the
   historical log or observed in the unforced unit trials.
4. `src/cmd/scatter_engine.inc:2727` binds the bare probe to that cutoff. The resolver at
   `src/store/flatstore_atomic.inc:1107` permits own-connection versions past the cutoff, but
   FLUSH's origin-zero tombstones do not receive that exception. It can therefore return the
   preceding EXEC's old value from an otherwise empty keyspace.
5. The NX probe at `src/cmd/scatter_engine.inc:3384` records each shard's existence result;
   `src/cmd/xshard_commands.inc:1274` combines **all** probes before scheduling any SET.
   The incorrect zero comes from a stale existence result, not an independent per-shard NX
   reply or a writer racing between the check and SET in this battery. The atomic-0 two-wave
   protocol's ordinary exposure to concurrent writers is outside this fix.
6. EXEC takes a different path: `src/cmd/multi.inc:1193` explicitly uses `UINT64_MAX` for
   MSETNX writes, `:1247` checks existence, and `:1393` advances from checks to installs only
   after all participants arrive. It sees the tombstones and returns `[1]`.

The seed-19 predecessor-order check at `src/core/ex_loop.h:2507` and undecided-predecessor
admission at `src/cmd/atomics_glue.inc:648` remain intact. This reproduction completes and
acknowledges every preceding operation; it needs no child overtaking a parked predecessor.

The only production edit is `src/cmd/scatter_engine.inc:1874`: omit the read-snapshot
registration for `Kind::Msetnx && !atomic_write`. Both its probe and its phase-two plain-version
preparation retain `UINT64_MAX`, matching EXEC's latest-committed write semantics. This also
avoids allocating a snapshot registration for that path. Atomic-enabled, forced-atomic and
script-guarded atomic writes keep their existing cutoff and install/abort behavior.

No writeback, reorder, LB, owner transfer, data structure layout, reader retry or overwrite
policy changed. The eight specified layout assertions passed in the release build. PRE `.text`
is 7,577,217 bytes; POST is 7,577,489 (+272). No data-layout change or PAD arm is proposed.

Outstanding correctness finding: **atomic-1 bare MSETNX also returns a stale NX failure in the
directed publication window**, whereas EXEC succeeds. This violates the same acknowledged
FLUSHALL ordering expectation. Requirement (4) forbids changing atomic-1 behavior, so this lane
leaves it unchanged and reports it for a separate mainline decision. A general finite-cut
read after an acknowledged origin-zero tombstone warrants the same audit; that broader surface
was not changed or claimed fixed here.

Controls and build commands

The final fixture's `controls` schedule checks successful writes, duplicate-key last-value wins,
NX rejection with both keys present, rejection with a blocker on either shard and no partial
write to its absent peer, same-shard controls, and MSET overwrite controls. All run bare and
inside EXEC. Each of 1s/2s × atomic 0/1 × db0/multi passed 2,000 cases (16,000 total).
The final serial schedule passed 1,000 rounds per configuration. No live boot is implied by
these in-memory thread-mode fixtures.

```bash
taskset -c 112-127 make -j16
taskset -c 112-127 make -j16 -f Makefile -f tests/execfix.mk \
  build/execfix-unit build/execfix-unit-db0
taskset -c 112-127 ./build/execfix-unit-db0 0 1000 window 2s
taskset -c 112-127 ./build/execfix-unit-db0 0 1000 window 1s
taskset -c 112-127 ./build/execfix-unit-db0 1 100 controls 2s
```

The negative is a separate source copy under `build/execfix-nofix`; no switch enters production.
To recreate exactly the tested removal and run the same final fixture:

```bash
python3 - <<'PY'
from pathlib import Path
import shutil
root = Path('build/execfix-nofix')
shutil.copytree('src', root / 'src', dirs_exist_ok=True)
p = root / 'src/cmd/scatter_engine.inc'
s = p.read_text()
needle = '!(atomic_write && kind == Kind::Mset) && !latest_msetnx);'
assert s.count(needle) == 1
s = s.replace(needle, '!(atomic_write && kind == Kind::Mset));')
start = s.index('    // Atomic-OFF MSETNX is a conditional writer,')
end = s.index('    const bool needs_snapshot', start)
p.write_text(s[:start] + s[end:])
PY
taskset -c 112-127 make -j16 -f Makefile -f tests/execfix.mk \
  EXECFIX_SOURCE=build/execfix-nofix EXECFIX_UNIT=build/execfix-unit-nofix \
  build/execfix-unit-nofix
taskset -c 112-127 ./build/execfix-unit-nofix 0 1000 window 2s
```

Expected negative result: exit 1, `discrepancies=1000 wrong=1000 lagging_flushes=2000`, with
`bare=:0` and `wrapped=*1 :1`. If the publication window never opens, the fixture fails its
explicit watermark assertion instead of skipping the trial.

Artifacts (release builds, never executed as servers)

| Artifact | SHA-256 |
| --- | --- |
| `build/tomokv` — POST | `616cb6c2cc072f605010cce3ef5fbf163522034675df4cc67eed3940467907e0` |
| `build/tomokv-execfix-pre` — local eaebd00ef PRE | `177491ac79a46fa58cd442489ea92b3742814bf4f505624204e9816236fe499b` |
| `/home/user/Projects/bench-bins/tomokv-headline-eaebd00ef` — requested reference | `bcdb204fc6e2d09eb0caa041fd110973a33d90fcc244d67c5d756e97d1bfee3a` |

The local PRE is a separate build, not a byte-identical claim about the headline artifact.
Build logs: `build/execfix-pre-build.log`, `build/execfix-post-build.log`,
`build/execfix-unit-final-build.log`, `build/execfix-nofix-build.log` (no compiler warnings).

Mainline correctness request — NOT RUN

Run the unchanged execfix battery ten times from each atomic boot mode, using fresh boots to
vary the hash seed. **Geometry: cores 0–7, 16 shards, split 6 IO + 2 EX, ratio `6:2`, DEBUG
enabled**, with the gate's remaining defaults. The battery flips CONFIG atomic itself, so every
run also exercises both runtime atomic settings. Require 20/20 battery invocations to pass;
keep every transcript. The exact per-boot commands are:

```bash
# Mainline only; run this block for AT=0 and AT=1, RUN=1 through 10, sequentially.
AT=0 RUN=1
mkdir -p build/execfix-mainline
EXECFIX_DIR=$(mktemp -d "$PWD/build/execfix-mainline/data-$AT-$RUN.XXXXXX")
taskset -c 0-7 "$PWD/build/tomokv" \
  --port 16743 --bind 127.0.0.1 --shards 16 --ratio 6:2 \
  --dir "$EXECFIX_DIR" --atomic "$AT" --enable-debug-command yes \
  > "build/execfix-mainline/server-$AT-$RUN.log" 2>&1 &
EXECFIX_PID=$!
EXECFIX_READY=0
for _ in $(seq 150); do
  kill -0 "$EXECFIX_PID" 2>/dev/null || break
  if (exec 3<>/dev/tcp/127.0.0.1/16743) 2>/dev/null; then EXECFIX_READY=1; break; fi
  sleep 0.2
done
if test "$EXECFIX_READY" -ne 1; then
  kill -TERM "$EXECFIX_PID" 2>/dev/null || true
  wait "$EXECFIX_PID" || true
  exit 1
fi
taskset -c 8-15 python3 tests/execfix.py 127.0.0.1 16743 \
  > "build/execfix-mainline/battery-$AT-$RUN.log" 2>&1
EXECFIX_RC=$?
kill -TERM "$EXECFIX_PID"
wait "$EXECFIX_PID"
test "$EXECFIX_RC" -eq 0
```

Also boot the ordinary fused control on cores 0–7 (`--thread-mode fused`, **omit `--ratio`**)
and run execfix in both atomic boot modes, then run the maintainer's usual iteration gate.
No new gate row is registered: delta **0 quick / 0 full**, constants remain **441 / 459**.
The existing execfix row is emitted at `tests/gate.sh:1636`, its debug jobs are collected at
`:2763`, and the quick exit is at `:2842`; it remains before that exit.

Mainline throughput request — NOT RUN

Use `tests/execfix_cells.txt` (validated with `abbagate.py --list-cells`: eight cells): MSETNX
and MSET, p8, eight independently generated keys, 64-byte values, 512 total connections,
1s/2s × atomic 0/1, read-local/overlap/reorder all zero. MSETNX is the instrument's populated-key
rejection control, expected reply zero; it does not measure successful NX insertion. MSET
controls the adjacent write path and atomic 1 controls the unchanged protocol.

Use the gate instrument's reviewed **32-core ABBA geometry** here: server cores 0–31, load
cores 32–111, no SMT, split 16:16; this is distinct from the eight-core correctness geometry.
The checked-in instrument has no reviewed eight-core ABBA ratio. New cells have no load pins;
let the instrument search and prove saturation, retaining its per-arm occupancy checks.
Reference A must be the explicit eaebd00ef headline binary above (the worktree's measurement
JSON still points at an older reference).

```bash
# Mainline only, quiet box. First collect the identical-binary standing null.
python3 tests/abbagate.py --cells tests/execfix_cells.txt --subset full \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --ports 16744-16744 --port 16744 --build-reference 0 \
  --candidate-binary /home/user/Projects/bench-bins/tomokv-headline-eaebd00ef \
  --collect-null 1 --output build/execfix-mainline/null

# After the null's internal verdict passes (the outer diagnostic exits PARTIAL/3):
python3 tests/abbagate.py --cells tests/execfix_cells.txt --subset full \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --ports 16744-16744 --port 16744 --build-reference 0 \
  --candidate-binary "$PWD/build/tomokv" \
  --reference-binary /home/user/Projects/bench-bins/tomokv-headline-eaebd00ef \
  --null-result build/execfix-mainline/null/results.json \
  --output build/execfix-mainline/comparison
```

Decision: all eight cells must pass the instrument's matched-null and paired-rate comparison.
Report each cell's A/B rate, cycles/op, instructions/op, IPC, and both arm spreads; no averaged
win can hide a losing cell. More than 2% same-arm spread invalidates a measurement. Rate at
matched offered load is the verdict; instruction count and IPC explain it. No performance gain
or zero-regression claim is made before those results exist.

| PRE versus POST | PRE | POST | Verdict |
| --- | --- | --- | --- |
| Directed atomic-0 correctness | 100% discrepancy | 0% discrepancy | Serverless fix/control demonstrated |
| MSETNX p8, each requested cell | Pending | Pending | Mainline |
| MSET p8, each requested cell | Pending | Pending | Mainline |
| Live execfix x10 per atomic boot / iteration gate | Existing intermittent failure | Pending | Mainline |

Append the mainline observations to `MEASURE-RESULT` and retain raw JSON/transcripts. This lane
stops with this report; the maintainer tests, gates and merges.
