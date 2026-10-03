# splitlocal — WB4/IO5 and IO1

**WB4 is overstated in the audit: the L4 prebuild does not run in either 2s schedule.**
The compile-time gate is a performance policy, not a read-local correctness guard.
Forwarding `SplitLocal` removes the overlap-0 dead test and its inert failure cleanup.
The parked epoll callback now uses the same `Fused` argument as ordinary polling.
No runtime corruption or speedup is claimed. Live checks, measurements, gate and merge
remain mainline-owned.

Worktree/branch: `/home/user/Projects/cx-splitlocal`, `cx-splitlocal`.
Launch HEAD **e279aeb4cf08ae2c39f26be679388b872fed4667**. Required first
`git fetch origin cpp && git merge --no-edit origin/cpp` completed, already up to date.
Read `/home/user/Projects/cx-iopark/MEASURE-REQUEST-iopark.md` before changing code.
Implementation/gate/unit commit: `af6aa048e`; counter/PAD tools: `e3e116c19`.
No server, load generator, benchmark, gate or push was run. Production builds and
serverless checks were pinned to CPUs 112–127; compilation used `make -j16`.

## Diagnosis and bounded change

| Evidence in the launch/current source | Consequence |
|---|---|
| `src/core/io_loop.h:2905–2911`: parser defaults `IoPipe=false`, `SplitLocal=false`; `Fused = SplitLocal || (BatchOps == kGenthreadIfidBatchOps && !IoPipe)` | The former two-argument overlap-0 call still selected the read-local-capable protocol through its batch size. Forwarding does not newly arm that protocol. |
| `io_loop.h:4204–4209`: `if constexpr (Fused && !SplitLocal)`, then SET/value/foreign-owner tests **and `srv_->thread_mode() == ThreadMode::Fused`** | At overlap 0, 2s previously compiled the branch but could not call `l4prebuild_prepare_set`. At overlap 1, it discarded the branch. IO5's dead-test diagnosis is correct; WB4's live-allocation divergence is not. |
| `io_loop.h:4247`; `src/cmd/l4prebuild.cc:147–150` | Failed-post discard is under the same compile-time gate. No candidate exists in 2s, so removing that paired cleanup there cannot leak a prebuilt SET. |
| `io_loop.h:4708–4722` versus `:5063–5086` | All six `flush_ready` parse sites now pass `NoBorrow, BatchOps, false, SplitLocal`. IFID overlap parsing already forwards it. TLS/plain and CLIENT PAUSE branches are all covered. |
| `src/cmd/l4prebuild.cc:126–144` | The size policy is measured placement/copy policy: strictly **greater than 512 B**, allocation is best effort, and failure retains the original owner handler. This is not the immutable-replacement/QSBR safety mechanism. |
| `l4prebuild.cc:47–59`; `src/store/kvobj.h:734–756`; merge `a327c00f0`, fix `71c7b998d` | The historical P0 was the short namespaced key's TTL replacement header: allocation used key identity while the old extended-length write used key length. The existing `kvobj_init_header` repair remains untouched. Disabling split-local prebuild was not that repair. |
| `io_loop.h:612` / `:741`; `src/exec/op.h:358` | IO1 now passes `Fused` at both normal and parked epoll callbacks. The plain split park remains `false`. `Sink::code`'s per-op runtime flag still prevents incompatible coded replies. |
| `io_loop.h:2425–2427` | Callback immediate parsing is confined to `Pipeline == 0`. The task's ruling and shelved iopark evidence do not establish a reachable TLS parse-inside-adoption window. No new live IO1 effect is asserted. |

IO1 decision: align the two admission paths. There is no current compile restriction
requiring `!SplitLocal`, nor an intentional admission policy distinction to preserve.
The unit checks the template invariant, including overlap 1's otherwise discarded
ordinary-poll expression; it does not claim that expression executes under overlap 1.

The production diff is seven template-argument edits in `io_loop.h`, plus its seven
generated counterparts in `reorder.cc`. The R7 source was regenerated with
`tests/r7shadow_sync.py --write`. The signal-accounting timeout negative control now
mutates the **new** parked callback spelling. No option, header allocator, ownership
transition, park timing, ordering fence, writeback policy, or object member changed.

## Serverless evidence

`tests/splitlocal_checks.py` extracts the actual parser defaults, Fused expression,
prebuild/discard guards, all six call arguments from each parse schedule, and all
three epoll poll/park arguments. A C++20 constexpr recorder evaluates those expressions.
The checks cover ordinary and generated R7 source, all supported Fused/SplitLocal
policies, TLS/plain/no-borrow and pause call sites, and 20 callback configurations per
envelope. This is a source-bound template test, not an execution of sockets or TLS.

```text
PASS splitlocal: FIFO/R7 forwarding, prebuild/discard, park policies
R7 shadow production envelopes: current
PASS negative control: old-forwarding rejected at flush_ready preserves SplitLocal and prebuild policy
PASS negative control: old-park rejected at park/hot callback Fused policy mismatch
PASS wbland clauses: 72/72 strict outcomes
PASS PAD-A: 119 retargets; 32 flush bodies; 16 park bodies
PRE/POST strict identity: 82 / 85
```

Both old-argument controls are throwaway source copies under `build/splitlocal/controls/`.
Each restores the production edit in both source envelopes and fails compilation
with exit 2 at the named static assertion in **both** `fifo` and `r7`. No deliberately
broken production binary was executed. The PAD check also rejects an omitted call
retarget at `PAD planned retarget missing`; its corrupt copy is mode 0600 and named
`missing-retarget.NEVER-RUN`.

The required writeback command passed:

```bash
taskset -c 112-127 make -j16 all build/wbland-units build/splitlocal-unit
taskset -c 112-127 python3 tests/splitlocal_checks.py check
taskset -c 112-127 python3 tests/wbland_checks.py check clauses
taskset -c 112-127 python3 tests/signalacct_source_checks.py \
  --reference . --output build/splitlocal/signalacct
```

The signalacct invocation checks the updated timeout and stale-R7 negative controls
against the **current** source. It does not claim historical PRE/POST envelope identity
across this intentional template edit. Python compilation, shell syntax, and
`git diff --check` passed. The combined production/witness build's only warning came
from the existing intentionally malformed `wbland-controls/empty` source. The
production and counter-overlay builds produced no warnings/errors.

Both production variants compiled all eight footprint assertions:
**Op 336 / Client 1984 / ThreadCtx 1408 / Shard 1440 / FlatStore 944 /
Rob<64> 192 / AtomicEntry 144 / Config 624**. The respective assertion sites are
`exec/op.h:486`, `net/conn.h:911`, `core/thread.h:1223`, `core/shard.h:532`,
`store/flatstore.h:3785`, `net/rob.h:1071`, `store/atomic_mvcc.h:71`, `core/config.h:430`.

Logs/receipts: `build/splitlocal/unit-{build,check}.log`, `controls/results.json`,
`wbland-clauses.log`, `build/wbland-clauses-proofs.json`, `signalacct/source-proof.json`,
`identity.json`, `build-command-identity.json`, and `PAD-A/{patches,parser-policy,negative}.json`.

## Arms and byte evidence

All 84 production compile commands match after normalizing only the output directory.
PRE and POST retain all objects and source archives. The only objects failing strict
executable/allocated-section/relocation/address equality are `src/core/rl2s.o` and
`db0/src/core/rl2s.o`; the linked executable also differs. The remaining **82/85**
artifacts pass. These are literal byte/layout comparisons, not masked displacements.

| Arm | Binary under `build/splitlocal/` | SHA-256 |
|---|---|---|
| PRE | `PRE/tomokv` | `7c63dbb655412bf33d398460bf4ac034c952950c61a528b763e1de019ce7406c` |
| POST | `POST/tomokv` | `c2f8beb89a735de9f652d71c2205997fcacf5a92438e916cebe3896b1ad7cc26` |
| PAD **A: behaviour twin** | `PAD-A/tomokv` | `ce753b696cd451809945ad3b03f11cf39b6ea45d4a00c9edc1abf97f308c530c` |
| Counter PRE | `LIVE-PRE/tomokv` | `b088e2947de0ab701cb8293b3a3cf3683915037b0c5e1ef2b1db501531220fad` |
| Counter POST | `LIVE-POST/tomokv` | `2c12649cb9d150819e10e96cbe94203b5d763f7ef11bd3a896db6400a576d118` |

| Linked layout | PRE | POST / PAD-A |
|---|---:|---:|
| `.text` bytes | 7,554,449 | 7,695,185 |

**Text grows 140,736 bytes.** The additional split-local parser specializations are
smaller individually but cannot replace the shared fused-policy bodies. Their four
ordinary/TLS, db0/namespaced bodies contain zero prebuild/discard references; each
retained PRE-policy body has both. `PAD-A/parser-policy.json` records those exact
symbol names, sizes, and disassembled references. No instruction or rate gain follows
from these facts alone.

PAD-A is PRE parser/admission behavior with **POST's exact text size and address
layout**, made by offline retargeting in a copy. It restores 96 parser calls in 32
split-local `flush_ready` bodies and 23 admission call edges covering all 16 parked
split-local epoll loops. One admission edge lives inside GCC's outlined epoll-accept
clone; its complete caller inventory is restricted to those parks, and its ABI is
preserved. There are no extra trampolines. Every section, symbol, file length and byte
outside the 119 call displacements remains equal to POST. No inverse PAD-B is supplied.

Reproduce offline controls without executing an arm:

```bash
taskset -c 112-127 python3 tools/splitlocal_artifacts.py pad \
  build/splitlocal/POST/tomokv build/splitlocal/PAD-A/tomokv
taskset -c 112-127 python3 tools/splitlocal_artifacts.py compare \
  build/splitlocal/PRE build/splitlocal/POST build/splitlocal/identity.json
taskset -c 112-127 python3 tests/splitlocal_live.py instrument --post build/splitlocal/POST
taskset -c 112-127 make -j16 -f build/splitlocal/live.mk \
  build/splitlocal/LIVE-PRE/tomokv build/splitlocal/LIVE-POST/tomokv
```

`build/splitlocal/SHA256SUMS` records artifacts. `build/tomokv` remains production POST.
The DEBUG counter exists **only in the two counter overlays**, at successful SET
candidate creation, with an atomic count in each database namespace. It adds no
production knob, store, allocation or object field. Use production/PAD arms for timing.

## Exact mainline live commands — NOT RUN

The counter's live command is **`DEBUG SPLITLOCAL-PREBUILDS`**. Expected deltas for
256 successful foreign-owner SETs with 1,024-byte values:

| Mode | Overlap 0 PRE / POST | Overlap 1 PRE / POST | Observed |
|---|---|---|---|
| 2s, read-local 1 | 0 / 0 | 0 / 0 | PENDING MAINLINE |
| 1s, read-local 1; positive counter control | 256 / 256 | 256 / 256 | PENDING MAINLINE |

The positive control is mandatory: an absent/non-incrementing counter must not
certify the two zeroes. The probe obtains real foreign ownership from DEBUG, disables
balancing/FLIP for the witness, checks every SET reply and same-connection GET, and
requires stable connection/shard ownership. There is no skipped arming attempt.
The old forwarding defect's negative control is the compile assertion above;
equal live zeroes cannot distinguish old from fixed forwarding.

Run this on the scheduled quiet box. It creates isolated data directories, verifies
the port is free, bounds startup, and tears down only the process it started. It runs
both transports and both database variants at **8 cores / 16 shards / split 6:2**.
The existing overlap witness supplies local-read, reply-order and RYOW coverage,
including the requested split-local epoll overlap-0 cell.

```bash
cd /home/user/Projects/cx-splitlocal
set -euo pipefail
for arm in PRE POST; do
  for databases in 1 4; do
    database=0; [ "$databases" = 1 ] || database=1
    for net in uring epoll; do
      for mode in 1s 2s; do
        for overlap in 0 1; do
          cell="$arm-db$databases-$net-$mode-ov$overlap"
          run=$(mktemp -d "$PWD/build/splitlocal/live-$cell-XXXXXX")
          taskset -c 8-15 python3 - <<'PY'
import socket
with socket.socket() as s:
    s.bind(('127.0.0.1', 18179))
PY
          taskset -c 0-7 "$PWD/build/splitlocal/LIVE-$arm/tomokv" \
            --bind 127.0.0.1 --port 18179 --thread-mode "$mode" \
            --ratio 6:2 --shards 16 --databases "$databases" --net-io "$net" \
            --read-local 1 --overlap "$overlap" --reorder 0 --atomic 1 \
            --key-lb 0 --client-lb 0 --flip-auto 0 --enable-debug-command yes \
            --save "" --appendonly no --dir "$run" >"$run/server.log" 2>&1 &
          splitlocal_pid=$!
          trap 'kill -TERM "$splitlocal_pid" 2>/dev/null || true; wait "$splitlocal_pid" || true' EXIT
          taskset -c 8-15 python3 - "$splitlocal_pid" <<'PY'
import os, sys, time
sys.path.insert(0, 'tests')
from _lib import Conn
for attempt in range(100):
    os.kill(int(sys.argv[1]), 0)
    try:
        c = Conn('127.0.0.1', 18179, timeout=0.1)
        try:
            assert c.must('PING') == b'PONG'
            break
        finally:
            c.close()
    except OSError:
        time.sleep(0.05)
else:
    raise SystemExit('FAIL: listener did not become ready')
PY
          taskset -c 8-15 python3 tests/splitlocal_live.py probe \
            127.0.0.1 18179 "$mode" "$overlap" "$database" "$run/counter.json"
          taskset -c 8-15 python3 tests/overlap.py \
            127.0.0.1 18179 "$mode" "$overlap" 1 0
          kill -TERM "$splitlocal_pid"
          wait "$splitlocal_pid"
          trap - EXIT
        done
      done
    done
  done
done
```

Repeat correctness under `--reorder 1` with the final overlap.py argument changed
to `1`. The normal gate's TLS, multi-DB, read-local and writeback witnesses remain
required. There is no new natural TLS-adoption reproduction claim; IO1 retains the
shelved lane's no-live-effect limitation.

## Measurement request and gate accounting

Use the gate's validated ABBA instrument, independently frozen offered load and
resolution, and the same eight-core/16-shard/6:2 geometry first. The stock runner
currently records ABBA placement only for 32 cores and derives shard count from
role count (`tests/abbagate.py:1445–1449`); its unmodified 1s eight-core boot would
use 64 shards. It also has no cell switch for epoll/database count. Mainline must
bind and validate those profiles; a default runner invocation is not evidence for
this requested geometry. Do not silently treat old calibration as current.

Required affected cells: `sl2-{GET,SET}-p{1,32}-ov{0,1}`, with 1 KiB values,
512 total connections, two million keys, read-local 1, reorder 0, atomic 1.
Run each under uring and epoll, databases 1 and 4. Required neutral cells use the
same workload/depth/overlap cross product with (a) 2s read-local 0 and (b) 1s
read-local 1, retaining 16 shards. Keep ordinary key/client balancing enabled for
measurement. Retain the standard headline cells for the main-command regression gate.

Compare **PRE/POST, PRE/PAD-A, PAD-A/POST** in ABBA order at matched offered load.
Record cycles/op, instructions/op, IPC, completed rate and p99/p99.9 for every cell:
`cycles/op = instructions/op / IPC`. POST/PAD-A separates the template-choice
change from candidate layout; PRE/PAD-A exposes layout/compiler effects. No gain
is required for this correctness-adjacent cleanup, but no cell's rate or tails may
regress beyond mainline's independently measured identical-arm resolution. Do not
average away a loss, especially with the 140 KiB text growth.

| Comparison | PRE cycles/op, instr/op, IPC, rate, tails | POST / PAD and deltas | Verdict |
|---|---|---|---|
| Affected split-local overlap 0/1 | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Plain split and fused neutral controls | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |

One new row: `splitlocal template forwarding + old-argument controls`, emitted at
`tests/gate.sh:1306–1315`, collected at **line 2762**, before the quick-tier exit
block at **line 2890**. Production-unit build/readiness and job dependencies include
the new standalone unit. **Delta quick +1, full +1: 446→447 / 463→464.**
`EXPECT_QUICK` and `EXPECT_FULL` are unchanged; mainline owns their update.

After the count update, mainline's normal gate command is:

```bash
bash tests/gate.sh iteration \
  --reference-binary "$PWD/build/splitlocal/PRE/tomokv"
```

This lets the gate build/certify candidate source normally; external
`--candidate-binary` would withhold its source receipt. The live and measurement
tables above remain pending regardless of successful serverless checks.

`git diff e279aeb4cf08ae2c39f26be679388b872fed4667 --stat`:

<!-- launch-diff-stat -->
```text
 MEASURE-REQUEST-splitlocal.md     | 295 ++++++++++++++++++++++++++++++++++++++
 Makefile                          |   5 +
 src/core/io_loop.h                |  14 +-
 src/core/reorder.cc               |  14 +-
 tests/gate.sh                     |  21 ++-
 tests/signalacct_source_checks.py |   4 +-
 tests/splitlocal_checks.py        | 132 +++++++++++++++++
 tests/splitlocal_live.py          | 131 +++++++++++++++++
 tools/splitlocal_artifacts.py     | 173 ++++++++++++++++++++++
 9 files changed, 769 insertions(+), 20 deletions(-)
```
<!-- end-launch-diff-stat -->

This lane stops after the committed report. No measurement result or gate pass is claimed.
