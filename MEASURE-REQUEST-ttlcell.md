# ttlcell: expiry traffic for the TTL sidecar comparison

Worktree `/home/user/Projects/cx-ttlcell`, branch `cx-ttlcell`, base `dab740964`.
TOOL/TEST-ONLY. Implementation commit `0a0feddab`; baseline receipts were committed
first in `6a7193081`. No production edit, build, gate, push, or performance claim.
The empty, tracked [production.diff](production.diff) is the production receipt.

## Instrument changes

`tests/abbagate.py` accepts a trailing `cli=<flags>` after the existing 15 fields.
The supported flag is one exact positive `--expiry-range=MIN-MAX`, also accepting
the equivalent space-separated argument. Shell-style quoting is parsed with
`shlex.split`; the original option text is retained in `client_flags`, and argv
is passed without a shell. Short aliases, abbreviations, unknown flags, duplicate
options, empty values, bad ranges, control characters, and attempts to override
the harness's connection, workload, timing, or output flags fail before boot.
The supported TTL workload is db0 SET or MIX with strictly positive expiry
values; zero-TTL mixtures and arbitrary-command/multi-DB TTL cells are rejected.

Both arms append the same supplied argv as the final suffix of every timed
memtier command, after the harness-owned options. Population remains ordinary
SET over the complete key range and must still pass the exact DBSIZE check.
TTL flags therefore cannot make population's own completeness check vacuous.

`client_flags` enters coverage, the cell receipt, and the calibration shape in
`tests/gate_measurements.py`, just as `server_flags` does. Full cell receipts and
cell-file digests already bind standing-null matching. Tests reject reuse of a
plain cell's floor or null even when its ID is unchanged. `cell_receipt()` omits
the new empty field for ordinary cells. The small serializer changes in the
other ABBA entry points and receipt/control helpers preserve that same schema;
`gateprod.py` also includes the suffix in its dry-run commands.

Memtier 2.5.1's positive expiry path emits **SETEX**, while its producer JSON
still calls the operation **Sets**. `tests/abba_workloads.py` maps those logical
SET counts to `cmdstat_setex` for TTL cells and records `server_command=SETEX`.
Central command progress and whole-run exact HDR/server accounting remain
mandatory. This mapping follows the upstream
[redis_protocol::write_command_set implementation](https://raw.githubusercontent.com/RedisLabs/memtier_benchmark/2.5.1/protocol.cpp).
The installed `/usr/bin/memtier_benchmark` reports version 2.5.1.

## Cells and expiry witness

[tests/ttl_cells.txt](tests/ttl_cells.txt) is private: no existing cell was renamed,
reordered, or edited. Both rows are 1s, rl=0, ov=1, ro=0, p32, 512 connections,
64-byte values, atomic=1, score=rate, with the explicit eight-instance pin used
by `tests/wb_rule_cells.txt` h05 and the generic merit h05.

| Cell | Logical workload | Timed client option | Shared key range |
| --- | --- | --- | --- |
| ttls | SET | `cli=--expiry-range=1-30` | 1–20,000,000 |
| ttlm | GET:SET 1:1 | `cli=--expiry-range=1-30` | 1–20,000,000 |

The existing `keys=20000000` option lengthens the P:P sequential revisit cycle;
a small, rapidly rewritten range can refresh every deadline before it expires.
This is an explicit workload choice, not a measured guarantee: the witness
still has to pass in every arm. Both cells use identical key/value/load geometry.
Expiry-induced misses are permitted only on these supported TTL cells, and the
raw hit/miss endpoints remain in the receipt. Plain cells retain the no-miss
check; negative TTL miss-counter deltas fail.

The counter is **`INFO STATS` → `expired_keys`**, verified in
`src/cmd/t_server.cc:2363`. The command sums `sh.stats().expired` at line 1887,
subtracts the INFO reset baseline at line 1983, and emits the value at line 2452.
No production counter was invented or changed.

The existing central INFO STATS snapshots supply `before` and `after` around
each arm's 20-second rate window. No new poller, connection, or observer command
is added. A positive delta produces an `expiry_witness` named **EXPIRY-FIRED**,
with the field, endpoints, delta, and PASS verdict. Missing/malformed counters,
a counter reset, or delta zero raise an arm-specific named failure, for example:

```text
EXPIRY-FIRED: arm B expired_keys delta=0: no expirations in measured window
```

The cell becomes FAIL and the failed measurement retains its raw endpoints,
window timing, and error. Warmup/population/drain expirations cannot satisfy this
check. Assessment and receipt validation replay the endpoints, so a cached PASS
cannot conceal a zero delta in A1, B1, B2, or A2. There is no retry or waiver.

## Receipt and fingerprint proof

Captured before editing and after the final implementation with
[receipt_proof.py](docs/ttlcell/receipt_proof.py). The raw JSON is committed under
[before](docs/ttlcell/before/manifest.json) and
[after](docs/ttlcell/after/manifest.json); the machine-readable
[comparison](docs/ttlcell/receipt-comparison.json) checks all ten payloads byte
for byte. Full SHA-256 values for cell files, parameter receipts, calibration
fingerprints, and coverage are in both identical manifests.

| Existing inventory | Cells | File digest | Receipt bytes | Cell fingerprints | Coverage bytes |
| --- | ---: | --- | --- | --- | --- |
| `tests/headline_cells.txt` | 181 | unchanged | identical | identical | identical |
| `tests/netio_cells.txt` | 32 | unchanged | identical | identical | identical |
| `/tmp/claude-1000/generic_merit_cells.txt` | 14 | unchanged | identical | identical | identical |

The **source-code** instrument fingerprint necessarily changes when the harness
changes; preserving it would incorrectly authorize old controls for new code.
It changes from `83e2bad5ae8b2fcd159c52eb540ef3b43d970ff952176952388c21fea5747c76`
to `d1cd8e2cc0ce8a8c51868604bd71b0f3c61acae91c5327275bf6174a71e08581`.
The claim of unchanged fingerprints above refers to existing **cell** shapes,
not this code hash. Collect a new null for the new TTL inventory and instrument.

## Verification and gate accounting

| Serverless check | Result | Evidence |
| --- | --- | --- |
| `python3 tests/ttlcell_test.py` | 9/9 pass | [log](docs/ttlcell/unit-test.log) |
| `python3 tests/abbagate.py --self-test` | 150/150 pass: 115 harness/TTL + 10 saturation + 9 calibration + 16 binary lifecycle | [log](docs/ttlcell/self-test.log) |
| `python3 tests/gate_measurements.py --self-test` | 11/11 pass | [log](docs/ttlcell/calibration-test.log) |
| `python3 tests/gate_receipt.py --self-test` | 66/66 pass across its five suites | [log](docs/ttlcell/receipt-test.log) |
| `python3 tests/gateprod.py --self-test` | 8/8 pass | [log](docs/ttlcell/gateprod-test.log) |
| Legacy JSON comparison | 10/10 payloads byte-identical | [proof](docs/ttlcell/receipt-comparison.json) |
| `git diff --check` | pass | No whitespace errors |

The new tests intercept children and sockets; no live server or load generator
is used. They cover exact flags/receipts, rejected spellings, calibration/null
separation, both arms' actual measurement argv positions, complete non-TTL
population, SETEX/HDR accounting, expected TTL misses, and saved zero-delta
failure artifacts. A cached PASS with zero raw delta fails in each ABBA position.

The new parser/witness tests are included by `abbagate.py --self-test`, already
run in the existing “ABBA comparison + saturation negative controls” gate row.
That row is before the quick-tier exit (row call near `tests/gate.sh:2879`, quick
exit near line 3405). **Rows +0 quick / +0 full**. `EXPECT_QUICK=502` and
`EXPECT_FULL=519` remain unchanged, as do all bytes of `tests/gate.sh` and
`tests/gate_measurements.json`.

An additional experiment-driver self-test has three pre-existing failed
assertions: its failed-null fixtures expect 24 windows, while current null
sampling adds 12 measurements. The same named failures reproduce on the
untouched base; all 426 extracted baseline test files were checked against
`dab740964`. See [baseline proof](docs/ttlcell/experiments-baseline-proof.json),
[baseline log](docs/ttlcell/experiments-base-test.log), and
[post log](docs/ttlcell/experiments-post-test.log). Its behavior is unchanged here.

## One authorized smoke attempt: precondition refusal

**REFUSED before boot; live TTL smoke evidence remains uncollected.** The normal
quiet screen observed **0.58 CPU-seconds > 0.48 seconds** of selected-core budget
per 20s. There was exactly one attempt, with no retry, threshold adjustment,
server launch, memtier launch, or measurement artifact. The native harness exits
1 and labels its report FAIL because of `QuietViolation`; this is an unmet
quiet-box precondition, not a TTL cell measurement failure.

The command used the frozen mainline `dab740964` binary in both arms, on the
lane's reserved 112–127 geometry. Its central window was the ordinary 20s (one
single-cell ABBA would contain four such windows if admitted):

```sh
python3 tests/abbagate.py --subset full --build-reference 0 \
  --reference-binary /home/user/Projects/bench-bins/tomokv-headline-dab740964 \
  --candidate-binary /home/user/Projects/bench-bins/tomokv-headline-dab740964 \
  --cells tests/ttl_cells.txt --only ttls \
  --server-cores 112-119 --server-smt '' --load-cores 120-127 --load-smt '' \
  --port 18861 --output build/ttlcell-smoke
```

Retained evidence: [attempt and exact argv](docs/ttlcell/smoke-attempt.json),
[console log](docs/ttlcell/smoke.log),
[native report](docs/ttlcell/smoke-results.json.gz), and
[quiet samples](docs/ttlcell/smoke-quiet-samples.jsonl).
No PRE/POST throughput, observed live expiration delta, or saturation result is
claimed. Mainline's scheduled quiet-box runs below provide that evidence.

## Exact mainline commands

Run from the merged worktree on the scheduled quiet box. These commands are the
measurement request, **not lane measurements**. Use new output directories if
these names already exist. No calibration-file edit or `--pin` is required.
Server CPUs are 0–31; load CPUs are 32–111; SMT is reserved. The existing ABBA
geometry records 16:16; these two fused cells actually boot 32 fused threads.
Eight generators use 64 workers and 512 total connections at that placement.
Windows remain 3s warmup + 20s central measurement + 5s tail.

Frozen binary identities are in [binaries.json](docs/ttlcell/binaries.json).
**PAD-B is type B, an inverse control:** sidecar behavior plus padding restoring
inline text size, as defined by deadswitch candidate 6. It is not a PRE-behavior
twin. No new PAD or production binary is needed for this tool-only change.

First obtain a contemporaneous identical-inline null for both TTL cells:

```sh
python3 tests/abbagate.py --subset full --build-reference 0 --collect-null 1 \
  --candidate-binary /home/user/Projects/bench-bins/tomokv-ttl-inline-3f92cd93 \
  --cells tests/ttl_cells.txt \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --port 18860 --output build/ttlcell-null-inline
```

Null collection deliberately returns PARTIAL/exit 3. Require
`null_control.verdict=PASS`, valid raw evidence, and a resolved per-cell band;
a failed/unresolved TTL null or the old generic null cannot certify this study.
Retain every planned null repeat and every failure. Then compare both candidates:

```sh
python3 tests/abbagate.py --subset full --build-reference 0 \
  --reference-binary /home/user/Projects/bench-bins/tomokv-ttl-inline-3f92cd93 \
  --candidate-binary /home/user/Projects/bench-bins/tomokv-ttl-sidecar-04eb6243 \
  --cells tests/ttl_cells.txt --null-result build/ttlcell-null-inline/results.json \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --port 18860 --output build/ttlcell-inline-v-sidecar

python3 tests/abbagate.py --subset full --build-reference 0 \
  --reference-binary /home/user/Projects/bench-bins/tomokv-ttl-inline-3f92cd93 \
  --candidate-binary /home/user/Projects/bench-bins/tomokv-ttl-pad-b-4eb4d10e \
  --cells tests/ttl_cells.txt --null-result build/ttlcell-null-inline/results.json \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --port 18860 --output build/ttlcell-inline-v-pad-b

python3 tests/abbagate.py --subset full --build-reference 0 \
  --reference-binary /home/user/Projects/bench-bins/tomokv-ttl-sidecar-04eb6243 \
  --candidate-binary /home/user/Projects/bench-bins/tomokv-ttl-pad-b-4eb4d10e \
  --cells tests/ttl_cells.txt --null-result build/ttlcell-null-inline/results.json \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --port 18860 --output build/ttlcell-sidecar-v-pad-b
```

Each comparison must retain A/B/B/A measurements with EXPIRY-FIRED delta > 0
in **every** run, exact SETEX/GET accounting, and the ordinary completion,
occupancy, spread, and null checks. The eight-instance pin fixes offered load;
it does not claim a newly measured TTL saturation floor. A failed occupancy or
expiry witness remains a failed cell.

Rate at matched load and the frozen null-derived per-cell band decide the TTL
comparison; no averaging ttls and ttlm, widening bands, or best-run selection.
Mainline supplies the PRE/POST/PAD-B table and, if needed, its aligned cycles/op,
instructions/op, and IPC diagnostics. The ordinary ABBA CLI itself does not
produce PMU metrics. No candidate keep/delete decision is made by this lane.
