# exbatch-bench6: matched-only directed scoring

Branch `cx-exbatch3`, worktree `/home/user/Projects/cx-exbatch3`, 2026-10-07.
Implementation: `680bfde55`. Initial merge `468cc9f5c` incorporates
`origin/cpp` at `f053e5930`. Fetched and merged `origin/cpp` again before the
final proofs: already up to date. No push. Changes are confined to the directed
tool, its embedded tests, and this report. **Gate rows +0 quick / +0 full**;
no gate registration, expectation edits, production edits, or layout changes.

`--score matched-only --matched-load N` runs only the matched pass. `N` is
aggregate offered frames/s, and the existing integer per-connection rate
limiter uses `q=floor(N/512)`. `--matched-load` is required in this mode: the
inventory's automatic formula needs plateau measurements, which this mode
deliberately does not collect. No implicit load is guessed. Invalid or missing
loads, loads below 512, and an override without matched-only refuse before any
measurement. The default `--score plateau-then-matched` retains the existing
plateau derivation, acceptance rules, and byte-identical result rows.

The successful bench4 s0 headline receipt at
`build/exbatch-directed/mainline4-headline-s0x/results.json` records PRE plateau
548,204.1141167749 frames/s and POST plateau 4,027,578.1603481746 frames/s.
The existing formula gives `floor(0.8 * 548204.1141167749 / 512) = 856`.
Thus **438,272 frames/s was the offered load; 433,147.173 / 433,147.101 was
the achieved PRE/POST rate**. The proof and requested mainline runs below use
the explicit override `--matched-load 438272` to retain exactly that `q=856`.
Passing `--matched-load 433147` is also supported, but rounds down to `q=845`,
or 432,640 offered frames/s; it does not reproduce the old offered load.

Each matched pass first runs PRE/PRE null ABBA blocks. Every null block checks
the four individual `cycles / central workload frames` values, including both
repeats and both sides: `max(cyc/op) / min(cyc/op) <= 1.02`. The boundary is
inclusive. A disagreement refuses before any candidate runs, with:

```text
same-arm matched repeats differ >2%; arm=PRE cyc/op=100.000000/104.000000 spread=4.000000%; samples=[...]; recollect quiet block
```

Checking both null sides prevents two individually stable but displaced PRE
pairs from passing. Zero/nonfinite costs refuse. Each block is checked before
proceeding; extra blocks do not average away a failed null. The plateau
precondition remains unchanged for the default mode. The existing achieved-rate
bound (2% from offered target), inter-arm mean-rate bound (0.5%), quiet screen,
grouped PMU checks, and exact wire/HDR/state checks remain active.

`--blocks N` still means N ABBA blocks for the null and for each available
comparison. One headline matched-only block uses eight fresh-server samples
(four PRE/PRE, four PRE/POST), one measured row and three unavailable-control
rows. One lane block uses twenty fresh-server samples (the null plus four
comparisons) and four measured rows. All matched-only rows append
` plateau=skipped`. The existing `matched=` field remains per-connection `q`,
as in bench4; JSON additionally records requested and quantized aggregate
offered loads, `score`, and `plateau: "skipped"`. There is no plateau pass or
fabricated plateau result. Refusals retain `complete: false` and raw evidence.

`--cores SERVER_RANGE,LOAD_RANGE` defaults to `0-7,8-111`. It requires exactly
eight server CPUs and at least eight disjoint load CPUs. The override reaches
server/load tasksets, warm/verify/poll workers, the coordinator, guard builds,
fallback arm builds, quiet screening, PMU selection/validation, and role-to-CPU
validation. Connections, generator threads, pipeline, shards and split ratio
stay at the frozen recipe. With eight load CPUs each memtier instance gets one
CPU; a poll workload shares its final load CPU when no ninth CPU is available.

Both receipts remain byte-identical, including receipt-relative lane paths:

| Receipt | SHA256 |
| --- | --- |
| `docs/exbatch/mainline-arms.json` | `a30c0ca9d1446b565eb628947714f32ab930ea624add59fa971cdbd3111e41df` |
| `build/exbatch-bench4-lane/arms.json` | `f6cd299b5eb4c5453705c09819770556498d4bdd60f712ddf4bd43b4b798e279` |

Final serverless proof, after the second merge:

```bash
taskset -c 112-127 python3 tools/exbatch_directed.py --self-test
taskset -c 112-127 python3 -m py_compile tools/exbatch_directed.py
git diff --check
```

**42 tests passed, no skips**: forty Python tests, the native preload exec
fixture, and the existing local perf-window test. The Python suite prevents
unmocked child launches and socket connections. New controls exercise CLI
validation and quantization, CPU routing/PMU/role validation, matched-only dry
plans, successful synthetic campaigns, disagreement within a PRE pair and
between PRE pairs, an exact 2% boundary, rejection in the second null block,
nonfinite/zero costs, and unchanged rate guards/default acceptance rules.
The synthetic campaigns call the real CLI and scoring orchestration, verify
`--blocks 2` schedules sixteen headline samples, and prove a refused PRE null
never starts POST or emits a scored row.

Evidence in `build/exbatch-bench6/`:

- `self-test-final.log`: final 42/42 result and native/perf evidence.
- `default-compatibility.json`: all fifteen cells' default dry plan is
  byte-identical to `468cc9f5c` (5,347,749 bytes, SHA256
  `6c4f4c0b6eea1377c8f0f5fa547f3a3d9571d5ea697e16a39b3e545e05b75498`),
  as are 240 generated rows spanning cells, phases, comparisons and framing.
- `dry-runs.json` and `*-dry.log`: real receipt/binary/help validation for both
  framings in both modes. Default headline/lane plans have 16/40 samples;
  matched-only headline (one block) and lane (two blocks) have 8/40 samples.
  All four calls succeeded and created no requested output directory.
- `changed-text-patterns.txt` / `changed-text-audit.log`: recursive `grep`
  over `tests/` and `tools/` for changed string literals, raw lines, JSON and
  Python escape encodings (99 distinct patterns). No `rg` used.

The requested live proof command is:

```bash
taskset -c 112-127 python3 tools/exbatch_directed.py --score matched-only --matched-load 438272 --cores 112-119,120-127 --arms docs/exbatch/mainline-arms.json --cell exbatch_xgroup32 --regime s0 --blocks 1 --output build/exbatch-bench6/live-headline-s0-quiet
```

Live proof is pending a quiet window. Two attempts refused in quiet preflight
before starting a server: `live-headline-s0` observed 16.13 CPU-seconds against
the 0.48-second budget (a concurrent sixteen-way compile), and
`live-headline-s0-quiet` observed 0.90 against 0.48 after compilation finished.
Their logs and incomplete receipts are preserved. No measurement bound was
relaxed and no scored row is claimed for either refusal.

After landing the tool, MAINLINE runs these three previously refused cells
sequentially at the original geometry, using fresh output directories:

```bash
cd /home/user/Projects/cx-final
taskset -c 0-111 python3 tools/exbatch_directed.py --score matched-only --matched-load 438272 --cores 0-7,8-111 --arms docs/exbatch/mainline-arms.json --cell exbatch_xgroup32 --regime f0 --blocks 1 --output build/exbatch-directed/bench6-headline-f0
taskset -c 0-111 python3 tools/exbatch_directed.py --score matched-only --matched-load 438272 --cores 0-7,8-111 --arms /home/user/Projects/cx-exbatch3/build/exbatch-bench4-lane/arms.json --cell exbatch_xgroup32 --regime f0 --blocks 1 --output build/exbatch-directed/bench6-lane-f0
taskset -c 0-111 python3 tools/exbatch_directed.py --score matched-only --matched-load 438272 --cores 0-7,8-111 --arms /home/user/Projects/cx-exbatch3/build/exbatch-bench4-lane/arms.json --cell exbatch_xgroup32 --regime s0 --blocks 1 --output build/exbatch-directed/bench6-lane-s0
```

Server CPUs 0–7, load CPUs 8–111, 16 shards, 512 connections, pipeline 32;
f0 is fused/read-local=0 and s0 is split 6:2/read-local=0. The override fixes a
common offered target from the successful headline calibration; it makes no
capacity claim for any arm. Judge cycles/op at that matched load, with rate,
instructions/op, IPC and the retained PRE null evidence. Require
`results.json.complete == true` and all accepted blocks. Do not pool headline
and lane framings. The headline pair carries the exbatch landing as a whole;
the lane has the original controls. **PAD-A is kind A: PRE behaviour at POST
text size/layout. EX1-OLD/EX3-OLD/EX6-OLD are kind-A partial controls restoring
their selected old item at POST layout.** The lane's EX6-OLD/POST comparison
isolates EX6 at that layout.

The three mainline measurements and the gate are left to the maintainer.
