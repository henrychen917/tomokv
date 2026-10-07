# exbatch-bench4: explicit arms on landed mainline

Delivered on `cx-exbatch3`, worktree `/home/user/Projects/cx-exbatch3`, starting
at `8f2cc881f`. Fetched `origin/cpp` and ran `git merge --no-edit origin/cpp`:
already up to date with `649116c91`, which contains the exbatch landing.
Implementation and rebuild evidence: `05cf1fd2c`. No push.

`--arms RECEIPT.json` **replaces** the frozen binary table for the run. It uses
the `tools/lb_episodes.py` entry shape:

```json
{
  "PRE": {"path": "/absolute/path/or/receipt-relative/path", "sha256": "64 lowercase hex digits"},
  "POST": {"path": "/absolute/path/or/receipt-relative/path", "sha256": "64 lowercase hex digits"}
}
```

PRE and POST are required; PAD-A, EX1-OLD, EX3-OLD and EX6-OLD are optional.
Relative paths resolve against the receipt directory, not the launch directory.
Duplicate fields, unknown arms, malformed hashes, missing/nonexecutable binaries
and any SHA mismatch refuse the run, including `--dry-run`. Supplied receipts
never trigger a build or substitute an arm from the frozen table.

`results.json` schema 2 records `arms_receipt.path`, `arms_receipt.sha256`,
`framing`, the bound binary identities and `unavailable_arms`. Comparisons that
need an omitted control have `status: "not available"`, `missing_arms` and a
reason, with the same explicit marking in `rows` and `endgame.txt`; they have
no fabricated metrics. Measured comparisons have `status: "measured"`.
Consumers must check status before accessing `left`/`right`. Available binaries
are still copied and SHA-verified before scoring. Without `--arms`, the original
frozen-table behavior and its strict POST identity check remain.

## Mainline framing (b): landed headline versus pre-landing headline

Use the committed [mainline receipt](docs/exbatch/mainline-arms.json):

| Arm | Binary in `/home/user/Projects/bench-bins/` | SHA256 |
| --- | --- | --- |
| PRE | `tomokv-headline-07023fd6e` | `6d93912f846b105cebdb13585ca95232d73726a83bf5b144e2876fa7ce564fd6` |
| POST | `tomokv-headline-1055409c2` | `d240f213046bfd65a920d5dc0eec96609cbd387746836851d693111213759f4a` |

Both binaries exist here and both hashes were checked. This compares the landed
headlines and carries **every landing between the two revisions: only exbatch
here**. The first-parent history contains the reference-pin update `ca6a3bc03`
and the exbatch merge `1055409c2`. It has no PAD or EX-OLD controls and cannot
separate EX6 from the other exbatch changes or distinguish mechanism from code
layout. These exact binary hashes select `framing=mainline`, and **every endgame
row includes** `headline 07023fd6e -> 1055409c2; includes every landing between
them (only exbatch); no PAD/EX-OLD controls`. Other supplied identities are
labeled explicit unless they match the original six lane arms.

After this tool change is merged into mainline, run these commands sequentially
on the scheduled quiet box, using new output directories:

```bash
cd /home/user/Projects/cx-final
taskset -c 0-111 python3 tools/exbatch_directed.py --arms docs/exbatch/mainline-arms.json --cell exbatch_xgroup32 --regime f0 --blocks 1 --output build/exbatch-directed/mainline4-headline-f0x
taskset -c 0-111 python3 tools/exbatch_directed.py --arms docs/exbatch/mainline-arms.json --cell exbatch_xgroup32 --regime s0 --blocks 1 --output build/exbatch-directed/mainline4-headline-s0x
```

Each regime has **16 fresh-server samples**: plateau and matched passes, each
with PRE/PRE nulls then PRE/POST ABBA. It retains eight comparison rows across
the two passes: **two measured PRE/POST rows and six “not available” rows**
(PRE/PAD-A, PAD-A/POST and EX6-OLD/POST in each pass). EX1-OLD and EX3-OLD are
also listed in `unavailable_arms`, although xgroup32 does not schedule their
comparisons. The common per-connection target is
`floor(0.8 * min(mean PRE plateau, mean POST plateau) / 512)`; no absent PAD
value enters the target.

## Lane framing (a): original six frozen arms

**Reproduction succeeded on this box: all six whole-file SHA256 values match
the original receipts exactly.** See [rebuild evidence](docs/exbatch/rebuild-bench4.json).

The old `binaries.json` recorded only PRE's source commit, and the control
`proof.json` files recorded binary identities but no source commit. Git history
locates their first complete receipt commit at
`d1687d34d2a94b53ae490abd3cac66022dc1daa4`. Its `src/`, `third_party/` and Makefile
are identical to `dd832b807878c89c69066681ac6f3eddfa144080`, the last server/build
source change before the receipt. Archiving **d1687d34d reproduces the exact
POST**, establishing a usable source revision without guessing an unrecorded
historical working-tree HEAD. PRE remains
`cd02ecbab1502775f1c170e806971d1f7bbc3ee9`.

[tools/exbatch_rebuild_arms.py](tools/exbatch_rebuild_arms.py) archives these
commits into a new directory under this worktree's `build/`. It requires the
recorded GCC 13.3.0 version and builds with the archived Makefiles, their
per-object flags, and `-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`,
jemalloc enabled, on CPUs 112–127 with 16 jobs. A `-fdebug-prefix-map` maps each
new compilation directory to its recorded original directory so DWARF paths
also reproduce. It does not edit sources or write into the deleted lane path.
The source/build provenance is now recorded in
[binaries.json](docs/exbatch/binaries.json); original build flags remain
auditable in `final-build.log.gz`, `pre-build.log.gz` and `build-and-checks.json`.

The tool verifies POST's SHA before applying the frozen `planned-retargets.json`
patches, checks each original five-byte site and every resulting control SHA,
and verifies PRE's whole-file SHA. It writes `arms.json` only after all six
identities match. A failed rebuild writes `rebuild.json` with its error and
issues no usable arms receipt; it does not relax the hash check.

| Arm | Rebuilt SHA256 |
| --- | --- |
| PRE | `5c2a0626ed3b3c73f3dae41c39c6beb412df795d42efd8de55b64812c9f62858` |
| POST | `410da97a4e6f851646773c8b863a867dd6c355ed79222d1ab16c08e4f5c38359` |
| PAD-A | `1a8411f96fbb3ff40e088a511255fdd506bf17c46825d529647b0b5f7801876b` |
| EX1-OLD | `2068ea2dafa5fa60e0afc89f0e171f0bee9c0d952f0242fa1d0b799c1dec82ff` |
| EX3-OLD | `d9cb457aab8f95f567f279e695e861720f0b34aa549569e05b3938cd57e4df1f` |
| EX6-OLD | `f27303fd5ee265427b1744a51ade195966f58c8a16ff2942307dc11c375c1ac9` |

The completed rebuild took 134.6 seconds. Its receipt and logs are under
`/home/user/Projects/cx-exbatch3/build/exbatch-bench4-lane/`. The receipt SHA256
is `f6cd299b5eb4c5453705c09819770556498d4bdd60f712ddf4bd43b4b798e279`.

**PAD-A is kind A: a behaviour twin, PRE behaviour at POST text size/function
layout. EX1-OLD/EX3-OLD/EX6-OLD are kind-A partial controls, each restoring its
selected old item at POST layout.** PRE/POST measures the original combined
lane change; PRE/PAD-A measures its layout component; PAD-A/POST compares all
three mechanisms at the same layout; EX6-OLD/POST isolates EX6 at POST layout
for xgroup32. This is the original lane baseline, not the landed headline pair.

The already rebuilt receipt can be used from mainline without touching its
ordinary `build/tomokv`:

```bash
cd /home/user/Projects/cx-final
taskset -c 0-111 python3 tools/exbatch_directed.py --arms /home/user/Projects/cx-exbatch3/build/exbatch-bench4-lane/arms.json --cell exbatch_xgroup32 --regime f0 --blocks 1 --output build/exbatch-directed/mainline4-lane-f0x
taskset -c 0-111 python3 tools/exbatch_directed.py --arms /home/user/Projects/cx-exbatch3/build/exbatch-bench4-lane/arms.json --cell exbatch_xgroup32 --regime s0 --blocks 1 --output build/exbatch-directed/mainline4-lane-s0x
```

If this lane directory is retired, regenerate the same six identities in
mainline with the following serverless command, then use
`--arms build/exbatch-bench4-lane/arms.json` in both invocations above:

```bash
cd /home/user/Projects/cx-final
taskset -c 112-127 python3 tools/exbatch_rebuild_arms.py --output build/exbatch-bench4-lane
```

The rebuild destination must be new. Lane framing retains **40 fresh-server
samples and eight measured endgame rows per regime**: two passes, each with
PRE/PRE nulls plus PRE/POST, PRE/PAD-A, PAD-A/POST and EX6-OLD/POST ABBA. Its
matched target still uses the primary PRE/PAD-A/POST plateaus only.

## Geometry, decision and validation

Both framings use server CPUs 0–7, 16 shards, f0 fused/read-local=0 or s0 split
6:2/read-local=0; eight memtier instances on CPUs 8–111, 512 connections and
pipeline 32. Require `results.json.complete == true`, exact zero-reply guard/HDR
reconciliation and accepted quiet blocks. The >2% same-arm plateau refusal,
productive occupancy requirement, achieved-rate limits and 0.5% matched-arm
mean-rate limit are unchanged. Mainline judges matched-load rate with cycles/op,
instructions/op and IPC, plus the plateau rates and collected same-binary nulls.
Do not pool the two framings or claim EX6 isolation from the headline pair.
No performance result is claimed here; append measurements and artifact paths
as `MEASURE-RESULT` after the scheduled runs.

Completed serverless validation on CPUs 112–127:

```bash
taskset -c 112-127 python3 tools/exbatch_directed.py --self-test
taskset -c 112-127 python3 -m py_compile tools/exbatch_directed.py tools/exbatch_rebuild_arms.py
git diff --check
```

**37 tests passed, no skips**: 35 Python tests, the memory-only native preload
exec fixture and the existing local perf-window test on CPUs 112/120. New
controls cover receipt-relative binding, receipt mutation, binary SHA mismatch
in real/dry preparation, missing/nonexecutable binaries, malformed/duplicate
receipts, the CLI dry run, SHA-bound framing text, and mocked complete campaigns
with PRE/POST, optional PAD-A, optional EX6-OLD and all six arms. The campaigns
check result/row skip markers, available-arm scheduling and plateau selection;
partial controls cannot lower the matched target. They start no server.

Real `--dry-run --arms ... --cell exbatch_xgroup32 --regime {f0,s0} --blocks 1`
invocations passed for both receipts. Each read the real binaries and executed
only memtier `--help`; every workload command was printed. All four requested
output directories remain absent. The plans contain 16/16 mainline and 40/40
lane samples, correct f0/s0 geometry, and 6/6 versus 0/0 unavailable rows.
[Dry-run evidence](docs/exbatch/dry-run-bench4.json) records the plan log hashes;
logs are in `build/exbatch-bench4/`, with the self-test log at
`build/exbatch-bench4-self-test.log`.

No server, benchmark workload, or gate was run. No server code or layout changed.
Gate row delta is **0 quick / 0 full**; `tests/gate.sh`, `EXPECT_QUICK` and
`EXPECT_FULL` were not edited. All changes are committed on the lane branch;
the maintainer measures, gates and merges.
