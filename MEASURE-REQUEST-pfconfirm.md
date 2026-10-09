# pfconfirm: pre-registered feature confirmations

Tool/test only, based on `165d268be` (`cx-pfconfirm`). No production change,
no PRE/POST or PAD claim, no push. `production.diff` is empty. Gate rows **+0/+0**;
neither EXPECT constant changes. These are priority confirmations, not optimization
acceptance or a correctness gate. The findings remain unconfirmed until mainline runs.

The source recipes are M1 + M0, M3, M4 in
`/home/user/Projects/round4-read/pf-keyspace.md`; B1 + B0 in `pf-messaging.md`;
C1 in `pf-persist-tls.md`; and B01 in `pf-datatypes.md`. Those recipes include
future implementation and correctness checks. This campaign isolates the six
OFF/ON effects on unchanged bytes; it does not claim those future checks passed.

## Frozen experiment and verdict

Both arms use `/home/user/Projects/bench-bins/tomokv-headline-165d268be`, SHA-256
`fa9c128af17a32a68b1eece3c5ad68f00ce5f3477b65eb1b4f44c8141e5b8434`.
The runner copies and hashes that executable before boot and checks it after the
campaign. A replacement headline requires an explicit path and expected digest.

Primary geometry: loopback, physical server CPUs **0–31**, physical load CPUs
**32–111**, no SMT, fused/1s, **32 executors and 256 shards**, rl1/ov1/atomic1,
key-lb1/client-lb1, flip-auto0, no persistence. 512 main connections except the
explicit single-connection TLS and stream recipe cases. No shard/ratio override
is smuggled through `srv=`. The M0/B0 dry guards also boot split with the existing
32-thread instrument ratio 16:16 and 128 shards; those are guards, not a claim of
32 split executors on 32 CPUs. All argv and observed ownership are retained.

Every scored cell first runs one same-binary **OFF/OFF/OFF/OFF null block**,
then exactly **three OFF/ON/ON/OFF blocks**, fresh boot and population per sample.
Twenty measured seconds per sample; setup and witnesses are outside the load,
except the stated 1 Hz trigger traffic. No adaptive reruns, arm selection, or
threshold widening. The fixed generator layout and per-connection pipeline are
identical between arms. The stream cell alone has a fixed offered rate.
These are fixed-load confirmations, not claims of saturated peak throughput.

Score the named main command's completed requests/second, p99 and p99.9, merging
HDR counts across generators before taking percentiles. Never use an aggregate
mixed-command tail or average percentiles. Preserve all samples, medians,
min/max, and relative spans, including each ABBA pair's rate and tail ratios.

Pre-registered decision: **HIGH upside CONFIRMED** when any predeclared cell has
median paired rate loss **>=5%** or median paired p99 ratio **>=2**, and all three
blocks' effects in that metric exceed its measured OFF-null span. Otherwise
**NOT CONFIRMED (mark only)**. p99.9 is reported, not a third decision threshold.
Null rate span or any within-arm ABBA rate span >2% is **FAIL (unstable
measurement)**, never a wider tolerance. Missing/empty main work, errors,
missing trigger witness, stream exhaustion, or malformed HDR is **FAIL**.
An unrun or refused cell cannot become NOT CONFIRMED or PASS. Common dry guards
must also have <=2% rate span. A candidate with a failed cell has no verdict.

## Arms, witnesses and exact commands

Run all, including shared dry guards:

```sh
docs/pfconfirm/run.sh --output build/pfconfirm-mainline
```

The output directory must be new. `results.jsonl` contains exactly one result
line per candidate; sample receipts and raw memtier/server logs are retained.
Each command below runs its candidate plus the shared M0/B0 guards. Running all
six through `run.sh` performs the guards only once.

| Candidate / command suffix | OFF (A) / ON (B), main cells | TRIGGER-FIRED witness | Budget |
|---|---|---|---|
| PFKEYSPA.1 / `--only PFKEYSPA.1` | Same 1,024 persistent working keys and 1M unrelated 64-byte strings; A unrelated keys persistent, B all unrelated keys expire in 3,600 s. GET/SET p1 and p32. No INFO polling during load. | Exact resident population; sampled background PTTL absent/present before and after; volatile key count positive only in B. Main key TTLs remain absent. | 40 min |
| PFKEYSPA.3 / `--only PFKEYSPA.3` | DB0 1M strings; DB1 empty; SET p32 on DB0. A PING on DB1 at 1 Hz, B `FLUSHDB SYNC` there at 1 Hz. | DB1 empty before/after, DB0 population intact; successful timed flush replies and commandstats FLUSHDB delta match. | 10 min |
| PFKEYSPA.4 / `--only PFKEYSPA.4` | SET p32 over 1M strings and the same one-field hash. Bare INFO at 1 Hz in both arms; A no field TTL, B one HEXPIRE 3,600 s. | HEXPIRE returns 1, HTTL positive before/after, INFO poll replies contain keyspace and subexpiry; timestamped calls overlap the main load. | 10 min |
| PFMESSAG.1 / `--only PFMESSAG.1` | Repeated 1,024-key MSET p1 over existing keys. Same RESP3 control connection: A tracking OFF, B BCAST PREFIX `never:`. No main key matches. | Tracking client remains connected; a separate `never:witness` SET at 1 Hz in both arms produces received invalidation pushes only in B, and the invalidation counter advances. No MSET key delivered to tracker. | 10 min |
| PFPERSIS.1 / `--only PFPERSIS.1` | GET p32, 4/16 KiB values, 1 and 512 connections. A plain TCP, B TLS 1.3. Both boots enable the same dual listeners/certificate. No polling or PING pokes during load. | TLSv1.3 negotiated, full p32 reply bytes checked before load; successful load handshakes and TLS output bytes advance; no connection/protocol errors. | 35 min |
| PFDATATY.1 / `--only PFDATATY.1` | One connection, fresh 100k-entry stream/group, p32 rotation of A `XLEN` or B `XREADGROUP GROUP g c COUNT 1 STREAMS pf:stream >`, followed by 127 GETs. Fixed 4,096 requests/s offered per connection. GET-only rate/tails. | B pending count equals completed XREADGROUP calls, 1–1,000 deliveries, stream not exhausted; A pending zero. Main GET follows feature command on that same connection. | 10 min |

Use each suffix with, for example:
`docs/pfconfirm/run.sh --only PFKEYSPA.3 --output build/pfconfirm-flush`.
The same verdict above applies to every row. Counts are commands, not keys;
wide MSET never reports its key count as its operation rate.

Exact individual commands (each includes the shared dry guards):

```sh
docs/pfconfirm/run.sh --only PFKEYSPA.1 --output build/pfconfirm-ttl
docs/pfconfirm/run.sh --only PFKEYSPA.3 --output build/pfconfirm-flush
docs/pfconfirm/run.sh --only PFKEYSPA.4 --output build/pfconfirm-info
docs/pfconfirm/run.sh --only PFMESSAG.1 --output build/pfconfirm-tracking
docs/pfconfirm/run.sh --only PFPERSIS.1 --output build/pfconfirm-tls
docs/pfconfirm/run.sh --only PFDATATY.1 --output build/pfconfirm-stream
```

Shared M0/B0 guards (~25 min) are dry GET/SET p1/p32 and eight-key MGET/MSET p8
in both modes, plus rl0 GET/SET p32 in both modes. Each is one four-sample
identical-arm null, with rate/p99/p99.9 and spread. No production change exists
to regression-test; these establish the common workload and dry-null controls.
Estimated total **140 min**, allow **up to 170 min**, with a 170-minute watchdog.
Population, cleanup and the 20-second quiet screen are included in the allowance.
A timeout is FAIL, not a truncated confirmation.

All workload shapes are private 15-field cells. `srv=--databases 16`, `dbs=0`,
`keys=` and `poll=info1hz` retain the stock meanings. `cli=--expiry-range`
would expire the measured SET working set and cannot represent M1's unrelated
TTL population. Stock cells cannot create field TTLs, hold trackers, negotiate
TLS with validation, select empty-DB admin commands, or pair XREADGROUP with GET.
The small stateful extension therefore uses abbagate's parser/layout/workload
and HDR helpers, with explicit setup and witness checks. Stock abbagate alone
on these base cells is **not** a feature confirmation.

The selected points are pre-registered screening cases, not every dimension
of the source recipes: no shard sweep, 1% TTL arm, ASYNC flush, INFO-in-EXEC,
other tracking widths, or stream fallback mutation sweep. Positive results
justify the scoped implementation lane and its full guards. Negative results
mark only these points. Plain-vs-TLS includes normal encryption cost and cannot
attribute a penalty specifically to partial-write progress accounting; that
requires the later causal fix/control described by C1. No TLS oracle or new
production instrumentation is introduced here.

## Proof commands (not a bench authorization for this lane)

```sh
python3 tests/abbagate.py --cells docs/pfconfirm/cells.txt --list-cells
python3 tests/abbagate.py --cells docs/pfconfirm/guards.txt --list-cells
python3 docs/pfconfirm/test_confirm.py
taskset -c 112-127 docs/pfconfirm/run.sh --smoke --output build/pfconfirm-smoke
```

Smoke uses server CPUs 112–119, load CPUs 120–127, ports 25000/25001, two
seconds, small resident data and at most eight main connections. It exercises
each candidate's A/B setup, actual memtier commands and witnesses. Smoke never
produces a performance verdict. A latched gate quiet-screen refusal is recorded
as **REFUSED**, without booting or retrying until green. Full runs use the same
reserved ports and are left to the maintainer. Proof results will be appended
after the pre-registration commit.

## Delivered proof

The cell definitions were committed in `3a5e9911b`, and this pre-registration
in `bdb8141e9`, before any run. The initial runner and negative controls were
committed in `ca6fdb1aa`. No full benchmark, server, or load generator ran in
this lane. No production build was necessary: both arms use the existing
headline binary above.

- Both `--list-cells` invocations passed: **12 scoring cells + 16 dry guards**.
  Retained output: [cells.json](docs/pfconfirm/proof/cells.json) and
  [guards.json](docs/pfconfirm/proof/guards.json).
- **17 serverless checks passed**, including all six absent-trigger negative
  controls, unstable-null rejection, no best-block selection, exact completed
  work/rejection checks, and count-weighted GET-only tails. See
  [unit.txt](docs/pfconfirm/proof/unit.txt). Python compilation and shell syntax
  checks passed. These checks are not substitutes for live witnesses.
- The exact short smoke command above returned **3 / REFUSED**. The gate's
  latched quiet screen observed **1.03 CPU-seconds > 0.48 CPU-seconds** on
  CPUs 112–127. **All six candidates are REFUSED; zero boots and zero loads**.
  No live trigger or witness was exercised, and the quiet screen was not
  retried. See [smoke receipt](docs/pfconfirm/proof/smoke-attempt.json),
  [quiet evidence](docs/pfconfirm/proof/smoke-quiet.json), and
  [six result lines](docs/pfconfirm/proof/smoke-results.jsonl).

The refusal happened at the same unchanged preflight used by the final driver;
subsequent serverless review strengthened command/configuration/error checks.
Mainline must first run the short smoke in its quiet slot, with a fresh output
directory, then the full command:

```sh
taskset -c 112-127 docs/pfconfirm/run.sh --smoke --output build/pfconfirm-smoke-mainline
docs/pfconfirm/run.sh --output build/pfconfirm-mainline
```

Performance verdicts remain **unmeasured**. Rows **+0/+0**. `src/`, gate files,
and EXPECT constants are unchanged; the committed `production.diff` is empty.
