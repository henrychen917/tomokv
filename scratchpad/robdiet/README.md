# robdiet — instruments for the armed read-local ROB bookkeeping

`replay.c` drives one connection with a byte-identical request stream in both arms; `measure.sh`
takes each cell as a SLOPE over two operation counts (1M and 3M) on a server pinned alone to one
core, so connection setup and the loop's idle spin cancel instead of being billed to the change.
`multi.sh`-style rotation (see `ab.sh`) alternates arm order across reps. `measure2s.sh` is the same
instrument booted `--thread-mode 2s`. `sizes.py` reports per-function byte sizes and `.text` totals
between binaries — the instrument that found the code-growth regression.

## Shapes, and which one models the deployed mix

`mixed11` alternates GET k, SET k on the **same** key, so every SET demotes the GET one frame ahead
of it through the demotion planner's exact-key selection: 0 local hits, 100% inflight-write
fallbacks at every pipeline depth. That is a pathological shape, not a property of 1:1 traffic.
`mixed11x` uses **disjoint** read and write key sets, which is what an independent-key load
generator produces: 100% local hits, 0 inflight-write fallbacks, matching the box reading of
113.9M local hits against 1,448 inflight-write fallbacks at 64 shards / 32 cores. **Use
`mixed11x`.** `mixed11` is retained only as the demote-everything corner.

## Data

| file | arms | what it establishes |
|---|---|---|
| `null.csv` | PRE vs PRE | fused-geometry noise band: worst cell +0.23%, 12 of 13 within +/-0.09% |
| `armtax.csv` | `--read-local 0` vs `1` | the armed tax this lane cuts into |
| `bisect.csv` | PRE, A, B, C, D | per-cut attribution: A=acquire, B=+write_conflicts, C=+mark, D=+owner_conflicts |
| `final4.csv` | PRE, BC, C, D | confirms C beats D on every cell and BC gives up the write-side win |
| `headline.csv` | PRE vs C | the shipped table, including `mixed11x` |
| `superseded-arm-D.csv` | PRE vs D | the first, over-inlined shape; kept because the C-vs-D argument rests on it |
| `null2s.csv` / `ab2s.csv` / `ab2s_rev.csv` | 2s, counterbalanced | 2s band ~+/-0.5%, slot bias +0.38%, binary effect -0.03% (measured against arm D, which perturbs strictly more than the shipped C) |

`batteries.sh <bin> 1s|2s` runs the functional batteries, one boot per battery, port 8071.
