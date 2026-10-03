# rlfence3 — production ALT spelling after the required mainline merge

`taskset -c 112-127 make -j16` now builds `build/tomokv` with the measured
ALT spelling and compiler/section settings. The fence witnesses, serverless
harness replays, generated-code negative controls, and ELF verifier controls
pass. No server, load generator, benchmark, gate, or push was run.

**The merged binary is not byte/address-identical to frozen ALT.** Frozen ALT
was built from `7dc81148e`; the required merge contains newer parser, TLS,
storage and command fixes. The exact verifier reports the differences rather
than certifying a false match. Every differing function is listed below in
machine-readable receipts. In particular, the merged build's h05 loop-head
alignments differ. The historical ALT null is not a null for this new binary;
mainline must run the new 14-cell comparison requested below.

Worktree/branch: `/home/user/Projects/cx-rlfence`, `cx-rlfence`.
Read both earlier requests first. Fetched and merged `origin/cpp`
`068fdb816d63d9adf4bbfd2aa5a11d57cd7c4615` in **2933f0a5c** before editing.
The merge was clean and retained both sides' additive test/build entries.
Production implementation: **d64c65d37**; verifier/proof receipts:
**b73ae89d2**. All work is committed locally; nothing was pushed.

## Mainline verdict checked before implementation

`/home/user/Projects/PLAN-SERIAL.md:2398`, 2026-10-04 00:57, logs exactly the
quoted verdict. The earlier 2026-10-03 rows and the final verdict are preserved
in [mainline-verdict.txt](docs/rlfence2/production/mainline-verdict.txt).

| h05 arm | Mainline deltas | Mainline verdict |
|---|---|---|
| Original POST | −2.79 / −2.32 / +2.05 / −2.85%; median −2.55% | Layout attribution required |
| Frozen ALT vs pinned `b47544aad` | +0.52 / +1.52 / +0.52 / +1.50%; median +1.01% | Within band |
| Old behavior, POST layout | −1.61% | Tracks POST layout |
| Old behavior, ALT layout | +2.21% | Tracks ALT layout |

Mainline records the other cells within their bands. Read-local-off GET cannot
execute the changed statement. These are mainline's measurements, not new lane
measurements; the earlier requests retain the historical trust/spread caveats.

## Production settings and semantic scope

The normal Makefile's db0 `src/core/genthread.o` rule now has:

```make
--param inline-unit-growth=0 --param large-unit-insns=128873 -Wa,--defsym,tomo_rlfence_text_pad=16
```

This is the measured ALT rule: the large-unit budget was 128880, and the
assembler definition adds 16 unexecuted NOP bytes in `.text.rlfence_pad`, which
the normal linker incorporates into `.text`. All other production TU flags,
link ordering and linker flags are unchanged. GCC is Ubuntu 13.3.0; GNU ld 2.42.

`src/net/rob.h` takes the exact ALT instruction spelling from
`docs/rlfence2/alt.patch`, apart from its explanatory comment. For x86-64/BMI
and `Rob<64>`, the pending-mask ANDN becomes a same-width five-byte jump into
`.rlfence`. Each island tests the covered MGET fence, conditionally stores the
sentinel, performs the same ANDN, and jumps back. The four COMDAT-inherited
islands occupy 112 bytes; all four parent completion helpers remain 294 bytes.
The inline assembly declares the fence memory operand, temporary register and
condition-code clobbers. It touches no stack. Other targets/capacities keep the
existing C++ implementation.

This changes instruction spelling and placement, not the completion contract.
The covered fence still clears before Done publication/parser resumption; an
uncovered fence survives. Pending-slot/filter cleanup finishes in the same
owner-local call, with no intervening observer. No retry, lock, field, runtime
knob or allocation is added. The sole source difference from merged mainline
is `src/net/rob.h`; its implementation matches the frozen ALT header after
removing comments/whitespace. See
[source-receipt.json](docs/rlfence2/production/source-receipt.json).

Both database variants and all split/fused production TUs compiled with the
existing locks intact:
`Op 336 / Client 1984 / ThreadCtx 1408 / Shard 1440 / FlatStore 944 /
Rob<64> 192 / AtomicEntry 144 / Config 624`.
Build evidence is [default-build.log.gz](docs/rlfence2/production/default-build.log.gz).
This is compilation evidence, not live boot evidence.

## Exact identity result and complete difference inventory

| Artifact | Frozen ALT | Newest headline at build (`068fdb816`) | Production `build/tomokv` |
|---|---:|---:|---:|
| `.text` bytes | 7,554,609 | 7,709,921 | 7,710,177 |
| `.rlfence` bytes | 112 | 0 | 112 |
| Defined function table entries | 10,028 | 10,181 | 10,182 |
| Literal function entries differing from production | 10,198 | 5,688 | 0 |
| Normalized IO/GET bodies equal to production | 165/334 | 350/362 | — |

Difference counts use the union of both inventories, so additions/removals can
make the count exceed either table's size. Duplicate symbol names are retained
and paired by address order. The literal comparison masks no displacement,
opcode, padding or executable section byte. Normalized IO counts are reported
separately and do not establish byte identity.

The compulsory merge alone makes frozen ALT's exact instruction bytes
incompatible with current source: the h05 GET parser now has the upstream
query-buffer checks, and the fused flush body also differs. Replacing those
bodies with old bytes would undo mainline work. Retaining ALT's exact settings
and assembly is therefore the production recipe; no further source change or
unmeasured compiler-budget search is adopted.

| h05 function | Frozen ALT address / size | `068fdb816` address / size | Production address / size |
|---|---|---|---|
| db0 fused `run_loop` | `0x3241d0` / 5,011 | `0x325260` / 5,011 | `0x32ac00` / 5,011 |
| db0 fused `flush_ready` | `0x3235d0` / 3,062 | `0x3249a0` / 2,238 | `0x32a340` / 2,238 |
| db0 GET `parse_and_dispatch` | `0x312be0` / 19,296 | `0x313d60` / 19,592 | `0x313d70` / 19,592 |

All three production bodies retain the newest headline's normalized
instructions. They do not retain its literal bytes/addresses. Principal static
loop heads (not a sampled profile):

| Loop | Frozen ALT address (mod 64) | Production address (mod 64) |
|---|---|---|
| `run_loop +0x90` | `0x324260` (32) | `0x32ac90` (16) |
| `flush_ready +0x70` | `0x323640` (0) | `0x32a3b0` (48) |
| Next-frame parser loop | `0x312d90`, +0x1b0 (16) | `0x313f10`, +0x1a0 (16) |

The existing strict h05 verifier still passes for frozen PRE → frozen ALT. It
rejects frozen ALT → production at **`h05 layout moved`**; this failure is
recorded in [frozen-alt-identity-limit.json](docs/rlfence2/production/frozen-alt-identity-limit.json).
No claim that production inherits frozen ALT's layout or performance is made.

Complete receipts under `docs/rlfence2/production/`:

- [ALT identity summary](docs/rlfence2/production/alt-identity/identity.json),
  [every differing function, TSV](docs/rlfence2/production/alt-identity/differing-functions.tsv.gz),
  [same list with body hashes, JSON](docs/rlfence2/production/alt-identity/differing-functions.json.gz).
- [Newest-headline identity summary](docs/rlfence2/production/headline-identity/identity.json),
  [every differing function, TSV](docs/rlfence2/production/headline-identity/differing-functions.tsv.gz).
- Both identity directories retain complete reference/candidate function and
  section tables. The summaries inventory every backward-branch target in the
  three h05 functions, with offsets and mod-16/mod-64 placement.
- `alt-io-audit.json.gz` / `headline-io-audit.json.gz`, `*-io-changes.json` and
  `*-io-diffs.txt.gz` retain all normalized comparisons and failing disassemblies.

Production whole-file SHA-256:

```text
2b51893af7dc9a1071db5a0bd07f329c3e02df938789a46599bafd7cbf9fc8c8  build/tomokv
```

Production `.text` SHA-256:
`4b71ba4076af17652a59f0a3e09e348c5ea5bc567eb4ab798be7c91fb7175d6e`.
The complete function-table SHA-256 is
`185091abdd1651793190c3d40bff28dc3a23ae3a0dc79d6a339f3a65f7bb30f4`.

## Serverless witnesses and verifier controls

All builds, binary inspection and witness execution used cores 112–127.

| Check | Result |
|---|---|
| Normal `make -j16`; subsequent default make | Success; second invocation has no work |
| `build/rlfence-unit` | All three completion sites; 128 positions; mixed/empty masks; p8=8 and p32=32 before retirement; RYOW retained |
| `build/read-local-write-ring-unit` | Pass, including four 200k-frame soaks |
| Same fence unit compiled with `-mno-bmi` | Portable C++ fallback passes |
| Generated unit ELF with covered-store branches bypassed | Expected symmetry failure; independent pipeline failure at `N=8 lane_completions=1 retired=0` |
| `mget-fence` Python replay | p8/p32 pass, checks=2, skips=0 |
| `mget-fence-old`, `-unarmed`, `-stale` | Expected failures: 1-vs-8 hits; three fresh arms exhausted; wrong ordered/RYOW replies |
| Existing `transient`, `delayed-drain` replays | Pass |
| Gate source inventory and `bash -n` | Three fence rows reachable; syntax passes |

`tools/rlfence_artifacts.py pad` independently inventories the production
ELF's four islands, including entry/return pairing and the entire section.
Its **A: behavior twin** verifier control changes exactly four branch bytes;
restoring the planned bytes reproduces the complete production file. All
10,182 function entries, section descriptors and other bytes are identical.
Missing-retarget, moved-symbol and unrelated one-byte controls fail at their
designated assertions. The unit ELF's corresponding five-island control has
the same proof and is the negative binary actually executed above.

These are offline verifier/unit controls, not requested measurement arms.
The server-shaped control and all corrupted `*.NEVER-RUN` files are
nonexecutable. Receipts:
[server-control/proof.json](docs/rlfence2/production/server-control/proof.json),
[unit-control/proof.json](docs/rlfence2/production/unit-control/proof.json),
[unit-negative-controls.json](docs/rlfence2/production/unit-negative-controls.json).
Each directory includes `planned-retargets.json`, complete compressed address
tables and `negative-controls.json`.

The source/call proof binds to **d64c65d37**, accounts for two completion sites
in each of four instantiations, and verifies all eight calls reach the island
helpers: [closure.json](docs/rlfence2/production/closure.json).
The new literal `identity --require-equal` check passes on production against
itself and rejects the moved-symbol and one-byte corruptions:
[identity-controls.json](docs/rlfence2/production/identity-controls.json).

Serverless reproduction (no server ELF is executed):

```bash
taskset -c 112-127 make -j16
taskset -c 112-127 make -j16 build/rlfence-unit build/read-local-write-ring-unit
taskset -c 112-127 build/rlfence-unit
taskset -c 112-127 build/read-local-write-ring-unit
taskset -c 112-127 python3 tests/read_local_lane.py --self-test mget-fence
taskset -c 112-127 python3 tools/rlfence_artifacts.py verify \
  build/tomokv build/rlfence3/server-control/tomokv \
  docs/rlfence2/production/server-control/planned-retargets.json
taskset -c 112-127 python3 tools/rlfence_artifacts.py identity \
  build/rlfence-alt/tomokv build/tomokv build/rlfence3/recheck-alt
taskset -c 112-127 sha256sum -c docs/rlfence2/production/SHA256SUMS
taskset -c 112-127 sha256sum -c docs/rlfence2/SHA256SUMS
```

## Retired study interface and gate accounting

The Makefile at lane launch and after the merge already had **no**
`rlfence-pad`, `rlfence-alt` or `rlfence-alt-pad` targets: rlfence2 built them
through the offline tool and its archived overlay. There were no such targets
to delete. They remain absent; the normal build needs no overlay command,
alternate BUILD_ROOT or runtime switch. The frozen binaries and their proof
receipts stay under `build/` and `docs/rlfence2/` for reproducibility.

The historical POST checksum now names the already byte-identical preserved
`build/tomokv-rlfence-post`, since `build/tomokv` is the new production binary.
All five historical checksums still pass; their values are unchanged.

rlfence3 adds zero gate rows. The complete rlfence lane retains these **three**
rows relative to merged `origin/cpp`:

| Row | Definition line in `tests/gate.sh` | Collection line |
|---|---:|---:|
| MGET fence symmetry unit | 1247 | `ring_unit`, 2848 |
| MGET fence battery (1s) | 1658 | `bplus`, 2909 |
| MGET fence battery (2s) | 1664 | `bplus`, 2909 |

All are before the quick-exit block at line **2990**. Delta: **+3 quick / +3
full**, so the maintainer-owned constants should become **462 / 479** from
**459 / 476** on this merged base. The source extractor counts 479 full rows.
`EXPECT_*` and the label fixture were not edited by this lane; the maintainer
must add these three labels to the fixture when updating the counts. Live
1s/2s battery and gate execution remain pending mainline.

## Mainline 14-cell null request — NOT RUN

Use the mainline instrument in `/home/user/Projects/cx-final` and the **newest
headline at execution time**, not rlfence2's pinned `b47544aad`. The newest at
this handoff is `tomokv-headline-068fdb816`, SHA-256
`c1461d1e6e7b31272b8af683b91fd96d2c751e1fc36f30d9cde2e319ea6cb38e`.
Other queued landings may advance it; record the chosen path and SHA.

Use the same 14-cell file, SHA-256
`de0e56e4696f780543c5adea21aa7d7283c12fa22110be6064370a69a2a68dc6`:
`h05,h06,p8g,p8s,d1g_l0,d1s_l0,d32s_l1,d8s_l1,d32g_l1,x9_32_l1,x9_32_l0,m8g_l0,v1g_l0,d128g_l0`.
Preserve its pins and depth-1 exemption, matched offered load, 20-second
windows, 2M keys, 512 connections, uring, atomic=1, overlap=1, reorder=0,
default balancers and save disabled. Server cores 0–31; load cores 32–111;
no SMT. h05 uses eight load instances and 256 shards, distinct from the
8-core/16-shard/6:2 correctness geometry.

```bash
(
  set -eu
  rlfence_lane=/home/user/Projects/cx-rlfence
  cd /home/user/Projects/cx-final
  rlfence_ref=$(python3 - <<'PY'
from pathlib import Path
print(max(Path('/home/user/Projects/bench-bins').glob('tomokv-headline-*'),
          key=lambda p: p.stat().st_mtime_ns))
PY
  )
  printf '2b51893af7dc9a1071db5a0bd07f329c3e02df938789a46599bafd7cbf9fc8c8  %s\n' \
    "$rlfence_lane/build/tomokv" | sha256sum -c -
  sha256sum "$rlfence_ref" "$rlfence_lane/build/tomokv" \
    > "$rlfence_lane/build/rlfence3-null-arms.sha256"
  python3 tests/abbagate.py --subset full --build-reference 0 \
    --cells "$rlfence_lane/docs/rlfence2/generic-merit-cells.txt" \
    --only h05,h06,p8g,p8s,d1g_l0,d1s_l0,d32s_l1,d8s_l1,d32g_l1,x9_32_l1,x9_32_l0,m8g_l0,v1g_l0,d128g_l0 \
    --reference-binary "$rlfence_ref" \
    --candidate-binary "$rlfence_lane/build/tomokv" \
    --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
    --ports 7933-7940 --port 7933 \
    --output "$rlfence_lane/build/rlfence3-null-newest" \
    > "$rlfence_lane/build/rlfence3-null-newest.log" 2>&1
)
```

The requested arms are the newest headline and production `build/tomokv`.
No study PAD is requested. The decision is the current mainline null/CONFIRM
protocol on **each** cell at matched offered load, including h05's unchanged
2.5% band. Do not average away a regression or transfer frozen ALT's +1.01%
verdict onto this merged ELF. Record rates, tails, spreads, validity/trust,
cycles/op, instructions/op and IPC where collected; retain invalid blocks and
use the existing confirmation policy. Append the result and exact arm hashes
to `MEASURE-RESULT-rlfence3.md` before deciding the landing.
