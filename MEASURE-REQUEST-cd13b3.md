Lane cd13b3 — correct the servertail unknown-ACLCAT expectation

Started on `cx-cd13b` at `f86eb0ecbfee6170c77fb155873cf83f1b76d5fc`.
The required first `git merge origin/cpp` returned `Already up to date`;
there is no new merge commit. The existing integration merge is
`8c8ffd6f0c8a0b4243a3706f4b8a1dd4ffedbd94`. No push.

Read item 2 of `MEASURE-REQUEST-cd13b.md` and the landing failure at
`build/gate-run.EtkplO/jobs/feature-armed-0/gate-fusedarmed-servertail-0.txt`:
111 checks ran, with only `FILTERBY unknown category` failing because its
expected error disagreed with the actual empty array.

Commit `67efb3f36` changes only that expectation in `tests/servertail.py:211`
to `[]`, the decoded Redis reply `*0\r\n` in both RESP2 and RESP3. A literal
source comparison with the starting commit, reversing just that replacement,
matches exactly: all other 110 checks and all battery plumbing are unchanged.
The existing raw-wire `aclcat_property` still checks exact bytes and requires
eight probes across target and oracle; no differential property was changed.

Search used `grep`, never `rg`:

```sh
grep -RInEi 'Unknown ACL category|FILTERBY|unknown.?category' tests docs --exclude-dir=__pycache__
grep -RInF 'Unknown ACL category' tests docs --exclude-dir=__pycache__
```

After the fix, the original tests/docs contain 16 remaining old-text matches:
three historical PRE-negative logs in `docs/cd13b/`, one explanatory reason
in `tests/cd13b_audit.py`, and six copies of that reason in each of
`docs/cd13b/audit.json` and `docs/cd13b/changed-bodies.md`. These document the
old implementation and its removal; none expects the old reply from POST.
They remain accurate and were preserved. All FILTERBY sites were reviewed,
including the following lines of multiline assertions; no other stale
`err_prefix` expectation exists. `tests/acl_categories.py:112` instead tests
the distinct `ACL CAT` command, whose unknown-category error remains valid.
No fixture was edited.

`taskset -c 112-127 make -j12` passed (`Nothing to be done for 'all'`).
The SHA-256 printed after make, unchanged from cd13b2, is:

```text
eda318b9e356d172ce116fc7d48db491d4260d6eb286b7a229a7ed83ce2f1d45  build/tomokv
```

Both production comparisons are EMPTY:

```sh
git diff 8c8ffd6f0c8a0b4243a3706f4b8a1dd4ffedbd94..HEAD -- src Makefile
git diff f86eb0ecbfee6170c77fb155873cf83f1b76d5fc..HEAD -- src Makefile
```

The requested gate invocation selects whole feature jobs plus the release
prerequisite, with one correctness slot, 16 shards and split ratio 6:2:

```sh
GATE_ONLY_JOBS='feature-split-0 feature-split-1 feature-armed-0 feature-armed-1' \
REDIS74_ROOT=/home/user/Projects/redis74 \
taskset -c 112-127 tests/gate.sh iteration \
  --server-cores 112-119 --load-cores 120-127 \
  --server-smt '' --load-smt '' --ports 18340-18342
```

All four requested rows are **ok**, with **111 checks / 0 failures** each:

| Job | Servertail receipt |
| --- | --- |
| `feature-split-0` | [split, atomic 0](docs/cd13b3/servertail-split-a0.log) |
| `feature-split-1` | [split, atomic 1](docs/cd13b3/servertail-split-a1.log) |
| `feature-armed-0` | [fused+armed, atomic 0](docs/cd13b3/servertail-armed-a0.log) |
| `feature-armed-1` | [fused+armed, atomic 1](docs/cd13b3/servertail-armed-a1.log) |

Whole selected-job result: **139 ok / 0 FAIL**, exit 0. This includes the
release prerequisite and all batteries in the four selected feature jobs.
Both armed shutdown checks observed 557 lane hits. This is a partial gate,
with no EXPECT tally, ABBA, NIC or full-gate receipt. Artifacts:
`build/gate-run.QPPeKg`; retained [ledger](docs/cd13b3/gate-ledger.partial),
[transcript](docs/cd13b3/gate.log), and [CPU/port plan](docs/cd13b3/gate-plan.sh).

The header warns that `/home/user/Projects/redis74` is a binary-only tree
missing ACL-generator source files. The ACL-metadata job is not selected;
the requested jobs use neither those source files nor a Redis oracle.
For a gate invocation that includes ACL metadata, the source checkout is
`/home/user/Projects/redis`.

GEO proof: **4,951 ops / 0 diffs / 0 clock tolerances — PASS**, exit 0.
Both target and vanilla **Redis 7.4.10** returned exact `b'*0\r\n'` for the
unknown category. On each peer, the 22-command `string` result was unchanged
by `STRING` / `StRiNg` casing; the eight-probe non-vacuity guard passed. All three cross-owner
GEO store properties also passed. The target and oracle stopped cleanly,
with ports 18340 and 18341 free afterward.

The narrow runner
[`docs/cd13b3/run-geo.sh`](docs/cd13b3/run-geo.sh) extracts the unchanged
guarded boot, oracle identity and exact-PID cleanup from `tests/differ_gate.sh`.
It ran once, after the selected gate jobs finished, with target CPUs 112–119,
oracle CPUs 120–123 and client CPUs 124–127. It uses split, atomic=1,
16 shards, ratio 6:2, seed 7 and RESP3, complementing the RESP2 servertail rows.

```sh
taskset -c 112-127 bash docs/cd13b3/run-geo.sh
```

The oracle binary was `/home/user/Projects/redis74/src/redis-server`, SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.
Receipts: [boot, identity, properties, verdict and cleanup](docs/cd13b3/geo-live.log),
[executed-command coverage](docs/cd13b3/geo-resp3.coverage.json).
The runner refuses an existing `build/cd13b3/geo` output directory, so preserve
or move that directory before a subsequent reproduction.

Rows **+0 quick / +0 full**. The existing split and armed collectors at
`tests/gate.sh:3252` and `:3257` precede the quick-tier exit at `:3355`.
No row was added or retired; **EXPECT_QUICK=500 / EXPECT_FULL=517** and all
fixtures remain unchanged. This is a correctness-only test expectation fix;
no performance arm or PAD is needed.

Python AST syntax, the exact source comparison, proof-runner shell syntax,
and `git diff --check` all passed. The final binary hash remains the one
printed after make above. No further measurement is requested for this lane.

Additional receipts: [make](docs/cd13b3/make.log),
[SHA-256](docs/cd13b3/tomokv.sha256),
[unchanged-check and production-source proof](docs/cd13b3/source-proof.log).
