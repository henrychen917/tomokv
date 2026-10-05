# exbatch-bench2: real perf FIFO handshake repair

Delivered on `cx-exbatch`: merge `fd3e52da6` incorporates `origin/cpp`
`ea177342d`; fix `07d7bb880` repairs ACK framing and adds a real-perf window
self-test. Work began at existing lane HEAD `8cc469008`, with a clean worktree.
No push. No server, memtier workload, or gate was run. Dry-run's required
memtier `--help` grammar check was the only memtier execution.

## Merge resolution

Ran `git fetch origin cpp && git merge origin/cpp`, resolved the conflicts by
hand, and committed the merge before touching the perf tool:

- `MEASURE-REQUEST`: kept the exbatch pointer text verbatim.
- `JOB_NAMES`: kept `persistfix_units lbplanner_units exbatch_units exbatch_live
  wb_rule_units` in that order.
- Production unit build list and readiness loop: retained `lbplanner-units`,
  `exbatch-unit`, and `exbatch-db0-unit`; preserved shell continuations.
- Production-unit dependency case: retained both lanes' alternatives.

`bash -n tests/gate.sh` and
`python3 tests/gateplan.py --json iteration > /dev/null` passed. The fixtures
match `origin/cpp` exactly. `EXPECT_QUICK=490` and `EXPECT_FULL=507` remain
unchanged from incoming mainline. The existing exbatch additions require the
maintainer's landing bump to **495 / 512**: the three unit rows emitted at line
1342 and two live rows at line 1357 are collected at lines 3087–3088, before
the quick-tier exit at line 3244. This handshake repair adds **zero gate rows**.

## Real reproduction and exact framing

Serverless reproduction ran on CPUs **112–127**, using a known continuous
`taskset -c 112 python3 -c 'while True: pass'` busy loop. Perf's control process
was pinned to CPU 120 and counters to CPUs 112–119. All other perf arguments
were identical to production, including `--delay=-1`, `--timeout 40000`,
grouped `{cycles,instructions}`, `--no-scale`, and both FIFOs opened
`O_RDWR|O_NONBLOCK`.

Installed version: `perf version 7.0.12`; `perf_event_paranoid=-1`.
The running executable was `/usr/lib/linux-hwe-7.0-tools-7.0.0-30/perf`, SHA256
`766049aa32f6c45344265a00bdfa2ec8ddee5ab7ae5e6da6e1c4a7364aff16a7`.

| Action | Exact ACK bytes read | Hex | Newly logged line |
| --- | --- | --- | --- |
| Startup with `--delay=-1` | No command sent | — | `Events disabled\n` |
| Initial `disable\n`, already disabled | `b'ack\n\x00'` | `61636b0a00` | `Events disabled\n` |
| `enable\n` | `b'ack\n\x00'` | `61636b0a00` | `Events enabled\n` |
| Second boundary command, `disable\n` | `b'ack\n\x00'` | `61636b0a00` | `Events disabled\n` |

Each response happened to arrive in one five-byte read in this capture; this
is observed framing, not a read-boundary guarantee. The complete successful
window's exact log was:

```text
Events disabled
Events disabled
Events enabled
Events disabled
```

The separate disabled-only reproduction logged exactly the first two lines
and produced `<not counted>` for **all 16 CPU/event rows**, with runtime zero,
when stopped with SIGINT. `--delay=-1` causes the first disabled line; the
redundant explicit disable causes the second. The old `reply.strip()` retains
the NUL, so it rejects a valid ACK and tears perf down before ever sending
enable. Empty counts follow directly from never enabling the events.

Raw capture, argv, logs and CSVs remain in
`build/exbatch-bench2/reproduction.json`, `disabled-only/`, and
`enabled-window/` under that same build directory.

## Repair and proof

`PerfWindow.command()` now accumulates stream fragments, extracts newline
records, tolerates the NUL terminator (including when it precedes the next
record), and drains nonblocking reads until no bytes remain. Coalesced ACK
lines are accepted and drained; surplus replies are not credited to future
commands. There is no fixed post-ACK sleep. The existing five-second deadline
is retained, with process-exit checks at most 50 ms apart while waiting.
Missing ACK lines time out with the command and received bytes; perf exits
report the log path. Valid replies no longer fail on read boundaries or NULs.
Boundary receipts now also retain `ack_hex` and `ack_lines`.

Keep the initial `disable`: it is redundant for counter state but the real
binary ACKs it, so it remains the startup liveness probe.

`--self-test` retains all **19 original tests unchanged**, adds four pipe-level
controls for fragmented/NUL/coalesced replies, complete-line timeout, stale
reply draining, and process exits, and adds **one real-perf test**. All **24
passed**, with **no skips**, on this box. Existing offline tests still trap
process launches and sockets. The real test is separately guarded by perf,
taskset, allowed CPUs 112/120, and a FIFO-independent grouped-PMU probe; once
that probe succeeds, handshake or counting failures fail the suite.

The real test runs a continuous busy loop on CPU 112 and perf on CPU 120,
with 550 ms before enable, 550 ms enabled, and 550 ms after disable. Only its
local argv substitutes `-I 100` for `--timeout 40000`, because perf forbids
combining those options. Production `perf_argv()` is unchanged. Owned-child
cleanup stops and reaps the test processes on success or failure.

For each 100 ms interval, the test bounds perf's epoch between launch and the
constructor ACK. It asserts counts only for intervals wholly within a phase
under every epoch in that bound. At least two complete intervals in **each**
phase are mandatory; an unobserved window fails. Boundary-straddling intervals
are excluded, without relaxing the zero-count checks.

Captured successful proof (CPU 112 system-wide counters):

| Phase | Complete intervals | Cycles | Instructions |
| --- | ---: | ---: | ---: |
| Before enable | 5 | 0 | 0 |
| Enabled | 3 | 932,149,498 | 2,204,456,794 |
| After disable | 5 | 0 | 0 |

Enabled IPC was **2.3649176433**, satisfying `0.1 < IPC < 6`. Busy-loop CPU
ticks at the four boundaries were **7, 62, 102, 138**, proving it ran during
every phase. Both boundary ACKs were `61636b0a00`; grouped event runtimes
matched and running percentages were 100%. These are instrument correctness
observations, not server performance measurements.

Three throwaway in-memory substitutions, applied only to the real perf window,
confirmed the test fails on broken mechanisms; no broken source was saved:

| Substitution | Required failure observed |
| --- | --- |
| Restore the old one-read exact-ACK check | `invalid perf control ACK` |
| Send `disable` in place of `enable` | `no counts inside enabled window` |
| Send `enable` in place of the closing `disable` | `counts outside enabled window: after` (310,514,809 cycles) |

Logs are `build/exbatch-bench2/{self-test,old-handshake,missing-enable,missing-disable}.log`.

## Completed checks and unchanged mainline invocation

```bash
taskset -c 112-127 python3 tools/exbatch_directed.py --self-test
taskset -c 112-127 python3 tools/exbatch_directed.py --dry-run --blocks 1 --output build/exbatch-directed/plan
python3 -m py_compile tools/exbatch_directed.py
git diff --check
```

All passed. Dry-run still prints **600 samples, 600 perf commands, 4,800 scored
memtier commands, and 2,400 rate-limited commands** and creates no run directory.
Its output is `build/exbatch-bench2/dry-run.log`. An AST comparison confirms
all 43 other top-level functions/classes, every original test method, and the
production `perf_argv()` are unchanged. PMU parsing, arm SHA validation, load
recipes, window timing limits, quiet checks, and acceptance bands are untouched.

Mainline's perf command remains exactly:

```bash
taskset -c 8 perf stat -a -A -C 0-7 -x , --no-big-num --no-scale -e '{cycles,instructions}' --delay=-1 --control=fifo:perf.ctl,perf.ack --timeout 40000 -o perf.csv
```

The implementation supplies each sample directory's absolute FIFO/CSV paths,
as before. Mainline runner commands and measurement policy are unchanged:

```bash
taskset -c 0-111 python3 tools/exbatch_directed.py --regime f0 --blocks 1 --output build/exbatch-directed/mainline-f0
taskset -c 0-111 python3 tools/exbatch_directed.py --regime f1 --blocks 1 --output build/exbatch-directed/mainline-f1
taskset -c 0-111 python3 tools/exbatch_directed.py --regime s0 --blocks 1 --output build/exbatch-directed/mainline-s0
```

Run sequentially on the scheduled quiet box. Preserve failed-run evidence;
where an output directory already exists, choose a fresh output path (for
example `mainline-f0-bench2`). No new server binaries, layouts, or PAD arms are
introduced by this repair. The existing PAD-A remains kind A: PRE behaviour
at POST layout. Mainline still owns the live measurement, gate, and landing.
