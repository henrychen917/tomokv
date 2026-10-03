# netcap — NET1 / same-path NET13 and NET17

Branch/worktree: `cx-netcap`, `/home/user/Projects/cx-netcap`.
Launch HEAD: `e279aeb4cf08ae2c39f26be679388b872fed4667`.
`git fetch origin cpp && git merge --no-edit origin/cpp` completed first; already up to date.
Implementation commits: `5a41b1496`, `feabc32ac`, `985d30a7b`.

The fix is committed and release builds succeed. No server, benchmark, live battery,
or gate was run by this lane. All builds used `taskset -c 112-127 make -j16`;
all executed checks were serverless and pinned to 112–127. Live results and
performance verdicts below remain for mainline. Nothing was pushed.

## Diagnosis and reference correction

The launch tree confirms NET1 exactly: `src/net/resp.h:75` restarts `find_crlf`
at `pos` on every attempt; `:85` returns Incomplete without an inline bound.
`src/net/conn.h:335` selects `UINT32_MAX` and `:336` allows that growth whenever
`rpos_ == 0`. An incomplete inline frame preserves that condition and ROB
quiescence. Pre-AUTH selects the same inline arm; its argument-count/bulk limits
do not bound this input. The launch source is preserved in `build/netcap-pre-src`.

Redis 7.4 **does not have a `proto-max-inline` configuration parameter**. Its
64 KiB `PROTO_INLINE_MAX_SIZE` is fixed. Consequently this lane deliberately
preserves Redis's empty CONFIG GET and unknown-option CONFIG SET for that spelling,
rather than inventing a writable knob. The actual knob is
`client-query-buffer-limit`, default `1073741824`, range
`1048576..9223372036854775807` on this 64-bit target. Zero and -1 are rejected;
there is no Redis off/auto state to implement.

Reference facts were checked against the official 7.4.0 source, not inferred from
another server: [configuration registration and numeric parsing](https://raw.githubusercontent.com/redis/redis/7.4.0/src/config.c),
[fixed protocol limit](https://raw.githubusercontent.com/redis/redis/7.4.0/src/server.h),
[inline/framing errors and silent query-buffer disconnect](https://raw.githubusercontent.com/redis/redis/7.4.0/src/networking.c),
[memory-value grammar](https://raw.githubusercontent.com/redis/redis/7.4.0/src/util.c), and
[queued MULTI accounting](https://raw.githubusercontent.com/redis/redis/7.4.0/src/multi.c).
There was no live reference-server run.

## Change and boundaries

- `src/net/resp.h:25–79`: fixed inline bound and resumed scan. The saved offset
  denotes the next CRLF candidate relative to the unconsumed request, including
  the trailing CR case. Repeated attempts without input do constant work; the
  directed scan checks exactly one visit per candidate. A completed frame resets
  the cursor so dispatch backpressure can reparse it.
- `src/net/conn.h:311–359`: consume/reset the cursor, account pending input, cap
  receive growth/offers, and offer one byte beyond a query limit to distinguish
  legal equality from overflow. epoll/TLS stop buffering at the inline frontier
  before their next parse. No zero-length recv is offered (the adjoining NET3
  boundary). Parsed bytes pinned by outstanding argv are not pending input.
  Existing quiescence and kernel-pointer fences still govern all reallocations.
- `src/core/io_loop.h:845`, `:2291`, `:2399`, `:2936`, `:3056` and matching
  `src/core/reorder.cc:1607`, `:2039`, `:2139`, `:2259`: apply the live query cap
  before parsing received bytes, including migration completion and TLS plaintext;
  retain the ordinary close/reclaim path. Query overflow closes without a reply,
  as Redis does. Pre-AUTH additionally uses Redis's 1 MiB query bound. Both
  ordinary and reorder parsers use the connection's saved inline scan offset.
- `src/core/config.h:125`, `:451`, `:965`; `src/cmd/t_server.cc:397`, `:534`,
  `:608`, `:1473`; `src/core/server.h:305`, `:2066`, `:3440`: CLI/conf and live
  CONFIG GET/SET, memory suffixes, exact range/grammar errors, duplicate rejection,
  and publication through the existing committed configuration mailbox. Numeric
  spelling normalizes to decimal bytes. No per-operation reader retry is added.
- `src/cmd/multi.inc:107`, `:1670`, `:2292`: maintain pending MULTI argument
  accounting incrementally, including Redis's one-pointer-per-argument allowance;
  clear it with every queue clear. Receive checks never walk a growing queue.
  Existing CLIENT memory reporting retains its prior behavior.
- Framing errors now carry `Protocol error:`. The expected-`$` error includes the
  offending byte, including embedded NUL; CR/LF is sanitized like Redis. The unit
  checks all 255 invalid prefix bytes. These changes stay in the reported framing
  error path. Existing bare-LF/quoted-inline grammar, empty/negative arrays, and
  leading-zero length behavior were not expanded into a general RESP rewrite.

`Client::inline_scanned_` occupies offsets 76–79, existing IO-only padding,
locked by `src/net/conn.h:911`. No established Client field moves. Config uses
reserved bytes; its existing fields retain their offsets. LiveConfigSnapshot
still occupies 64 bytes after packing its existing small fields. New Server/IO
caches are at their cold tails. The full compiled layout witness is:

```text
layouts Op=336 Client=1984 ThreadCtx=1408 Shard=1440 FlatStore=944 Rob=192 AtomicEntry=144 Config=624
```

## Executed proof

```text
release build (ordinary and databases=1 objects): exit 0
build/netcap-unit all: PASS netcap all
build/config-parser-test: boot presentation: 512 resolved cells, eight placement witnesses each
build/netcmd-unit receive: ok: netcmd receive
build/netcmd-unit config: ok: atomic fingerprint boot=0, three runtime toggles with active work
build/netcmd-unit config: ok: atomic fingerprint boot=1, three runtime toggles with active work
build/netcmd-unit config: ok: netcmd config
python3 tests/wbland_checks.py check clauses: PASS wbland clauses: 72/72 strict outcomes
Python syntax, bash -n tests/gate.sh, git diff --check: exit 0
```

The new unit proves both default and pre-AUTH parser limits, the 64 KiB boundary,
split CRLF, repeated attempts, compaction, retry after dispatch refusal, bounded
allocation, query equality/overflow, CONFIG publication and rejection, MULTI
account/reset, framing bytes, and actual IO rejection/reclamation. The free
witness wraps `free`, follows real `close_client`/`reap_dead`, and separately
holds an outstanding recv and argv to prove neither lifetime fence is weakened.
The expected CLI rejection diagnostics in `build/netcap-unit.log` are successful
negative cases, not failed checks.

All five negative controls failed at their named assertion, with exit 1:

| Control | Command argument | Observed assertion |
| --- | --- | --- |
| Launch headers + launch objects (`netcap-old-unit`) | `inline` | `NET1: 1 MiB unterminated inline rejected` |
| Reset scan start to zero (`netcap-scan-control`) | `scan` | `NET1: every CRLF candidate scanned once despite retries` |
| Disable overflow predicate (`netcap-query-control`) | `buffers` | `NET1: query limit overflow detected` |
| Restore unbounded allocation ceiling (`netcap-allocation-control`) | `buffers` | `NET1: query cap bounds allocation including one overflow byte` |
| Remove receive-buffer free (`netcap-free-control`) | `teardown` | `NET1: closed client receive buffer freed exactly once` |

The assertion lines are prefixed `FAIL netcap:` in the actual outputs. These are
serverless binaries using throwaway sources, never corrupted running servers.
Receipts: `build/netcap-proof.json`, `build/netcap-*-control.log`,
`build/netcap-old-unit.log`, `build/netcap-wbland.log`.
Re-run the local proofs without starting a server:

```bash
taskset -c 112-127 make -j16 all build/netcap-unit build/netcmd-unit build/config-parser-test build/wbland-units
taskset -c 112-127 ./build/netcap-unit all
taskset -c 112-127 ./build/config-parser-test
taskset -c 112-127 ./build/netcmd-unit receive
taskset -c 112-127 ./build/netcmd-unit config
taskset -c 112-127 python3 tests/wbland_checks.py check clauses
# Throwaway negative-control recipes and sources remain in this worktree's build/.
taskset -c 112-127 make -j16 -f Makefile -f build/netcap-negative.mk build/netcap-old-unit build/netcap-scan-control build/netcap-query-control build/netcap-allocation-control build/netcap-free-control
taskset -c 112-127 ./build/netcap-old-unit inline        # must exit 1
taskset -c 112-127 ./build/netcap-scan-control scan      # must exit 1
taskset -c 112-127 ./build/netcap-query-control buffers # must exit 1
taskset -c 112-127 ./build/netcap-allocation-control buffers # must exit 1
taskset -c 112-127 ./build/netcap-free-control teardown # must exit 1
```

## Mainline live checks — not run here

`tests/netcap.py` first proves two retained connections share one IO thread with
DEBUG IO-THREAD and disabled client migration. It enables requirepass, RESETs
only the victim into pre-AUTH state, and requires NOAUTH. It must observe exactly
65536 pending bytes before sending the rest of the 1 MiB unterminated input.
It requires the exact inline error and close, removal from CLIENT LIST, and PING
service on the second connection. Its fixed p50 liveness band is
`max(4 * baseline_p50, 2 ms)`; it never widens or skips on failure. Buffer freeing
is independently witnessed by the serverless actual reclamation test above.
It then exercises live lowering/raising of the query cap, MULTI queued bytes,
silent overflow closes, and exact framing-error replies.

The following is an exact **mainline-only** reproduction of the four new live
rows. Each server has 16 shards on cores 0–7; split uses the gate's 6 IO + 2 EX.
Use an otherwise quiet, scheduled box. These commands have not been executed here.

```bash
cd /home/user/Projects/cx-netcap
for netcap_mode in 1s 2s; do
  for netcap_engine in uring epoll; do
    netcap_dir=$(mktemp -d "$PWD/build/netcap-live.XXXXXX")
    netcap_ratio=()
    if [ "$netcap_mode" = 2s ]; then netcap_ratio=(--ratio 6:2); fi
    taskset -c 0-7 ./build/tomokv-netcap-post --bind 127.0.0.1 --port 16379 \
      --shards 16 --thread-mode "$netcap_mode" "${netcap_ratio[@]}" \
      --net-io "$netcap_engine" --enable-debug-command yes --client-lb 0 \
      --save '' --dir "$netcap_dir" >"$netcap_dir/server.log" 2>&1 &
    netcap_pid=$!
    trap 'kill -TERM "$netcap_pid" 2>/dev/null || true; wait "$netcap_pid" 2>/dev/null || true' EXIT
    taskset -c 8-9 python3 - <<'PY'
import socket, time
for _ in range(300):
    try:
        with socket.create_connection(('127.0.0.1', 16379), timeout=.1):
            break
    except OSError:
        time.sleep(.1)
else:
    raise SystemExit('netcap server did not become ready')
PY
    taskset -c 8-9 python3 tests/netcap.py 127.0.0.1 16379 || exit 1
    kill -TERM "$netcap_pid"
    wait "$netcap_pid" || exit 1
    trap - EXIT
  done
done
```

For a live negative control, substitute `build/tomokv-netcap-pre`; the inline
error assertion must fail. For the reorder/read-local envelopes, repeat the same
POST commands with `--reorder 1 --overlap 1 --read-local 1`. No production data is
used: every boot above owns a fresh directory.

## Gate rows and counts

- One serverless row at `tests/gate.sh:1390`, collected with `netcmd_units` at
  line 2784, includes build readiness and the complete new unit.
- `job_netcap` at line 1396 emits four live rows (1s/2s × uring/epoll), collected
  at line 2788. **Both collection sites precede the quick exit at line 2910.**
- `tests/knobs.py` adds the query-limit default, accepted memory spellings,
  normalization, rejected range/grammar, no mutation after rejection, duplicates,
  and absence of the invented `proto-max-inline` knob. These extend existing knob
  rows and add no separate gate count.

**Delta: +5 quick and +5 full. From launch constants 446/463, the resulting counts
are 451/468. `EXPECT_QUICK` and `EXPECT_FULL` are untouched.** Mainline owns their
update before running the complete gate:

```bash
tests/gate.sh iteration --server-cores 0-31 --load-cores 32-111 \
  --ports 16379-16450 --reference-binary "$PWD/build/tomokv-netcap-pre" \
  --candidate-binary "$PWD/build/tomokv-netcap-post"
```

## Measurement request and arms

This is a correctness fix; no throughput or latency gain is claimed. The release
artifacts below are built and frozen in this worktree. **PAD is kind B, inverse
control: candidate behavior plus 400 bytes of inert text padding restoring PRE's
`.text` size.** It uses the same production object files and resident layouts as
POST. The existing locked layouts are unchanged, but the cold query-accounting
state and configuration packing justify retaining a control. This is a total
text-size control, not a claim of identical instruction addresses across PRE/POST.

| Arm | Executable | `.text` bytes | Matched-load rate / latency, cycles/op, IPC, instr/op |
| --- | --- | ---: | --- |
| PRE | `build/tomokv-netcap-pre` | 7,554,449 | Mainline pending |
| POST | `build/tomokv-netcap-post` | 7,554,049 | Mainline pending |
| PAD B | `build/tomokv-netcap-pad` | 7,554,449 | Mainline pending |

```text
PRE  sha256 97f5d03d9de21c3ebcb7c3223f35e656790d68ffa1fa79a90b3a0d54f827a5f1
POST sha256 19f79d313ac2faadfa04586abb015c07129e756db23a6d955ddc3fe3d39ac230
PAD  sha256 78526b9c897dbc9a84e2d9050843a40715014aad2b2d38c437079913d24fb0a4
```

Use the gate's own ABBA instrument and pinned offered-load choices for
`h01,h02,h17,h18,h33,h34,h49,h50` (ordinary 1s/2s GET/SET, p32/p1), plus
`h15,h16,h31,h32,h47,h48,h63,h64` (the all-enabled counterparts). Compare PRE/POST
and PRE/PAD B on the same quiet box and load choices. The rate/latency verdict and
its existing null-derived uncertainty decide regression; cycles/op, IPC and
instructions/op explain it. POST and PAD B should agree within that uncertainty;
a discrepancy makes a performance attribution to the new mechanism unsupported.
These partial diagnostics do not replace the complete correctness gate.

```bash
netcap_cells=h01,h02,h17,h18,h33,h34,h49,h50,h15,h16,h31,h32,h47,h48,h63,h64
for netcap_arm in post pad; do
  python3 tests/abbagate.py --build-reference 0 --subset full --only "$netcap_cells" \
    --reference-binary "$PWD/build/tomokv-netcap-pre" \
    --candidate-binary "$PWD/build/tomokv-netcap-$netcap_arm" \
    --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
    --ports 17400-17431 --output "$PWD/build/netcap-abba-$netcap_arm"
done
```

Record live outcomes and measured tables in `MEASURE-RESULT-netcap.md`. The lane
has stopped after this report; it does not wait for or run those measurements.

## Diff from launch

`git diff e279aeb4cf08ae2c39f26be679388b872fed4667 --stat`:

```text
 MEASURE-REQUEST-netcap.md | 281 ++++++++++++++++++++++++++++++++++++++++++++++
 Makefile                  |   4 +
 docs/CONFIGURATION.md     |   6 +
 src/cmd/multi.h           |   1 +
 src/cmd/multi.inc         |  25 +++--
 src/cmd/t_server.cc       |  14 ++-
 src/core/config.h         |  37 +++++-
 src/core/io_loop.h        |  41 ++++++-
 src/core/live_config.h    |   6 +-
 src/core/reorder.cc       |  20 +++-
 src/core/server.h         |   8 ++
 src/net/conn.h            |  39 +++++--
 src/net/resp.h            |  84 +++++++++-----
 tests/gate.sh             |  39 ++++++-
 tests/knobs.py            |  34 ++++++
 tests/netcap.py           | 185 ++++++++++++++++++++++++++++++
 tests/netcap_unit.cc      | 262 ++++++++++++++++++++++++++++++++++++++++++
 tomokv.conf               |   4 +
 18 files changed, 1030 insertions(+), 60 deletions(-)
```
