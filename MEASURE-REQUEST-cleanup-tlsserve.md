**cleanup-tlsserve — implemented and committed; production code is byte-identical to launch PRE. Live correctness is PENDING MAINLINE.**

The strict comparison passes **85/85 artifacts**: all 84 production objects and
`tomokv`. Every executable section, allocated data section other than the
DWARF-dependent build ID, relocation target/addend, symbol address, ELF entry
point and load mapping matches. The linked files themselves are **not identical**:
`.debug_info`, `.debug_line` and `.note.gnu.build-id` differ. No changed executable
byte is described as identical. Under the launch contract, production-code
identity discharges the performance null; **no PAD is required or supplied**.
No gain or measured rate/latency result is claimed.

No server, listener, worker loop, gate, benchmark, load generator, performance
measurement or push was run. All builds and serverless execution used
`taskset -c 112-127`; make used `-j16`. The serverless epoll fixture attempts
`send(-1)`/`sendmsg(-1)` and checks the deterministic attempted-send accounting;
its io_uring queue is in memory and never submitted to the kernel.

**Frozen reference and verified diagnosis.** The clean lane began on branch
`cx-cleanup-tlsserve` at staging SHA
`5b3d9c4292bf8b332d493beb485266ecc5a289aa`. The first action after inspection was
`git merge origin/cpp`, a clean fast-forward to launch PRE
**`2a9e484035960b0ba5925824cc581148c359c0f8`**. This incorporates the mainline
readreply cleanup. The launch note's reference-at-launch ruling applies; this
report does not relabel 5b3d9c429 as the built PRE. PRE was built and captured
before editing production source. `freeze/reference.tar`, `reference-sha.txt`,
`staging-sha.txt`, dependency files, tracked/resolved input hashes, toolchain and
build commands retain the exact reference and build inputs.

Rechecked PRE anchors, rather than relying on the 705cddec2 audit:

| Item | PRE anchor | Finding |
|---|---|---|
| Plain/kTLS template | `src/net/wb.h:785` | Shared retire/stage/accounting, with real `TlsNoBorrow` and `Coded` specializations |
| Userspace TLS template | `src/net/wb.h:878` | Same staging structure, but different release/CRLF order and final pump |
| TLS ciphertext predicate | `src/net/wb.h:943` | Must pump even with no plaintext queued |
| Public wrappers | `src/net/wb.h:204`–`:277` | Plain, kTLS/no-borrow, explicit TLS; ordinary serve and both preparation APIs; both tracking paths |

The audit missed a second observable distinction. Plain/no-borrow staging copies
the borrowed bytes, releases them, counts TLS suppression, then appends CRLF.
Userspace TLS copies, appends CRLF, releases, then counts suppression. A release
callback can observe the difference. Both orders are retained exactly. Both
bodies are **live duplicated logic**, not dead code, a constant-return stub, or
an incomplete mechanism that authorizes removing safety checks. In particular,
`tls.output_pending()` and the `Submit` guard are necessary behavior.

**Implementation and scope.** `src/net/wb.h:791` has the single authoritative
retire/stage/OOB/limit/accounting body. A local, immediately undefined source
macro expands that body into the existing C++ template/lambda contexts at
`:857` and `:874`. Existing `if constexpr` specializations remain in place.
The three transport fragments are the pre-retire no-borrow note, borrow/CRLF
sequence, and final pump statement. This deliberately retains the compiler's
existing entry points and inlining contexts. It is not an additional handwritten
implementation or a new runtime dispatch layer. Public signatures are unchanged;
plaintext acquires no TLS pointer, pointer load or mode test. `Submit=false`
compiles away either pump. `pump_tls`, cipher processing, zero-copy policy and
suppression serving are unchanged.

Expanded C++ token streams match PRE in both namespaces, including statement
order and template/lambda contexts (`expanded-tokens.json`). This is supporting
source evidence, not a substitute for the raw ELF comparison. The production
diff is confined to wb.h. Test integration is `tests/netcmd_unit.cc:9`, `:128`
and the test-only prerequisite at `Makefile:335`. Tests and proof generators
are `tests/tlsserve_checks.inc` and `tools/tlsserve_proof.py`.

No layouts or offsets change. The normal and db0 builds compile all existing
locks: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144, Config 624 bytes. Ownership, migration, QSBR, immutable writes,
RYOW, atomicity and ordering code are unchanged, including their safety guards.
An inherited law conflict remains: `src/store/flatstore.h:928`, `:949`, `:975`
and `:3253` perform the per-operation topology sequence validation already
flagged by cleanup-readreply. The literal no-per-operation-seqlock law conflicts
with that existing sequence protocol. This cleanup neither removes its torn-read
protection nor claims to resolve the conflict; it adds no reader retry.

Implementation commits before this report:
`dfec9aa97` (shared body), `e885d9985` (matrix in existing output row),
`567e76ebe` (assertion bypasses and ELF controls).

**Object/instantiation census and reproducibility.** The launch Makefile has
42 normal and 42 db0 objects. Its broad header prerequisites include wb.h for
all 84. Compiler dependency resolution identifies 18 actual includers per
namespace, **36 total**. All 84 were compared. The per-object source, compiler
command and dependencies are in `freeze/object-inventory.json`; no includer or
broad-prerequisite object was silently dropped.

DWARF inventory includes inline instances that nm alone misses. For each
namespace, the serve-template instantiations occur in `main.o`, `genthread.o`,
`rl2s.o` and `reorder.o`. Other actual includers parse wb.h without instantiating
these serve bodies. `instantiation-inventory.json` and `instantiations/*.txt`
retain the complete object-by-object census and raw matching DWARF names.

| Variant | Plaintext | kTLS/no-borrow | Userspace TLS |
|---|---:|---:|---:|
| normal | 16 combinations in 4 objects | 16 in 4 | 16 in 4 |
| db0 | 16 combinations in 4 objects | 16 in 4 | 16 in 4 |

These are all TrackOutput × Coded × kEp × Submit combinations; the observed
serve callers have ClassifySend=false. The fixture additionally exercises
ClassifySend=true through each public serve wrapper and proves the SQ classifier.
Both prepare APIs are tested separately, although they share underlying
Submit=false instantiations. Coded=false uses actual ordinary reply bytes;
Coded=true exercises both fill-frontier formatting and segment materialization.

Compiler: GCC 13.3.0, release flags
`-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, jemalloc enabled,
with every existing per-TU compiler parameter retained. PRE and POST used the
same absolute worktree and relative source/output paths. `reproducibility.json`
checks identical 84 compile commands plus link command, and 735 resolved inputs;
only wb.h changes among compiler-resolved inputs. The Makefile addition affects
only the test prerequisite, not production commands. `final-build-binding.json`
confirms all 85 current release products match saved POST after that test edit.

**Arms and raw proof artifacts.** All paths below are under this worktree.
Each arm contains `artifacts/`, `manifest.json`, `SHA256SUMS` and
`ARTIFACT-SHA256SUMS`. `dumps/` contains raw objdump/readelf/nm output, every
SHF_EXECINSTR section's unnormalized bytes and metadata, relocation signatures
and allocated-symbol address tables. The checker is the existing strict
`tools/ttlstate_proof.py`; the lane driver adds source/census and negative proofs.

| Arm | Binary | File bytes | SHA-256 |
|---|---|---:|---|
| PRE | `build/cleanup-tlsserve/PRE/artifacts/tomokv` | 176985360 | `24c39ea41d3b312ac81c38667997286ac9895caeb81678776f19e8f33de9b5ef` |
| POST | `build/cleanup-tlsserve/POST/artifacts/tomokv` | 176988648 | `bf0d633ae751d70329e3d52abbc9a64736424a06233b521d4d7e7ee2fff53ee1` |
| PAD A / B | Not required: no production-code/layout change | — | — |

| Production property | PRE | POST | Result |
|---|---:|---:|---|
| Linked `.text` bytes | 7564433 | 7564433 | Every byte equal |
| All six linked executable sections | 7574265 | 7574265 | Every byte/layout equal |
| Executable object sections, including all `.text.*` | 8588 | 8588 | Every byte/layout equal |
| Linked allocated relocation records | 3786 | 3786 | Same targets, types, offsets, addends |
| Linked allocated symbol entries | 10618 | 10618 | Same names, attributes, addresses, sizes |
| Entry point | `0x4dc10` | `0x4dc10` | Equal; program headers also equal |
| Full artifact comparison | 85 artifacts | 85 artifacts | **85/85 PASS**, `identity.json` |

The address comparison covers all 10,035 defined executable function-symbol
entries (including zero-sized entries), 8,805 unique names. There are no renamed
local-label exemptions in this comparison. Separate ELF controls flip one
executable `.text` byte, flip one executable `.text.*` byte, change a relocation
addend, move a function address, and change the entry point. **5/5 are rejected**
with the exact expected checker error. Copies are named `.NEVER-RUN`, mode 0600,
and were never executed. Logs/results: `elf-controls/`.

**Deterministic evidence.** The existing netcmd `output` row now runs 960 cases
per database variant: 3 transports × 2 tracking states × 2 event engines ×
2 coded states × 4 public call forms × 10 states. Every state is constructed
fresh; no timing window, retry tolerance or SKIP is used. Missing Done or missing
BIO output fails an explicit negative witness. Borrow-release callbacks inspect
staged bytes, counters and callback order, then overwrite the released source
storage to catch a missing copy. OOB tests cover a callback during retirement
and an uncompleted ROB frontier. Limit callbacks inspect staging/OOB completion
before retirement statistics, and verify early return and submit_allowed.

The TLS-only pending-output fixture owns a real BIO pair containing ten bytes,
with an empty plaintext queue. It models pending ciphertext; it does **not** claim
a completed TLS handshake, kTLS engagement, encryption correctness or a live
transport result. The unchanged live battery owns those claims.

| Serverless check | Result | Artifact |
|---|---|---|
| netcmd `output`, normal and db0 | 960 cases each, PASS | `netcmd-output-{normal,db0}.log` |
| netcmd `pubsub`, `receive`, `flush`, normal and db0 | 6/6 PASS | `netcmd-results.json`, corresponding logs |
| Generated controls, mutations disabled | 960 cases in each namespace, PASS | `controls/*-00-positive-all.log` |
| Mechanism/setup bypass controls | **136/136 exact failures**, 44 distinct faults | `controls/results.json` |
| Submit=false forced-pump controls | 32/32 exact failures: both prepare APIs × both tracking/coded/engine states × both namespaces | same |
| Raw ELF checker controls | 5/5 rejected, none executed | `elf-controls/results.json` |

Every new assertion's exercised state, exact failure label and bypass result is
listed below. The label is the exact stderr suffix expected by the control driver.
Each listed rejection is exit 1, not a crash or a timeout. The complete mapping,
including configuration and namespace, is `controls/assertion-coverage.json`;
its key set must equal all 35 assertion labels in the fixture. Controls are
generated copies of the real header under build/, never production options or
alternate handwritten implementations. Setup-failure controls are identified
by their fixture/window labels and do not masquerade as transport claims.

| Exact failure label | Exercised state | Removed/bypassed mechanism | Result |
|---|---|---|---|
| `borrow-crlf-oob-order` | borrow-oob, coded-borrow | `borrow`, `crlf`, `materialize`, `oob`, `prefix`, `retire`, `seal` | 14/14 rejected |
| `borrow-policy-release-suppression` | borrow-oob | `note-after`, `release` | 4/4 rejected |
| `borrow-progress` | borrow-oob | `false-no-progress` | 2/2 rejected |
| `borrow-released-once` | borrow-oob | `teardown-release` | 2/2 rejected |
| `cipher-frontier-unchanged` | cipher-only | `cipher-frontier` | 2/2 rejected |
| `cipher-only-no-plaintext` | cipher-only | `wrong-cipher-window` | 2/2 rejected |
| `cipher-only-pump-selection` | cipher-only | `cipher-condition`, `force-submit` | 34/34 rejected |
| `ciphertext-window-armed` | cipher-only | `no-cipher-window` | 2/2 rejected |
| `coded-or-materialized-bytes` | coded-frontier, pending-code | `coded`, `materialize` | 4/4 rejected |
| `direct-spill-bytes` | direct-spill | `direct`, `no-done-window`, `spill` | 6/6 rejected |
| `empty-progress` | empty | `false-progress` | 2/2 rejected |
| `fixture-bio-pair` | cipher-only | `bio-fail` | 2/2 rejected |
| `fixture-rob-acquire` | direct-spill | `acquire-fail` | 2/2 rejected |
| `hook-oob-armed` | borrow-oob | `oob-refuse` | 2/2 rejected |
| `limit-after-oob-before-accounting` | limit-reply | `oob` | 2/2 rejected |
| `limit-callback-gating` | empty | `skip-limit` | 2/2 rejected |
| `limit-oob-armed` | limit-reply | `oob-refuse` | 2/2 rejected |
| `limit-prevents-pump` | limit-reply | `ignore-limit` | 2/2 rejected |
| `limit-progress` | limit-empty | `ignore-limit` | 2/2 rejected |
| `limit-submit-allowed` | limit-reply | `allowed` | 2/2 rejected |
| `oob-flushed-after-frontier` | oob-hole | `oob` | 2/2 rejected |
| `oob-fully-flushed` | borrow-oob | `draining-clear` | 2/2 rejected |
| `oob-held-at-hole` | oob-hole | `early-oob` | 2/2 rejected |
| `oob-hole-armed` | oob-hole | `oob-refuse` | 2/2 rejected |
| `output-accounting` | direct-spill, pending-code | `start-tracking`, `stop-tracking` | 4/4 rejected |
| `plain-frontier-unchanged` | pump-ready | `plain-frontier` | 2/2 rejected |
| `plain-pump-selection` | pump-ready | `plain-pump` | 2/2 rejected |
| `plain-send-and-classification` | pump-ready | `classification` | 2/2 rejected |
| `prepare-allows-submit` | empty | `deny-submit` | 2/2 rejected |
| `release-identity-count` | borrow-oob | `release-double` | 2/2 rejected |
| `release-order` | borrow-oob | `copy` | 2/2 rejected |
| `retire-before-stage` | borrow-oob | `note-before`, `retire-double` | 4/4 rejected |
| `selected-state-entered` | unknown-state | `unknown-state` | 2/2 rejected |
| `serve-retire-direct-empty-counts` | direct-spill, empty, limit-empty, limit-reply | `direct-count`, `empty-count`, `retired`, `serves` | 12/12 rejected |
| `tls-send-and-classification` | cipher-only | `classification` | 2/2 rejected |

Build logs are `PRE-build.log`, `POST-build.log`, `final-build.log` and
`netcmd-final-build.log`. Final builds succeeded. The source proof, input proof,
ELF verdict and completed serverless checks are bound in
`build/cleanup-tlsserve/SHA256SUMS`. Reproduce without starting a server:

```bash
taskset -c 112-127 make -j16 all build/netcmd-unit build/netcmd-unit-db0
taskset -c 112-127 ./build/netcmd-unit output
taskset -c 112-127 ./build/netcmd-unit-db0 output
taskset -c 112-127 python3 tools/tlsserve_proof.py source
taskset -c 112-127 python3 tools/tlsserve_proof.py inputs
taskset -c 112-127 python3 tools/tlsserve_proof.py inventory
taskset -c 112-127 python3 tools/tlsserve_proof.py controls
taskset -c 112-127 python3 tools/tlsserve_proof.py elf-controls
taskset -c 112-127 python3 tools/ttlstate_proof.py compare \
  build/cleanup-tlsserve/PRE build/cleanup-tlsserve/POST \
  --output build/cleanup-tlsserve/identity.json
```

**Mainline live handoff — PENDING MAINLINE.** Keep the launch batteries intact:

| Existing row/battery | Rechecked gate line | Status |
|---|---:|---|
| TLS auth yes/optional and their shutdown checks | 2289–2326 | PENDING MAINLINE |
| kTLS engaged-live gauge witness | 2308 | PENDING MAINLINE |
| TLS pipeline/torn-record/coexistence, forced fallback | 2333 | PENDING MAINLINE |
| TLS shutdown, send errors, slot cleanup, zero-copy suppression | 2339, 2342, 2345, 2352 | PENDING MAINLINE |
| CLIENT REPLY OFF/SKIP cross-shard zero-copy silence | 2434 | PENDING MAINLINE |
| Existing output-buffer, pubsub and global shutdown invariants | Existing batteries retained | PENDING MAINLINE |

Mainline's ordinary diagnostic invocation, using the explicit frozen arms:

```bash
tests/gate.sh iteration \
  --reference-binary "$PWD/build/cleanup-tlsserve/PRE/artifacts/tomokv" \
  --candidate-binary "$PWD/build/cleanup-tlsserve/POST/artifacts/tomokv"
```

This is an external-binary diagnostic, not a claimed source receipt. The gate's
reviewed correctness slots remain eight cores, --shards 16, 6 io + 2 ex. The gate
has a separate performance geometry; that invocation does not certify an
eight-core send-path measurement. Retain both 1s and 2s, read-local 0/1, and
--databases 1/4 in mainline coverage. A fused boot omits --ratio. For a focused
TLS row, the exact existing client invocations are:

```bash
python3 tests/tls.py --generate "$TLS_DIR"
python3 tests/tls.py 127.0.0.1 "$TLS_PORT" "$TLS_DIR" optional \
  --plain-port "$PORT" --full --expect-ktls yes
python3 tests/tls.py 127.0.0.1 "$TLS_PORT" "$TLS_DIR" no \
  --plain-port "$PORT" --full --expect-ktls no
```

The first full command belongs to the normal kTLS-capable boot; the second to
the gate's separate forced-fallback boot at lines 2328–2332, with
`--tls-protocols 'TLSv1.2 TLSv1.3' --tls-ciphers ECDHE-RSA-AES256-SHA384
--tls-ciphersuites TLS_AES_256_GCM_SHA384 --tls-prefer-server-ciphers yes`.
`tests/tls.py:285` proves negotiated TLS1.2/TLS1.3 and mode via active/fallback
counter changes; `:460` requires handshake/transport/zero-copy counters. A
connection that never enters the required mode fails. No live assertion was
added, so no new live mutant binary is required. All new negative controls above
are serverless and have been executed on the permitted CPUs.

**Frozen cells and conditional measurement contract.** This lane needs no
performance measurement to establish the contractual null: all production code,
addresses and load layout are identical. Measurements, if mainline elects to run
them, remain **PENDING MAINLINE** and must use the following unchanged contract.

Base guards are **h01–h64 inclusive**: GET/SET × p1/p32 × both modes ×
read-local/overlap/reorder, 512 connections, 64-byte payload. Exact launch lines
and per-line digests are `freeze/h01-h64.json`; the entire load-plan file is
copied, not reconstructed. Inventory SHA-256:
`d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350`.
Launch `gate_measurements.json` SHA-256:
`883634597e70a073c6f7c011524924723a90f77dbed328a1334b4fad26e96afb`.
The launch note mentions 14 generic null cells without IDs. Their exact selection
is PENDING MAINLINE if needed; it is not silently substituted for the explicit
64-cell guard inventory.

Add separate feature regimes without rewriting an h-cell: userspace TLS1.2/1.3
and kTLS small 64-byte GET/SET replies; 64 KiB and 1 MiB borrowed GETs with
--zc-min 64; OOB delivery behind an outstanding reply; and output backpressure.
Each uses p1 **and** p32, both thread modes, read-local 0/1, databases 1/4, and
512 starting connections, with enough independently calibrated load workers to
establish the productive-role plateau. Freeze offered loads, input bytes,
worker/pin plan and window before POST; a single-connection saturation claim
cannot pass. Use --shards 16 and reviewed 8-core 6:2 split for 2s, corresponding
8-core 1s geometry, and the **two-netns 25GbE NIC rig** for send-path judgments.
Require entered transport/borrow/OOB/backpressure witnesses; a missing window
must be re-armed on fresh state within a fixed budget and then FAIL, never SKIP.

| Regime | PRE cycles/op, instr/op, IPC, rate, tails | POST | Verdict available here |
|---|---|---|---|
| Neutral: plaintext GET/SET | PENDING MAINLINE | PENDING MAINLINE | Production identity; performance null discharged |
| Exercised: kTLS/userspace small replies | PENDING MAINLINE | PENDING MAINLINE | Production identity; no benefit claimed |
| Possible deficit: large borrows | PENDING MAINLINE | PENDING MAINLINE | Production identity; live regime pending |
| Possible deficit: OOB/backpressure | PENDING MAINLINE | PENDING MAINLINE | Production identity; live regime pending |

Freeze evidence from nullrefresh is retained, without claiming unavailable
independent resolution:

| Instrument | Digest / stable reference | Actual limitation |
|---|---|---|
| nullrefresh5, all 23 file hashes verified | `cc6c06bde1ce7939b7f001489fde7287476c4086929f51badf774811d087dd36`; stable binary `ef52de792f72ab8dae240fcd8194e1f14aa94b3828dc7e512eea7256b50c1133`, source `9c4717da03b9340377926277f8eb99cea9f5ab5a` | Saved result PARTIAL; 32 cores / 16:16. Resolution CSV is historical rate/tail spread, not independent per-cell cycles bands. Frozen campaign explicitly says cycles/op UNPROVEN. |
| nullpublish, all 25 file hashes verified at `08d1dd2dbb1d549c83eeb5a8f4792c6b9bd6230b` | `ef5bb5a313f566a67f70b583708bc087da217c9ec5162a3974bb3483b61617dc`; frozen A=B binary `49e69e30d1d3d46f46f8e5f96dad17885511e905c98fba4a3d530814885cf1a7`, baseline `90ba908d3` | Freeze says measurements_run=false; it supplies no validated per-cell bands for this requested geometry. |

Files/manifests are under `freeze/nullrefresh5/` and `freeze/nullpublish/`.
Historical instrument files that have since changed were recovered by recorded
commit and verified against the exact frozen hashes. These instrument reference
SHAs are distinct from this cleanup's PRE. Mainline must independently validate
and freeze per-cell resolution, stable reference SHA, instrument digest and
separate cycle/rate/tail epsilons **before any candidate measurement**. The launch
load-plan file specifies ABBA ratio only for 32 cores; it is not an eight-core
calibration. No guessed invocation or widened tolerance is offered to conceal
that limitation.

For each cell at matched offered load, report cycles/op together with instr/op
and IPC (`cycles/op = instr/op / IPC`), rate and p99/p99.9 tails. For A/B=PRE/POST:

```text
abs(100 * (B_cycles_per_op / A_cycles_per_op - 1)) <= epsilon_cyc[cell]
100 * (1 - B_rate / A_rate)                      <= epsilon_rate[cell]
100 * (B_tail / A_tail - 1)                      <= epsilon_tail[cell]
```

Every cell must also meet stable-reference parity at its frozen resolution;
no averaging away a losing cell or widening a band after POST. If a future
integration changes executable bytes, re-prove identity or supply a separately
mapped **PAD (A), PRE behavior with POST function addresses/layout**, then apply
the same checks to PRE/PAD and PAD/POST. A text-size change of more than a few
hundred bytes also needs the requested kind-B inverse control. No existing R7
PAD is asserted to control this cleanup. This report's identity proof is scoped
to its frozen launch reference and exact saved candidate.

**Gate arithmetic and final handoff.** The extended `output` selection is emitted
at `tests/gate.sh:1385`, inside the existing case loop at 1382, before the quick
exit at **2871** (the old 2808 anchor has moved). No row, case name, gate script,
EXPECT constant or live battery changed in this lane. Delta quick **+0**, full
**+0**: **446 + 0 = 446; 463 + 0 = 463**. These are mainline-owned expectations,
not a claim of a gate run. The gate.sh/load-plan changes shown relative to
5b3d9c429 came from the required origin/cpp merge, not this cleanup.

`sha256sum build/tomokv`:

```text
bf0d633ae751d70329e3d52abbc9a64736424a06233b521d4d7e7ee2fff53ee1  build/tomokv
```

`git diff 2a9e484035960b0ba5925824cc581148c359c0f8 --stat` (lane scope):

```text
 MEASURE-REQUEST-cleanup-tlsserve.md | 395 ++++++++++++++++++++++++++++++++++++
 Makefile                            |   1 +
 src/net/wb.h                        | 228 ++++++++-------------
 tests/netcmd_unit.cc                |   2 +
 tests/tlsserve_checks.inc           | 312 ++++++++++++++++++++++++++++
 tools/tlsserve_proof.py             | 384 +++++++++++++++++++++++++++++++++++
 6 files changed, 1177 insertions(+), 145 deletions(-)
```

Requested `git diff 5b3d9c429 --stat` (includes the launch merge):

```text
 MEASURE-REQUEST-cleanup-readreply.md | 371 ++++++++++++++++++++++++++++++++
 MEASURE-REQUEST-cleanup-tlsserve.md  | 395 +++++++++++++++++++++++++++++++++++
 Makefile                             |   1 +
 src/core/ex_loop.h                   |  63 +++---
 src/net/wb.h                         | 228 ++++++++------------
 tests/gate.sh                        |   2 +-
 tests/gate_measurements.json         |   8 +-
 tests/netcmd_unit.cc                 |   2 +
 tests/rltopo_unit.cc                 | 148 ++++++++++++-
 tests/tlsserve_checks.inc            | 312 +++++++++++++++++++++++++++
 tools/readreply_proof.py             | 369 ++++++++++++++++++++++++++++++++
 tools/tlsserve_proof.py              | 384 ++++++++++++++++++++++++++++++++++
 12 files changed, 2092 insertions(+), 191 deletions(-)
```

The source diff, build and serverless proof work is complete. Live batteries,
boot coverage, mainline gate/receipt and any elected measurements are
**PENDING MAINLINE**. Nothing was pushed. Stop here for maintainer review.
