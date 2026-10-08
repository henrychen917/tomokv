TomoKV gateprod — measurement request and proof, 2026-10-08

The frozen h01–h32 p32 GET/SET product now has 64 cells: its original 32 uring
cells plus 32 epoll twins. The merged baseline is `5efc5414d3d6107b5e7e29f2404e585806c823ec`.
**Baseline discrepancy:** `origin/cpp` already has 181 headline cells, not 32.
This lane preserves all 181 and adds the epoll twins as a second measurement pass:
**213 full measurements**, or **26 iteration measurements** (18 original + 8 epoll).
The other 149 headline cells remain unchanged. The requested p32 product doubles;
the entire current headline tier grows by 32/181 = 17.68%, rather than doubling.
This is the conservative interpretation of the 32→64 ruling after the initial merge.

`tests/gate.sh` dispatches the unchanged ABBA executable twice through
`tests/gateprod.py`: the original headline file first, then `tests/netio_cells.txt`.
The original result stays at the requested output path; the epoll result is at that
path with `-epoll` appended. A failure or untrusted result from either pass remains
nonzero in the combined status. Private `--cells` diagnostics retain their own
selection; `--only` on the standard headline also selects the corresponding epoll
IDs when they belong to h01–h32. No differential suite lists were changed.

**Frozen grammar and identity.** The existing parser accepts IDs matching
`[A-Za-z0-9_-]+`. New IDs use the permitted `-epoll` suffix, e.g. `h01-epoll`.
The existing extended grammar accepts a sixteenth pipe-separated field
`srv=--net-io epoll`. No parser or instrument changes are needed. Every other
field, including smoke membership, is copied exactly from its uring counterpart.
The original uring argv continues to omit `--net-io`, preserving the existing
uring default. Both epoll arms explicitly append `--net-io epoll`.

SHA256 convention: the exact UTF-8 data line including its terminating LF;
concatenate h01 through h32 in file order for the product digest. Do not strip
whitespace or hash a reserialization. The original 32-line digest is
`244c3941036d8b4535df60eb7a6304bd1f022e046a4c40fdada9501114bc5abc` before and after. The entire untouched headline file
is `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350`. All individual line digests are in
[uring-line-sha256.json](tests/gateprod-evidence/uring-line-sha256.json).

| Check | PRE | POST |
| --- | --- | --- |
| p32 measurement product | 32 uring | 32 unchanged uring + 32 epoll |
| Headline measurement inventory | 181 | 181 original + 32 epoll in the second pass |
| Instrument SHA256 | `83e2bad5ae8b2fcd159c52eb540ef3b43d970ff952176952388c21fea5747c76` | identical |
| h01–h32 cell bytes, IDs, parameters, load settings | frozen | identical |
| Correctness counts | 500 quick / 517 full | 500 quick / 517 full |
| Production diff against origin/cpp | baseline | 0 bytes |

`tests/abba_instrument.py` fingerprints executable roots and their transitive
Python imports, including test bodies. It deliberately excludes gate.sh and cell
DATA; runtime cell-source SHA, parsed parameters, geometry, binaries and environment
are bound separately by `abba_evidence`. This lane leaves that file, every existing
fingerprint dependency, `abbagate.py`, `headline_cells.txt`, the measurement config,
and the label fixture untouched. The complete before/after manifests compare equal,
not merely their top-level hashes. See [proof.json](tests/gateprod-evidence/proof.json),
[instrument-before.json](tests/gateprod-evidence/instrument-before.json), and
[instrument-after.json](tests/gateprod-evidence/instrument-after.json).
The new serverless controls run inside the existing ABBA negative-control row;
they prove the epoll axes, both-arm boot argv, memtier argv, missing/wrong-engine
negative controls, independent null identity, and combined dispatch/status handling.
The original instrument tests run unchanged. No bound was relaxed.

**Dry run.** This command prints JSON for the complete 64-cell matrix, with server
and memtier argv for both A/B arms at the initial or currently pinned load rung,
the unchanged escalation ladder, placement, ABBA order and duration estimate.
It exits before any build, server, generator, quiet preflight or capability probe.
The normal order is A/B/B/A; subsequent repetitions use the same argv with their
sequence-specific artifact directory. The current snapshot has no applicable pins
for h01–h32 or their new twins, so each starts at n=1 and searches as required.

```bash
bash tests/gate.sh perf --dry-run \
  --server-cores 0-31 --server-smt '' \
  --load-cores 32-127 --load-smt 160-255 \
  --candidate-binary "$PWD/build/gateprod/tomokv-smoke" \
  --reference-binary /home/user/Projects/bench-bins/tomokv-headline-5efc5414d \
  --output "$PWD/build/gateprod/final-sweep"
```

The complete captured output is [matrix.json.gz](tests/gateprod-evidence/matrix.json.gz)
(uncompressed SHA256 `c3a58c5bb45cdc9d7d4f152743cc59254323fd159101872919a3f9e770df7374`). All rows retain 64-byte
values, 2,000,000 keys, P:P key generation, 512 connections, atomic=1 and rate scoring.
At the initial n=1 rung the native memtier command has 16 workers × 32 clients.
The full geometry is 32 physical server CPUs and 96 physical + 96 SMT load CPUs.
These are the existing measurement axes, not the separate eight-core correctness
geometry. Fused has 256 shards; split uses the reviewed 16:16 ratio and 128 shards.

| ID | Net IO | Mode | RL | OV | RO | Shape | Connections | Shards | IO:EX |
| --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| h01 | uring | 1s | 0 | 0 | 0 | GET p32 | 512 | 256 | fused |
| h02 | uring | 1s | 0 | 0 | 0 | SET p32 | 512 | 256 | fused |
| h03 | uring | 1s | 0 | 0 | 1 | GET p32 | 512 | 256 | fused |
| h04 | uring | 1s | 0 | 0 | 1 | SET p32 | 512 | 256 | fused |
| h05 | uring | 1s | 0 | 1 | 0 | GET p32 | 512 | 256 | fused |
| h06 | uring | 1s | 0 | 1 | 0 | SET p32 | 512 | 256 | fused |
| h07 | uring | 1s | 0 | 1 | 1 | GET p32 | 512 | 256 | fused |
| h08 | uring | 1s | 0 | 1 | 1 | SET p32 | 512 | 256 | fused |
| h09 | uring | 1s | 1 | 0 | 0 | GET p32 | 512 | 256 | fused |
| h10 | uring | 1s | 1 | 0 | 0 | SET p32 | 512 | 256 | fused |
| h11 | uring | 1s | 1 | 0 | 1 | GET p32 | 512 | 256 | fused |
| h12 | uring | 1s | 1 | 0 | 1 | SET p32 | 512 | 256 | fused |
| h13 | uring | 1s | 1 | 1 | 0 | GET p32 | 512 | 256 | fused |
| h14 | uring | 1s | 1 | 1 | 0 | SET p32 | 512 | 256 | fused |
| h15 | uring | 1s | 1 | 1 | 1 | GET p32 | 512 | 256 | fused |
| h16 | uring | 1s | 1 | 1 | 1 | SET p32 | 512 | 256 | fused |
| h17 | uring | 2s | 0 | 0 | 0 | GET p32 | 512 | 128 | 16:16 |
| h18 | uring | 2s | 0 | 0 | 0 | SET p32 | 512 | 128 | 16:16 |
| h19 | uring | 2s | 0 | 0 | 1 | GET p32 | 512 | 128 | 16:16 |
| h20 | uring | 2s | 0 | 0 | 1 | SET p32 | 512 | 128 | 16:16 |
| h21 | uring | 2s | 0 | 1 | 0 | GET p32 | 512 | 128 | 16:16 |
| h22 | uring | 2s | 0 | 1 | 0 | SET p32 | 512 | 128 | 16:16 |
| h23 | uring | 2s | 0 | 1 | 1 | GET p32 | 512 | 128 | 16:16 |
| h24 | uring | 2s | 0 | 1 | 1 | SET p32 | 512 | 128 | 16:16 |
| h25 | uring | 2s | 1 | 0 | 0 | GET p32 | 512 | 128 | 16:16 |
| h26 | uring | 2s | 1 | 0 | 0 | SET p32 | 512 | 128 | 16:16 |
| h27 | uring | 2s | 1 | 0 | 1 | GET p32 | 512 | 128 | 16:16 |
| h28 | uring | 2s | 1 | 0 | 1 | SET p32 | 512 | 128 | 16:16 |
| h29 | uring | 2s | 1 | 1 | 0 | GET p32 | 512 | 128 | 16:16 |
| h30 | uring | 2s | 1 | 1 | 0 | SET p32 | 512 | 128 | 16:16 |
| h31 | uring | 2s | 1 | 1 | 1 | GET p32 | 512 | 128 | 16:16 |
| h32 | uring | 2s | 1 | 1 | 1 | SET p32 | 512 | 128 | 16:16 |
| h01-epoll | epoll | 1s | 0 | 0 | 0 | GET p32 | 512 | 256 | fused |
| h02-epoll | epoll | 1s | 0 | 0 | 0 | SET p32 | 512 | 256 | fused |
| h03-epoll | epoll | 1s | 0 | 0 | 1 | GET p32 | 512 | 256 | fused |
| h04-epoll | epoll | 1s | 0 | 0 | 1 | SET p32 | 512 | 256 | fused |
| h05-epoll | epoll | 1s | 0 | 1 | 0 | GET p32 | 512 | 256 | fused |
| h06-epoll | epoll | 1s | 0 | 1 | 0 | SET p32 | 512 | 256 | fused |
| h07-epoll | epoll | 1s | 0 | 1 | 1 | GET p32 | 512 | 256 | fused |
| h08-epoll | epoll | 1s | 0 | 1 | 1 | SET p32 | 512 | 256 | fused |
| h09-epoll | epoll | 1s | 1 | 0 | 0 | GET p32 | 512 | 256 | fused |
| h10-epoll | epoll | 1s | 1 | 0 | 0 | SET p32 | 512 | 256 | fused |
| h11-epoll | epoll | 1s | 1 | 0 | 1 | GET p32 | 512 | 256 | fused |
| h12-epoll | epoll | 1s | 1 | 0 | 1 | SET p32 | 512 | 256 | fused |
| h13-epoll | epoll | 1s | 1 | 1 | 0 | GET p32 | 512 | 256 | fused |
| h14-epoll | epoll | 1s | 1 | 1 | 0 | SET p32 | 512 | 256 | fused |
| h15-epoll | epoll | 1s | 1 | 1 | 1 | GET p32 | 512 | 256 | fused |
| h16-epoll | epoll | 1s | 1 | 1 | 1 | SET p32 | 512 | 256 | fused |
| h17-epoll | epoll | 2s | 0 | 0 | 0 | GET p32 | 512 | 128 | 16:16 |
| h18-epoll | epoll | 2s | 0 | 0 | 0 | SET p32 | 512 | 128 | 16:16 |
| h19-epoll | epoll | 2s | 0 | 0 | 1 | GET p32 | 512 | 128 | 16:16 |
| h20-epoll | epoll | 2s | 0 | 0 | 1 | SET p32 | 512 | 128 | 16:16 |
| h21-epoll | epoll | 2s | 0 | 1 | 0 | GET p32 | 512 | 128 | 16:16 |
| h22-epoll | epoll | 2s | 0 | 1 | 0 | SET p32 | 512 | 128 | 16:16 |
| h23-epoll | epoll | 2s | 0 | 1 | 1 | GET p32 | 512 | 128 | 16:16 |
| h24-epoll | epoll | 2s | 0 | 1 | 1 | SET p32 | 512 | 128 | 16:16 |
| h25-epoll | epoll | 2s | 1 | 0 | 0 | GET p32 | 512 | 128 | 16:16 |
| h26-epoll | epoll | 2s | 1 | 0 | 0 | SET p32 | 512 | 128 | 16:16 |
| h27-epoll | epoll | 2s | 1 | 0 | 1 | GET p32 | 512 | 128 | 16:16 |
| h28-epoll | epoll | 2s | 1 | 0 | 1 | SET p32 | 512 | 128 | 16:16 |
| h29-epoll | epoll | 2s | 1 | 1 | 0 | GET p32 | 512 | 128 | 16:16 |
| h30-epoll | epoll | 2s | 1 | 1 | 0 | SET p32 | 512 | 128 | 16:16 |
| h31-epoll | epoll | 2s | 1 | 1 | 1 | GET p32 | 512 | 128 | 16:16 |
| h32-epoll | epoll | 2s | 1 | 1 | 1 | SET p32 | 512 | 128 | 16:16 |

**Smoke admission and boot lines.** The requested smoke was attempted with server
CPUs 112–119, load CPUs 120–127, no SMT and TCP port 18760. It would run h01 and
h01-epoll once each in fused mode, through the real Runner's existing isolated
10-second calibration window (3-second warmup + 10-second central window +
5-second tail). It asserts CONFIG GET net-io before population, then greps each
server's `tomokv-cpp:` boot line. It cannot produce a comparison PASS.
There is no reviewed eight-core split ABBA ratio, so this smoke does not invent one.

The copied binary is the published `tomokv-headline-5efc5414d`, SHA256
`f2d62135aa03585ea847457f1fd202b66c108c93084d357095164256a39f20d5`, verified against bench-bins/MANIFEST.md.
There are no production changes to rebuild. The exact smoke driver invocation was:

```bash
taskset -c 120-127 python3 tests/gateprod.py --smoke \
  --candidate-binary "$PWD/build/gateprod/tomokv-smoke" \
  --server-cores 112-119 --server-smt '' \
  --load-cores 120-127 --load-smt '' --port 18760 \
  --output "$PWD/build/gateprod/smoke"
```

**Result: REFUSED, exit 3. No server or load generator started, so no live boot
lines exist.** The initial attempt and three retries, spaced 200 seconds apart,
all exceeded the unchanged quiet-screening budget. Total elapsed time was
611.015 seconds. The guard may refuse on an early sample
as soon as the full 20-second budget is exceeded; no tolerance was widened.
The samples establish selected-core contention; they do not identify its process owner.
This is the ruling's explicit bounded-refusal fallback, not evidence that either
transport was booted live. Both-arm argv for every epoll cell is proved serverlessly.

| Attempt | Started UTC | Observed CPU seconds at refusal | Budget CPU seconds |
| ---: | --- | ---: | ---: |
| 1 | 2026-10-08T06:01:26+00:00 | 14.170 | 0.480 |
| 2 | 2026-10-08T06:04:46+00:00 | 13.120 | 0.480 |
| 3 | 2026-10-08T06:08:06+00:00 | 4.130 | 0.480 |
| 4 | 2026-10-08T06:11:26+00:00 | 2.900 | 0.480 |

The complete refusal records and raw selected-CPU samples are committed alongside
[smoke.json](tests/gateprod-evidence/smoke.json) and
[smoke-driver.log](tests/gateprod-evidence/smoke-driver.log). On a quiet box, rerun
the smoke command with a fresh output path such as `build/gateprod/smoke-next`, then:

```bash
grep -E '^tomokv-cpp:.*(io_uring|epoll)' \
  build/gateprod/smoke-next/h01/n1-1-B/server.log \
  build/gateprod/smoke-next/h01-epoll/n1-1-B/server.log
```

**Row accounting:** +0 quick / +0 full. No new row is emitted. The product controls
join the existing `ABBA comparison + saturation negative controls` row at gate.sh
line 2869, before the quick-tier exit at line 3394. The measurement dispatch at
line 3472 is after that exit and emits zero scored correctness rows. Static expansion
compares all quick/full labels and their multiplicities to origin/cpp: 500/517,
identical in order and content. EXPECT_QUICK, EXPECT_FULL and the label fixture
were not edited. The source-label fixture and its negative controls pass.

**Duration estimate:** existing WARMUP=3, WINDOW=20, TAIL=5 gives 28 seconds per
arm run. One four-run ABBA block costs 112 seconds per cell (80 scored seconds).
This is generator time; startup, population, probes, teardown and quiet preflights
are additional. Unpinned load search and repeated null blocks are additional too.

| Inventory | Cells | One ABBA block per cell |
| --- | ---: | ---: |
| Original p32 product | 32 | 3,584 s = 59m44s |
| Expanded p32 product | 64 | 7,168 s = 1h59m28s |
| Original complete headline | 181 | 20,272 s = 5h37m52s |
| Complete gate after this lane | 213 | 23,856 s = 6h37m36s |

The p32 product doubles exactly. The current complete tier adds 3,584 seconds of
nominal generator time plus another pass's preflight and setup. The unchanged
six-rung default ladder is 1,2,4,8,12,16; a cell reaching all six rungs costs
672 seconds of generator time before overhead. Do not budget the table as a wall-time cap.

**Final-sweep measurement request:** run the gate's full measurement selection
on the owner's quiet box with the same reference/candidate and selected geometry
in both passes. Preserve `results.json` in both the requested output directory and
its `-epoll` sibling. Require all 32 epoll IDs in full mode, both A/B server argv
ending in `--net-io epoll`, complete original workload/accounting evidence, and the
unchanged per-cell ABBA validity/comparison decisions. The decision remains the
existing per-cell rate comparison at its measured load, never an average over cells.
This lane makes no throughput or epoll-versus-uring performance claim.

Epoll has separate load/null identity. `GATE_ABBA_EPOLL_NULL` selects its own
control; the default is `.gate-history/receipts/baselines/epoll-null.json`.
An absent or mismatched control leaves comparison evidence untrusted and returns
nonzero. The old uring null cannot certify an epoll row: the file SHA and parsed
server_flags differ. The existing headline receipt retains its frozen inventory;
the coordinator's combined status additionally requires the epoll pass to succeed.
The epoll raw report must be retained separately; the old receipt is not a new
213-cell inventory or a promoted epoll standing-null campaign.

An existing instrument limitation is retained explicitly: persisted load-floor
validation accepts the base shape keys and optional data_bytes, but not the
server_flags key produced by srv=. A copied valid floor with the epoll shape is
rejected as `h01-epoll: invalid load-floor fields`; see
[floor-schema-control.txt](tests/gateprod-evidence/floor-schema-control.txt).
Therefore this lane does not import epoll pins or copy uring calibrations. The
new pass uses the existing unpinned search. Any later extension of persisted
floor/campaign schemas requires its own reviewed instrument revision/refreeze.
The frozen instrument can already consume a separately collected raw null with
matching cells, complete load ladder, geometry and environment.

**Verification retained:**

- `python3 tests/abba_instrument.py --self-test`: 7 unchanged controls pass.
- `python3 tests/abbagate.py --self-test`: 106 main controls plus its 10/9/16-test sub-batteries pass.
- `python3 tests/gates_test.py`: 66 gate wiring controls pass, including cleanup and dispatch.
- `python3 tests/gateprod.py --self-test`: 8 controls pass; all 64 cells × both arms have exact server and memtier argv checks.
- `python3 tests/gate_ledger_fixture.py` and `--self-test`: 517 source labels agree; 10 controls pass.
- `python3 tests/netio.py --self-test`: existing engine/counter substitution controls pass.
- `bash -n tests/gate.sh` and `git diff --check`: pass.
- Grep audit: every changed nonblank source line plus shared argv/fixture tokens searched throughout tests/;
  [changed-text-audit.json](tests/gateprod-evidence/changed-text-audit.json) records scope and matches.

The full gate, full ABBA product and performance measurements were not run.
The authorized live smoke reached only its refused preflight. No push was made.
`origin/cpp` was fetched and merged again before the final proof; see
[final-merge.txt](tests/gateprod-evidence/final-merge.txt).
[production.diff](tests/gateprod-evidence/production.diff) against origin/cpp is
empty and committed as evidence. Logs, matrix and proof artifacts have a digest
manifest in [SHA256SUMS](tests/gateprod-evidence/SHA256SUMS).
