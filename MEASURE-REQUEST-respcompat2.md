# respcompat2 — WIP; required hot-byte identity is NOT achieved

Worktree `/home/user/Projects/cx-respcompat`, branch `cx-respcompat`.
Merged `origin/cpp` **7213a9405** in **faf503174**. Production changes for this
revision are **eeb7ee694** and **70d2e375f**, confined to `src/net/resp.h`.
**ff1c38c10** adds the serverless replay of the existing wire inventory.

This is a committed candidate and an explicit failed acceptance report, **not a
completed restoration of PRE's fast-path bytes**. Both byte checkers still find
hot differences. No measurement, server, load generator, live differential,
gate, or push was run. Compilation and executable/serverless checks used CPUs
112–127. Compiler flags and budgets, EXPECT constants, wire fixtures, gate rows,
and the differential leg were not changed by respcompat2.

## The conflicting acceptance conditions

PRE uses the same digit loop for the first and later digits. In its emitted
`tomo::resp_parse_t<false>` body, offsets `0xa0` and `0x160` contain:

```asm
lea -0x30(%rax),%edi       # 8d 78 d0
cmp $0x9,%dil             # 40 80 ff 09
ja  <invalid-length>
```

Those instructions accept zero. A leading zero neither exceeds the numeric
limit nor fails the completed-header `digits != 0` check. Consequently both
`*01\r\n$4\r\nPING\r\n` and `*1\r\n$04\r\nPING\r\n` complete as valid PINGs
without taking a cold/error edge in PRE. Changing only cold/error bodies cannot
reject either request. Rejecting the first zero while accepting a later zero
requires a different decision in that path, or additional validation elsewhere;
the latter would also violate the requested zero common-path cost.

The [four-input production-parser witness](docs/respcompat2/identity-witness.cc),
[PRE output](docs/respcompat2/identity-pre.txt), and
[POST output](docs/respcompat2/identity-post.txt) demonstrate this directly.
Canonical PING and a bulk length of `10` succeed in both. PRE accepts both
leading-zero cases; POST returns the exact NET16 errors. The disassembly remains
in `build/respcompat2/parser-instructions/000.diff.pre` and `.post`.

Thus literal PRE hot-body byte identity and NET16 cannot both hold for this PRE
with unchanged input and no additional validation. This candidate retains NET16
and reports the changed hot instructions; it does not redefine byte identity or
mask those instructions in the audit. The requested first-byte `'1'..'9'`
instruction identity is **also not achieved**. A further lane needs an explicit
acceptance exception for that classifier/code generation, or a PRE that already
implements canonical count grammar. No grammar or test expectation was weakened.

## Cold boundary implemented

The first digit is peeled from the existing numeric loop. Its range check accepts
`'1'..'9'`; zero and nondigits use the rejection exit. Subsequent digits retain
the `'0'..'9'` check. There is no completed-header leading-zero revalidation and
no extra first-byte test inside the subsequent-digit loop. This is a source and
control-flow description, not a throughput or instructions/op claim.

`resp_parse_slow`, marked `[[gnu::cold, gnu::noinline]]`, finishes the entire
exceptional request. The ordinary parser returns its result directly instead of
resuming its argument loop after a slow length call. The cold parser handles
zero-length arguments, empty/negative arrays, count limits/grammar, malformed
prefixes, incomplete malformed headers, and Redis's unchecked terminator bytes.
`resp_parse_unlimited_slow` keeps constant-limit argument setup inside the cold
exit. `resp_expected_bulk_error` is now explicitly cold/noinline too.

The fallback replays framing from the original command boundary and appends only
arguments beyond the existing `op.argc()` prefix. It never resets `Op`, discards
captured reply/read flags, rewrites pinned input, or eagerly allocates argv for a
large count. Normal positive-count parsing never calls it. Valid zero fields
take the cold decoder, as requested; they may replay an already parsed prefix.

NET15 retains its prior out-of-line `resp_parse_inline` implementation and cold
quote validator. Marking the whole inline-protocol function cold in the first
iteration perturbed ordinary dispatch bodies; that attribute change was backed
out. The final inline-protocol function is **not explicitly `gnu::cold`**, and
its emitted body differs from PRE. Therefore the strict requested cold-boundary
and unchanged-continuation conditions are not claimed complete either. The
existing IoLoop error/reply/close path is untouched.

## Body table before and after

The existing `tools/lbstall_artifacts.py compare` and
`tests/respcompat_audit.py` were used without changing either comparator. The
latter retains its existing TLS relocation-width extension. No opcode, register,
immediate, branch, local block offset, or resolved callee difference is masked.

| Inventory against PRE | Prior respcompat | respcompat2 |
|---|---:|---:|
| Original frozen 1,559 entries, raw equal | 1,402 / 1,559 | **1,409 / 1,559** |
| Same entries, canonical bytes + resolved targets equal | 1,441 / 1,559 | **1,450 / 1,559** |
| Removed entries from that inventory | — | **0** |
| Additional entries | — | 16 cold fallback/wrapper entries |
| Current extended inventory, raw / canonical equal | 1,402 / 1,441 of 1,559 | 1,409 / 1,450 of 1,575 |
| `lbstall_artifacts` inventory, raw / canonical equal | — | 1,405 / 1,446 of 1,482 |
| All emitted `parse_and_dispatch*` entries including lambdas/clones, raw / canonical equal | — | **216 / 226 of 240** |
| Independent linked ordinary-body instruction audit | 363 / 396 | **373 / 396** |
| GET/SET/MGET/MSET entries in the object inventory, raw / canonical equal | unchanged | **10 / 10** |

[Frozen inventory](docs/respcompat2/frozen-inventory.json) retains every original
entry and its before/after flags, plus all 16 additions.
[Complete body table](docs/respcompat2/body-table.md) lists **every one of the
166 current raw differences**, with its object, demangled body, PRE/prior/POST
sizes, and reason. Of these, 41 differ only in address displacements with equal
canonical bytes and targets; the other 125 fail that check too. This includes
the 14 `parse_and_dispatch*` entries that fail canonical comparison. Their
remaining differences concern quota-helper inlining, demotion-storage cleanup,
and conflict-check lambdas under the unchanged compiler budgets.

The full 86-object union contains 16,893 function entries; 212 entries are
changed/new under canonical comparison. Exact callee deltas, including non-hot
bodies, are in [changed-bodies.json](docs/respcompat2/changed-bodies.json).
[Summary and binary digests](docs/respcompat2/audit-summary.json) are retained.

Linked body sizes / static instruction counts follow. These count the entire
body, including uncommon blocks; they are **not instructions/op**. Limited
variants are emitted in four objects per namespace but link as one COMDAT each;
the object inventory checks all emitted copies.

| Namespace/body | Linked copies | PRE bytes / instructions | Prior POST bytes / instructions | respcompat2 bytes / instructions |
|---|---:|---:|---:|---:|
| tomo `resp_parse_t<false>` | 4 | 914 / 224 | 1,094 / 267 | **998 / 248** |
| tomo_db0 `resp_parse_t<false>` | 4 | 997 / 238 | 1,132 / 276 | **1,058 / 260** |
| tomo `resp_parse_t<true>` | 1 | 952 / 229 | 1,242 / 304 | **1,073 / 265** |
| tomo_db0 `resp_parse_t<true>` | 1 | 1,024 / 242 | 1,335 / 315 | **1,150 / 274** |
| tomo `resp_parse_inline` | 1 | 645 / 177 | 653 / 188 | **382 / 123** |
| tomo_db0 `resp_parse_inline` | 1 | 642 / 178 | 667 / 190 | **382 / 123** |
| `resp_expected_bulk_error`, each namespace | 1 | 490 / 127 | 490 / 127 | **410 / 119** |

All 16 emitted hot `resp_parse_t` bodies still differ. First-digit peeling,
terminal fallback exits, and compiler register/block placement explain those
differences. No parser-body identity claim is made from the smaller bodies.
The first iteration's audit and binary remain under
`build/respcompat2/iteration1`; its current-inventory canonical result was
1,416 / 1,567 and its text grew to 7,784,300 bytes. The final build restores the
inline-protocol function's original declaration attributes and uses the cold
constant-limit wrapper. No compiler-budget change was made.

## Serverless validation and unchanged live rows

| Check | Result |
|---|---|
| Expanded parser unit | **204,263 checks, 0 failures** |
| Expanded unit under ASan + UBSan | **204,263 checks, 0 failures** |
| Same expanded unit against prior respcompat | **204,263 checks, 0 failures** |
| Unchanged 311-case inventory, production-parser replay | **343 steps, 0 failures** |
| Same replay against prior respcompat | **343 steps, 0 failures** |
| PRE replay negative control | **50 failing steps across 27 cases**, exit 1 |
| Duplicate-prefix cold-fallback control | **33 failures**, exit 1 |
| Reset-Op cold-fallback control | **1 failure** for lost captured flags, exit 1 |
| Wire-oracle scripted-socket controls | **9 / 9 pass**, no sockets opened |
| Production-linked `netcap-unit` | **PASS all**, including real parser error queuing and deferred reclamation |
| Layouts | Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob 192, AtomicEntry 144, Config 624 |
| Shell/Python syntax and `git diff --check` | PASS |
| Live NET13–NET16, both modes, Redis differential, gate | **Not run; maintainer-owned** |

The new [serverless replay](tests/respcompat_replay.py) imports the unchanged
`tests/respcompat.py` inventory. It passes fragmented receive bytes through the
actual parser and formats the inventory's PING/ECHO replies locally. It checks
exact parser output and terminal Error results. It explicitly does **not**
claim TCP close timing, executor/reorder behavior, or a live Redis comparison.
Receipts and unit logs are in `docs/respcompat2/`.

`tests/respcompat.py`, `tests/differ_gate.sh`, and `tests/gate.sh` are unchanged
from the starting lane. No fixture was edited. The inherited row remains
`collect_job respcompat` at **line 3179**, before the quick-tier exit at
**line 3301**: **+1 quick / +1 full**, with **zero additional rows** in this
revision. EXPECT remains **497 / 514**; the owner update is still **498 / 515**.

## Frozen measurement arms

PRE production inputs (`src`, `third_party`, Makefile) are identical between
649116c91 and merged mainline 7213a9405. PRE was copied from the existing frozen
build; POST and PAD-B were rebuilt for this revision. The production source
state is 70d2e375f; subsequent commits add only tests/evidence.

| Arm | Binary | `.text` bytes | SHA-256 |
|---|---|---:|---|
| PRE | `build/respcompat2/PRE/tomokv` | 7,782,988 | `5df68dbcc48e9cf62e465cea8b81e504e5609087be841f22cba0e969c54a102e` |
| POST (WIP) | `build/respcompat2/POST/tomokv` | 7,782,956 | `f0cde7f0fa97532ed560fcfdb4d7a9114b0a97cde880454df41b5218e4ad7187` |
| PAD-B — **B: inverse control** | `build/respcompat2/PAD-B/tomokv` | 7,782,988 | `f7ed8fcf915e896fcb9d41185dff194ba55e079b450f14a984b54d52ebbbbcc7` |

PAD-B is **POST behavior plus 32 unreachable NOP bytes restoring PRE's text
size**. It is not a PRE-behavior twin. The existing builder verifies text
function placement, all four read-local island entry/return pairs, unchanged
island work instructions, and every remaining `.text` byte. `.rodata` is
identical. The independent instruction audit is **396 / 396 identical** for
POST versus PAD-B. See [receipt](docs/respcompat2/pad-receipt.json).

This revision does not pass the requested static acceptance condition. If the
maintainer measures this WIP to judge its behavioral change, use the unchanged
mainline 14-cell null instrument in `docs/lbplanner/generic-cells.txt`, PRE vs
POST and PRE vs PAD-B:

`h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`.

Keep the instrument's current standing-null geometry, matched offered load,
ABBA ordering, overlap/reorder/read-local/atomic settings, and score fields.
Record per-cell rate, latency, cycles/op, IPC and instructions/op. Use the same
null bands as the rejected prior arms, with particular attention to m8g_l0 and
the deep/mixed cells. A body-size or instruction-count reduction does not decide
acceptance; the matched-load rate/latency verdict does. This is not a substitute
for the unmet byte-identity gate. No new PRE/POST performance result is claimed.

The maintainer should also run the unchanged wire row in both 1s and 2s at gate
geometry (`--shards 16 --ratio $GATE_RATIO`, pinned to `$GATE_CORES`), the
harness-owned Redis 7.4 differential leg, then `tests/gate.sh iteration` after
the owner-maintained EXPECT/ledger update.

## Reproduction, serverless only

```sh
taskset -c 112-127 make -j16 BUILD_ROOT=build/respcompat2/POST
taskset -c 112-127 g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -I. tests/respcompat_unit.cc -o build/respcompat2/unit
taskset -c 112-127 build/respcompat2/unit
taskset -c 112-127 python3 tests/respcompat_replay.py build/respcompat2/replay
taskset -c 112-127 python3 -m unittest discover -s tests -p respcompat_test.py -v
taskset -c 112-127 python3 tests/respcompat_audit.py build/respcompat2/PRE build/respcompat2/POST build/respcompat2/audit
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare build/respcompat2/PRE build/respcompat2/POST build/respcompat2/lbstall-bodies.json
taskset -c 112-127 python3 tests/r7shadow_noop.py build/respcompat2/PRE/tomokv build/respcompat2/POST/tomokv build/respcompat2/instructions --inventory splitlocal
taskset -c 112-127 python3 tests/respcompat_pad.py build/respcompat2/PRE/tomokv build/respcompat2/POST/tomokv build/respcompat2/post-build.log build/respcompat2/PAD-B/tomokv
taskset -c 112-127 python3 tests/r7shadow_noop.py build/respcompat2/POST/tomokv build/respcompat2/PAD-B/tomokv build/respcompat2/pad-instructions --inventory splitlocal
```

Both PRE/POST strict comparators intentionally return **1**: that is the reported
failed byte gate. The PRE replay control also returns 1. POST/PAD-B comparison
returns 0. The PAD builder needs the recorded final production link command in
`post-build.log`; do not overwrite that log with a no-op make invocation.
