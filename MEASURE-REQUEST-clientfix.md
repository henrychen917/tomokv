## clientfix

Worktree `/home/user/Projects/cx-clientfix`, branch `cx-clientfix`; no push.
PRE source: `5146b78ee89b64748dd46db970efa8086f653fa0`.
PRE binary: `build/clientfix/pre/tomokv`; POST: `build/tomokv`.
All proof commands are confined to CPUs 112–127, with candidate servers on
112–119, the Redis 7.4.10 oracle on 120, and clients on 121–127. Ports are
25070–25083. Lifecycle logs include box load and each owned server's exit.
This file is a work-in-progress receipt until its POST/build/identity sections
are populated; it is not a gate or performance pass.

The focused task's PROOF authorization is used for PRE/POST correctness boots.
The full gate and mainline performance null remain maintainer work.

PRE negative controls are in `docs/clientfix/pre/`: all 14 rows failed their
intended assertions, and every owned server exited 0. The same seven probes
passed against Redis 7.4.10 (`docs/clientfix/oracle/`). Tracking rows cover
atomic/read-local 0/0, 1/0 and 1/1 in each thread mode.

| Finding | PRE, both modes | POST | Gate label, one per mode |
|---|---|---|---|
| CC4.1 | 1024/1100 invalidations; 76 cached misses survive, all three axes | Pending | `clientfix tracking-cap (1s/2s)` |
| CC4.2 | Later GET loses registration after pipelined NOLOOP SET | Pending | `clientfix tracking-pipeline (1s/2s)` |
| WB4.12 / WB4.13 | Skipped replies leak; retried WAIT/BLPOP duplicate MONITOR lines | Pending | `clientfix reply-skip (1s/2s)` |
| CC4.11 | Retained pattern stops receiving keep:one, receives empty-channel publication | Pending | `clientfix pattern-cleanup (1s/2s)` |
| SV4.4 | SET becomes ready inside the original 1000 ms deadline | Pending | `clientfix pause-deadline (1s/2s)` |
| CD4.1 | Nearest-five selections differ at 20/20 centres | Pending | `clientfix geo-count (1s/2s)` and `clientfix geo-store (1s/2s)` |

DQ **+14**, DF **+14**: `collect_job clientfix` is before the quick-tier exit.
The arithmetic comment above EXPECT states **511 + 14 = 525** quick and
**528 + 14 = 542** full. EXPECT assignments remain unchanged as instructed.
The explicit fixture and source declarations both contain 542 rows; the actual
ledger check refuses the still-owner-owned EXPECT_FULL=528. This is not hidden
or counted as a passing check.

Reproduce a row (replace PRE with POST for the positive control):

```sh
taskset -c 112-127 taskset -c 121-127 python3 tests/clientfix.py --binary build/clientfix/pre/tomokv --port 25070 --cores 112-119 --ratio 6:2 --mode 2s --case tracking-cap
```

Focused differential proof (both atomics, four seeds, eight suites):

```sh
for geometry in split armed-fused; do
  REDIS74_ROOT=/tmp/claude-1000/redis74 GATE_LOAD_CORES=121-127 GATE_DIFFER_ORACLE_CORES=120 GATE_DIFFER_GEOMETRY="$geometry" GATE_DIFFER_PROOF_SUITES="$PWD/docs/clientfix/differ-suites.txt" GATE_DIFFER_PROOF_SEEDS="$PWD/docs/clientfix/differ-seeds.txt" GATE_DIFFER_OUT="$PWD/build/clientfix/differ-$geometry" taskset -c 112-127 tests/differ_gate.sh "$PWD/build/tomokv" 25074 25075 112-119 6:2
done
```

PFMESSAG.1 has no optimization in this lane. `tests/clientfix_widths.py` supplies
one open-loop MSET connection, a separate idle RESP3 tracking observer, existing
keys, widths 1/32/256/1024, OFF/unmatched BCAST/default-preread, both modes,
interleaved PRE/POST/Redis boots, at least three boots and 1000 samples per cell.
Default tracking reads each cell's keys once before its timed writes, as in the
requested shape; it is not silently renewed with extra workload during timing.
Latency is measured from scheduled issue time, with send-to-reply latency and
sender lag also retained. Each cell saves CPU occupancy and load/pressure beside
raw samples, and flags p99 at or above the offered period as unsuitable for an
under-capacity comparison. Do not compile while taking these timings.

```sh
taskset -c 112-127 taskset -c 121-127 python3 tests/clientfix_widths.py --pre build/clientfix/pre/tomokv --post build/tomokv --redis /tmp/claude-1000/redis74/src/redis-server --port 25080 --cores 112-119 --oracle-cores 120 --boots 3 --samples 1000 --rate 100 --output build/clientfix/widths.jsonl
```

Report p50/p99 and ON/OFF ratios by width, mode and version, beside Redis's
ratios. The merit question is incremental tracking cost at the same offered
load; a saturated/late-sender cell or changing sibling load earns no rate verdict.
No PAD arm is currently named. Hot-body and layout identity receipts are pending.
