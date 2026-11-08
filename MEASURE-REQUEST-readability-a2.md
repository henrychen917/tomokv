## readability-a2

Branch `cx-readability-a2`, source baseline `52dbad6c9e470b42725b015303de6ce86ca1a57a`.
Production reference: `/home/user/Projects/bins/readability-pre-5c363128/tomokv`, supplied by
the maintainer and never rebuilt. No throughput measurement or new PAD arm is requested.

### Result

The production binary remains identical under the supplied binary-neutral checker:

```text
IDENTICAL (11167504 bytes after stripping)
```

The one reformat commit is `d56f71656f15f008646521c795398355f36822c9`
(`format: apply clang-format to the tree`). The immediately following commit,
`c880e69816`, adds that hash to `.git-blame-ignore-revs`. Configuration, generator/tool
fixes and proof drivers are separate commits. No push was performed.

### Measured style and choice

The reproducible measurement is [measure_style.py](docs/readability-a2/measure_style.py).
It reads the frozen Git blobs, excludes generated regions, blanks comments/literals for
syntax heuristics, and records physical line lengths with tabs expanded to four columns.
Percentiles use the nearest rank. These are lexical style samples, not AST classifications.

| Property | All 418 eligible files | 199 production files | Configuration |
|---|---|---|---|
| Block indentation increase | 4 spaces: 15,338/16,120 samples | 11,857/11,902 | `IndentWidth: 4` |
| Control/function opening braces | Attached: 20,026/20,029 | 14,849/14,851 | `BreakBeforeBraces: Attach` |
| 95th-percentile physical line length | 97 columns; also 97 excluding blanks | 96; 97 excluding blanks | `ColumnLimit: 100` |
| Pointer declarations | Left: 5,603/5,670; right 44, middle 2, neither 21 | Left: 4,006/4,029 | `PointerAlignment: Left`, no derivation |
| Access labels relative to class indentation | Same column: 237/241 | 211/213 | `AccessModifierOffset: -4` |
| Namespace body indentation | No additional indent: 462/462 | 285/285 | `NamespaceIndentation: None` |

The candidates share those overrides, a four-space continuation indent, and the required
token-preserving settings. They also disable using-declaration sorting, namespace-comment
insertion and raw-string language formatting. `X` is declared a statement macro: without
that grammar hint, clang-format 18.1.8 repeatedly reshapes the string-handler X-macro table.
The final candidate comparison verifies a fixed point for every file.

| BasedOnStyle | Changed files | Added lines | Removed lines | Total changed lines | Token/literal/fixed-point exceptions |
|---|---:|---:|---:|---:|---:|
| LLVM | 406 | 65,108 | 41,979 | 107,087 | 0 |
| **Google (selected)** | **397** | **49,063** | **33,570** | **82,633** | **0** |
| WebKit | 410 | 72,128 | 49,203 | 121,331 | 0 |

These counts compare identical protected inputs before regenerating the R7 copies.
The final reformat, including generator-owned layout refreshes, is **397 files,
51,843 added / 36,287 removed lines**: 185 production files, 198 tests and 14 tools.
Google is the smallest consistent candidate. [Comparison driver](docs/readability-a2/compare_formats.py).

### Formatter contract and exclusions

[.clang-format](.clang-format) retains `SortIncludes: Never`, `BreakStringLiterals: false`,
`InsertBraces: false`, `QualifierAlignment: Leave`, and `ReflowComments: false`.
The exact pip package is **clang-format==18.1.8**, installed in the venv
`build/clang-format-18.1.8/`. `make format`, `make format-check` and `make format-setup`
use that environment, check its package and executable versions, and never use PATH's
formatter. Installation uses system pip's `--python` option because this box lacks
`ensurepip`; no system package installation was necessary.

The sorted manifest [tools/format-files.txt](tools/format-files.txt) contains 418 maintained
C/C++ files: 199 under `src/`, 205 under `tests/`, 14 under `tools/`. The driver reads only
that list and prints offending filenames in order. New maintained files must be added to
the list. `third_party/`, `src/third_party/`, archived tools, historical `docs/` source
snapshots, scratch directories and calibration experiments are excluded.

The generated-header inventory found exactly these three whole generated files; none is
formatted or checked by clang-format:

- `src/cmd/cmddocs_generated.inc`
- `src/cmd/cmdmeta_generated.inc`
- `src/cmd/acl_categories_generated.h`

The R7 blocks in `src/core/reorder.cc`, `src/core/io_loop.h` and `src/core/ex_loop.h`
have `// clang-format off/on` immediately outside their existing BEGIN/END markers.
The formatter handles the handwritten inputs first, then invokes
`tests/r7shadow_sync.py --write`. Generated output is never hand-formatted. Both sync
entry points pass on POST, and `make format-check` includes the generator's check mode.

No literal-bearing file needed exclusion. [The full audit](docs/readability-a2/source_proof.py)
uses A1's `tools/source_tokens.py` **raw `lex()` tokens**, without identifier normalization.
All **418 files / 1,372,256 preprocessing tokens / 23,935 literal tokens** match PRE,
including all 12 raw literals and the Lua/help strings in scripting/functions. Literal
spelling is also compared separately before splice normalization. Every `TOMO_TOOL_*`
comment remains at the same token boundary. There are **zero exceptions**. All **528**
generated/vendor/archive files audited separately remain byte-identical.

The final pinned configuration's `make format-check` passes POST and rejects a disposable
exact PRE source copy overlaid only with the new formatter tooling: **397 offending files,
make exit 2**. It does not write source in check mode.

### Text tools and gaps found

The A1 matrix passes **52/52 positives and 52/52 broken-anchor rejections** on both PRE
and POST. Both emit exactly **313 C++ files with identical normalized token hashes**.
This covers R7/reorder sync, all **62 lottery insertion sites** (source preparation only),
the source PAD checks, 41 WB controls, six flush sites, four WBLAND controls, nine LB
controls, three persistence controls, six applicable blockfix controls, metadata/docs
generators, SplitLocal, and the Makefile Climon/L4 token controls.

Explicit regeneration exposed two A1 generator gaps, fixed in the tools:

- `--write` previously did nothing when tokens matched, leaving stale generated layout.
  Explicit writes now refresh layout; unchanged output retains its mtime. The existing
  R7 regression test checks both cases.
- The pinning helper was copied with its ordinary `TOMO_TOOL_BIND`, adding an extra
  generated binding. It now uses the same marker-stripping path as the other copied
  helpers. Marker removal handles actual comments and does not leave trailing spaces.

The A1 proof driver also assumed CPUs 64–95 and hashes newly emitted files by mtime.
The [A2 adapter](docs/readability-a2/prove_tools.py) passes the active authorized CPU mask
and clears only disposable output trees before each run. The initial run's flush-reference
case refused the wrong mask; the complete reruns pass. No production formatting was
reverted or special-cased to accommodate a text matcher.

The pre-existing optional historical blockfix rename campaign and L4 runtime failure
documented by A1 are outside this formatting proof; their assertions were not changed.
No historical benchmark/PAD campaign was replayed. Existing PAD controls exercised here
are **kind A behaviour twins**, with their original scope and assertions.

### Build and gate proof

All builds and boots use `LC_ALL=C`; production builds pin:

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
taskset -c 0-31 make -j16 all
taskset -c 48-63 /home/user/Projects/calib/binary-neutral.sh \
  /home/user/Projects/bins/readability-pre-5c363128/tomokv build/tomokv
```

GCC is 13.3.0, with the unchanged production flags and link order. `make all` produces
only `build/tomokv` as an executable, plus its assertion map. The frozen PRE was not built.

Completed independent checks:

- `python3 tests/gates_test.py`: **83 tests, OK**.
- Label-fixture unittest: **12 tests, OK**; **1,229 declared labels**, **1,230 fixture rows
  including NIC**. `tests/gate.sh` and the fixture are unchanged. `EXPECT_QUICK=1212`,
  `EXPECT_FULL=1229`, and the quick-tier boundary are unchanged; row delta is zero.
- Lottery runner/AST checks: **20 tests, OK**; A1b caller-inventory controls: **14 tests, OK**.

Selected runtime jobs and the production-unit build/freshness inventory are still running
at this report checkpoint. Their final results and receipts will replace this paragraph.
The job runner selects A1's previous jobs plus the three A1b caller jobs, with server CPUs
0–31, load CPUs 32–47, no SMT, ports 25100–25198, and `GATE_TEST_PORT=25199`. Each ordinary
boot retains the gate's eight-core, 16-shard, 6:2 geometry. `GATE_PROOF_NO_RATES=1` is used
only with selected partial jobs. No full iteration, ABBA, NIC or throughput benchmark runs.

Reproduction helpers: [gate selection](docs/readability-a2/run_gate.py),
[build/freshness inventory](docs/readability-a2/build_proof.py), and
[formatter usage](docs/readability-a2/README.md). Large build logs and binaries remain
under `build/readability-a2/` and the recorded gate-run directory; no file over 1 MB is committed.
