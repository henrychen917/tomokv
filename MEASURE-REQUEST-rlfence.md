# RL1 — release the MGET parse fence at local completion

2026-10-03. Worktree `/home/user/Projects/cx-rlfence`, branch `cx-rlfence`.
Launch HEAD: `e279aeb4cf08ae2c39f26be679388b872fed4667`.
Ran `git fetch origin cpp && git merge --no-edit origin/cpp` first: already up to date.

The production change is one added statement in `src/net/rob.h`. Both release builds and
the serverless proofs pass. The actual old implementation, and a throwaway source copy with
only this statement reverted, fail the designated assertions. **No server, live battery,
benchmark or gate was run. Live results and performance remain for mainline.**

Implementation commits: `3d30b7fe8` (witnesses), `3410415b9` (fix and gate rows),
`7ccc6ea30` (live-harness controls). Nothing was pushed.

## Diagnosis and symmetry audit

This confirms RL1 in `/home/user/Projects/round3-read/read-local.md`, section C, and
`/home/user/Projects/round3-read/REGISTER.md`.

| Site / anchor in this branch | Contract and finding |
| --- | --- |
| `src/net/rob.h:319` | Arming a second outstanding MGET fence still aborts. |
| `src/net/rob.h:324` | The old fallback clear depended on `flush_id()` passing the fenced id. Completion alone did not satisfy it. |
| `src/net/rob.h:365` | Chunk completion retired the pending bits/filter but omitted the fence clear. Added `if (bits & read_local_slot_bit(local_mget_fence_id_)) local_mget_fence_id_ = UINT64_MAX;`. |
| `src/net/rob.h:400` | Per-op local completion already retires its pending bit/filter, then clears only its matching fence. |
| `src/net/rob.h:407` | Owner publication already retires its pending bit/filter, installs the owner bit, then clears only its matching fence. |
| `src/net/rob.h:890` | The per-op helper compares the complete id. The mask form uses slot membership; active ids are distinct modulo the ROB window. An unrelated or empty mask cannot release a live fence. With no fence, the sentinel remains unchanged, including a mask containing bit 63. |
| `src/core/ex_loop.h:1558` | The production lane completes through the chunk method, before publishing Done and adding the `mget_local_hits` count. |
| `src/core/io_loop.h:2988`, `src/core/reorder.cc:2205` | Both parser variants stop while the fence is pending. Both benefit from the shared ROB fix. |
| `src/core/ex_loop.h:2952` | Existing `DEBUG ATOMIC-COMMIT-HOLD` retains the commit queue without blocking the executor. The live witness uses it without a new production hook. |

The three completion paths now agree on releasing a covered fence immediately and retaining an
uncovered fence. Only owner publication adds owner slots. Pending-filter clear-on-empty, reply
retirement, write descriptors, reader retry behavior and the one-fence arming guard are unchanged.

No layout change. Both release variants compiled all existing locks:
`Op 336 / Client 1984 / ThreadCtx 1408 / Shard 1440 / FlatStore 944 / Rob<64> 192 /
AtomicEntry 144 / Config 624`. No knob was added or changed. No changes to `io_loop.h`, `wb.h`
or `reorder.cc`; the conditional writeback-clause witness requirement does not apply.

## Directed proof and recorded output

`tests/rlfence_unit.cc:55` tests all three production ROB methods over 128 starting positions:
two slot generations, bit 63, wraparound, partial/mixed/empty masks, immediate rearming, pending
filter cleanup and owner-map differences. `tests/rlfence_unit.cc:102` withholds retirement behind
an unfinished precise write and drives 8 and 32 disjoint logical MGET completions through the
real ROB. The same-key RYOW hazard must remain throughout and disappear only on retirement.
This is a ROB proof; it does not claim to execute the live MGET handler or sample INFO.

Commands run, all on cores 112–127:

```sh
taskset -c 112-127 make -j16                         # PRE, before changing production source
cp build/tomokv build/tomokv-rlfence-pre
taskset -c 112-127 make -j16 build/rlfence-unit       # witness on old source: expected failure
taskset -c 112-127 build/rlfence-unit
taskset -c 112-127 build/rlfence-unit pipeline

# After the one-line fix:
taskset -c 112-127 make -j16 build/rlfence-unit build/read-local-write-ring-unit build/tomokv
cp build/tomokv build/tomokv-rlfence-post
taskset -c 112-127 build/rlfence-unit
taskset -c 112-127 build/read-local-write-ring-unit
```

PRE / reverted-copy results, each command exiting 1:

```text
FAIL rlfence: all three completion sites clear the covered MGET fence before retirement

FAIL rlfence: N MGETs complete locally before any ROB retirement
rlfence pipeline N=8 lane_completions=1 retired=0
```

POST, exit 0:

```text
PASS rlfence symmetry (3 sites, 128 slot positions, partial/mixed/empty masks)
rlfence pipeline N=8 lane_completions=8 retired=0
rlfence pipeline N=32 lane_completions=32 retired=0
PASS rlfence (completion symmetry, pipelined MGET, RYOW, Rob<64>=192)
```

The existing write-ring suite also passed, including all four 200k-frame soaks
(shallow precise, full-window precise, conservative, initially unarmed).

Reproduce the **throwaway negative control** without editing the working production header:

```sh
taskset -c 112-127 python3 - <<'PY'
from pathlib import Path
import shutil
root = Path('build/rlfence-old')
root.mkdir(exist_ok=True)
shutil.copytree('src', root / 'src', dirs_exist_ok=True)
(root / 'tests').mkdir(exist_ok=True)
shutil.copy2('tests/rlfence_unit.cc', root / 'tests/rlfence_unit.cc')
shutil.copy2('Makefile', root / 'Makefile')
header = root / 'src/net/rob.h'
text = header.read_text()
fix = '        if (bits & read_local_slot_bit(local_mget_fence_id_)) local_mget_fence_id_ = UINT64_MAX;\n'
assert text.count(fix) == 1
header.write_text(text.replace(fix, ''))
PY
taskset -c 112-127 make -j16 -C build/rlfence-old build/rlfence-unit
taskset -c 112-127 build/rlfence-old/build/rlfence-unit          # exit 1: symmetry assertion
taskset -c 112-127 build/rlfence-old/build/rlfence-unit pipeline # exit 1: 1 completion, want 8
```

This copy builds only the serverless unit, never a running server. Recorded logs are
`build/rlfence-{pre,post}-build.log`, `build/rlfence-{pre,post}-unit.log`,
`build/rlfence-pre-pipeline.log`, `build/rlfence-negative-{unit,pipeline}.log`,
`build/rlfence-old-build.log`, and `build/rlfence-write-ring.log`.

## Live witness and its serverless harness checks

`tests/read_local_lane.py:94` adds `HOST PORT --mget-fence`, reusing the existing RESP client,
counter parser, reporting and deadline machinery. It proves the connection arms on a local
MGET, then sends one held cross-owner MSET, N disjoint MGETs, and a conflicting trailing MGET
in one socket write. DEBUG geometry selects two untouched read shards and two write owners.

While the commit latch remains armed, INFO must show an in-flight atomic group, exactly N
`read_local_mget_local_hits`, and exactly one MGET fallback attributed to the older same-key
write. The socket must have no reply available: the unfinished head prevents ROB retirement.
After releasing the latch, every reply must match, including alternating MGET key order,
duplicate keys and the trailing read of both newly written values. Reader retries stay zero.
It exercises p8 and p32. A missing window re-arms on fresh connection/write state at most three
times and then fails; an entered window with the wrong result fails immediately.

**A final N-hit total after receiving every reply would pass old code too.** This test samples
the count while retirement is blocked. Expected live PRE is one hit before release; expected
POST is N. These live expectations have not been run by this lane.

The same Python function was run without sockets against synthetic traces:

```sh
taskset -c 112-127 python3 tests/read_local_lane.py --self-test mget-fence
taskset -c 112-127 python3 tests/read_local_lane.py --self-test mget-fence-old
taskset -c 112-127 python3 tests/read_local_lane.py --self-test mget-fence-unarmed
taskset -c 112-127 python3 tests/read_local_lane.py --self-test mget-fence-stale
```

| Trace | Observed result |
| --- | --- |
| `mget-fence` | Exit 0; p8 hits=8 and p32 hits=32, one RYOW demotion each; `PASS (checks=2 skips=0)`. |
| `mget-fence-old` | Exit 1 at `RL1: N MGET lane hits before ROB retirement: got 1, want 8`. This trace reaches N on release, so it detects an incorrectly delayed observation. |
| `mget-fence-unarmed` | Exit 1 at `MGET fence window never opened after 3 fresh arms (p8)`. |
| `mget-fence-stale` | Exit 1 at `MGET pipeline replies/order/RYOW:`. |

Every trace checks latch release and connection cleanup. Logs are
`build/rlfence-harness-positive.log` and `build/rlfence-harness-mget-fence-{old,unarmed,stale}.log`.
These synthetic traces validate the harness, not server scheduling. The production-code
negative control is the reverted C++ unit above.

Also passed: existing `--self-test transient` and `--self-test delayed-drain`,
`taskset -c 112-127 bash -n tests/gate.sh`, Python byte compilation, and `git diff --check`.

## Mainline live commands — not executed here

Run on the scheduled quiet box from this worktree. This uses the gate geometry: server cores
0–7, 16 shards, split ratio 6:2, one database, separate client cores 8–9. Each arm gets an empty
persistence directory. The function accepts overlap/reorder to cover both parser variants.
Use an unused port 16389.

```bash
cd /home/user/Projects/cx-rlfence
rlfence_live() (
  set -eu
  arm=$1 mode=$2 overlap=$3 reorder=$4
  port=16389
  args=(--thread-mode "$mode" --overlap "$overlap" --reorder "$reorder")
  if [ "$mode" = 2s ]; then args+=(--ratio 6:2); fi
  run_dir=$(mktemp -d "$PWD/build/rlfence-live-$arm-$mode-$overlap-$reorder.XXXXXX")
  taskset -c 0-7 "$PWD/build/tomokv-rlfence-$arm" \
    --bind 127.0.0.1 --port "$port" --shards 16 --databases 1 \
    --read-local 1 --atomic 1 --enable-debug-command yes --maxmemory 0 \
    --dir "$run_dir" --save '' "${args[@]}" >"$run_dir/server.log" 2>&1 &
  srv_pid=$!
  trap 'kill -TERM "$srv_pid" 2>/dev/null || true; wait "$srv_pid" || true' EXIT
  taskset -c 8-9 python3 - "$port" <<'PY'
import socket, sys, time
deadline = time.monotonic() + 30
while True:
    try:
        with socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=0.2):
            break
    except OSError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(0.1)
PY
  rc=0
  taskset -c 8-9 python3 tests/read_local_lane.py 127.0.0.1 "$port" --mget-fence \
    >"$run_dir/proof.log" 2>&1 || rc=$?
  cat "$run_dir/proof.log"
  if [ "$arm" = pre ]; then
    test "$rc" -eq 1
    grep -Fq 'RL1: N MGET lane hits before ROB retirement: got 1, want 8' "$run_dir/proof.log"
  else
    test "$rc" -eq 0
  fi
)
for mode in 1s 2s; do
  for overlap in 0 1; do
    for reorder in 0 1; do
      for arm in pre post; do
        rlfence_live "$arm" "$mode" "$overlap" "$reorder" || exit 1
      done
    done
  done
done
```

## Gate rows and counts

No existing defect-specific row covered MGET completion fences. Added three rows:

| New row | Definition line | Collection line |
| --- | --- | --- |
| read-local MGET fence symmetry unit (also runs Python positive harness replay) | `tests/gate.sh:1241` | `collect_job ring_unit`, line 2766 |
| read-local MGET fence battery (1s), existing B+ armed boot | `tests/gate.sh:1601` | `collect_job bplus`, line 2821 |
| read-local MGET fence battery (2s), new armed split boot | `tests/gate.sh:1607` | `collect_job bplus`, line 2821 |

Both collection sites are **before** the quick-tier exit at line **2902**. Therefore the delta
is **+3 quick / +3 full**, making the expected healthy counts **449 / 466** from **446 / 463**.
`EXPECT_QUICK` and `EXPECT_FULL` at lines 261–262 are untouched. Mainline must update those
counts before expecting the expanded gate's row-count check to pass.

After that maintainer-owned count update, the mainline gate command is:

```sh
tests/gate.sh iteration \
  --reference-binary "$PWD/build/tomokv-rlfence-pre" \
  --candidate-binary "$PWD/build/tomokv-rlfence-post"
```

## PRE / POST artifacts and measurement request

| Artifact | PRE | POST |
| --- | --- | --- |
| Binary | `build/tomokv-rlfence-pre` | `build/tomokv-rlfence-post` |
| SHA-256 | `8f0f3add5043003f6b6bfbe16a69c9e3edf7bc8c50be49caa7e28d05dbb15c26` | `933e6857b8529adc195f7b8fe4e09223f2b3855881726ae7e175e943998ae155` |
| ELF `.text` bytes | 7,554,449 | 7,554,209 (−240) |
| GNU `size` text / data / bss | 8,544,637 / 89,560 / 1,146,424 | 8,544,425 / 89,560 / 1,146,424 |
| ROB p8 logical completions with no retirement | 1 (fails) | 8 (passes) |
| ROB p32 logical completions with no retirement | Not reached after p8 failure | 32 (passes) |
| Live INFO witness / throughput | Pending mainline | Pending mainline |

No PAD arm: no data-layout change, and `.text` changes by only 240 bytes. No performance gain
or zero-regression claim is made from instruction count, binary size or the serverless result.

Use the gate's ABBA instrument for these existing cells, all with overlap/reorder 0 and 512
connections: MGET p8/p32 in both modes with read-local 0/1 (8 cells), and GET/SET p1/p32 in
both modes with read-local 0/1 (16 regression cells). This is a diagnostic subset, not a full
release result. Exact command, after the live proof and with no other measuring lane running:

```sh
python3 tests/abbagate.py --subset full --build-reference 0 \
  --reference-binary "$PWD/build/tomokv-rlfence-pre" \
  --candidate-binary "$PWD/build/tomokv-rlfence-post" \
  --server-cores 0-7 --server-smt '' --load-cores 8-111 --load-smt '' \
  --only h01,h02,h09,h10,h17,h18,h25,h26,h33,h34,h41,h42,h49,h50,h57,h58,m02,m03,m26,m27,m50,m51,m74,m75 \
  --output "$PWD/build/rlfence-abba.json"
```

The correctness verdict is exact N local completions before retirement, intact replies and
RYOW, plus the old-code failure at the named assertion. The performance verdict is PRE/POST
rate at matched offered load using the gate's comparison; cycles/op, IPC and instructions/op
explain it. Main commands must have no regression. Record live/ABBA results in `MEASURE-RESULT`.

## Diff from launch HEAD

`git diff e279aeb4cf08ae2c39f26be679388b872fed4667 --stat` (including this report):

```text
 MEASURE-REQUEST-rlfence.md | 283 +++++++++++++++++++++++++++++++++++++++++++++
 Makefile                   |   6 +-
 src/net/rob.h              |   1 +
 tests/gate.sh              |  25 ++++
 tests/read_local_lane.py   | 236 ++++++++++++++++++++++++++++++++++++-
 tests/rlfence_unit.cc      | 145 +++++++++++++++++++++++
 6 files changed, 693 insertions(+), 3 deletions(-)
```
