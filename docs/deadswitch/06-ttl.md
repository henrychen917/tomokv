# 6 — TTL deadline sidecar: EXPERIMENT; both arms and inverse control built

No production TTL selector, default, or branch is removed. The current default
remains inline (`TOMO_TTL_DEADLINE_SIDECAR=0`). The two requested executables are:

* `build/deadswitch/ttl-inline/tomokv`
* `build/deadswitch/ttl-sidecar/tomokv`

Both use the same source and Makefile compiler budgets; the second adds only
`-DTOMO_TTL_DEADLINE_SIDECAR=1` to the normal CXXFLAGS. The full default binary
is byte-identical in loadable sections to the frozen merge base. The sidecar is
not: **1186/1492 hot bodies equal**, 306 different; **15985/17199** in the full
union inventory equal, **1214** changed/added/removed. Both strict identity tools
correctly exit 1 for this experiment. Those failures are retained, not waived
into cleanup passes. The full checker selects 1498 hot bodies including extra
run/new bodies, of which 1189 match.

Every changed emitted body is listed with a reason and instruction-line counts
in `06-changed-bodies.json.gz`; `06-body-diffs.txt.gz` retains the corresponding
instruction/relocation diff. The changes include the sidecar's 8-byte deadline
storage per expiry slot, state-byte offsets, migration and refresh logic,
owner deadline lookup, and TTL lookup/reap/mutation/accounting callers. There
are also GCC inline/outline/clone and constant-target changes in otherwise
unchanged source bodies. These are explicitly classified as compiler changes,
not claimed to be neutral, deleted code, or hand-audited semantic equivalence.
The experiment's A/B must price all of them. No compiler budget was retuned.

GDB proves **sizes and all named field bit offsets identical** in both namespaces:
Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144, Config 624. `06-layouts.json` contains both complete layouts.
Heap expiry-index allocation intentionally differs even though those object
layouts do not.

The existing serverless storage suites pass 11 common cases in each arm plus
the sidecar allocation-failure/deadline-extension case: **23 passes**. Running
that sidecar-only case on the inline build fails its arming assertion, as it must.
Results are in `06-storage-units.json`. These are not edgetime/hexpire live or
differential receipts; those remain mainline work.

## PAD semantics

`build/deadswitch/ttl-pad-b/tomokv` is **(B) inverse control: candidate sidecar
behavior plus padding restoring PRE's aggregate text size**. It is justified
because `.text` shrinks by 27,874 bytes:

| Arm | `.text` bytes |
|---|---:|
| inline PRE | 7,845,285 |
| sidecar POST | 7,817,411 |
| PAD-B | 7,845,285 |

`ttl_pad_b.py` relinks the exact POST production objects in the same order,
adding 27,874 unreachable NOP bytes with no symbols or relocations. It preserves
all 9229 selected POST text-function addresses and sizes, and preserves the
GNU CET/ISA property note. The proof records every input-object hash. This
controls aggregate size while retaining POST code placement; it does **not**
recreate all PRE function addresses/alignment and is **not** a kind-A behavior
twin. Do not label it A or claim full instruction-placement causality from it.

## Mainline request

The exact 14 mainline null recipes are frozen in `06-null14-cells.txt`:
m02 m03 m05 m06 m26 m27 m50 m51 m53 m54 m74 m75 h05 h06.
`06-null14-plan.json` validates the recipe inventory without starting workloads.
Run the null before comparing inline/sidecar/PAD-B at the same offered loads;
retain per-cell rate, cycles/op, instructions/op, IPC, and tails.

For correctness, run **edgetime and hexpire**, split and armed-fused, both atomic
settings and RESP modes, with permanent seeds **7, 19, 20, 23**. The suite/seed
files are committed. Use eight physical cores, 16 shards, ratio 3 (6 io + 2 ex)
for the split correctness geometry. The checked-in ABBA geometry is separately
32 physical cores, 16:16; do not invent eight-core ABBA calibration.

There are **no expiry/TTL performance d-cells** in `headline_cells.txt` or
`wb_rule_cells.txt`. The only d-cell is `d128g_l0`, plain GET at p128, and it
has no expiry setup. Neither edgetime nor hexpire is a rate cell. A TTL-heavy
rate conclusion therefore needs an explicit expiry workload/arming receipt
from mainline; a pass on the generic null cannot decide that question. The root
measurement request makes this missing evidence explicit. Gate rows +0/+0.
