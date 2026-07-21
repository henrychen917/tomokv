# 2s-paper-baseline — reference build

Purpose: the **basic TomoKV 2s architecture only**, as close to the original THredis paper as the
current tree allows — no adaptive controllers, no CPU pinning, post-paper optimizations off,
remaining constants pinned to fixed standardized values. Use as the clean comparison/ablation
baseline; not an active dev branch. Branched from stable `7a11afb95` (carries all correctness
fixes — this baseline changes *defaults only*, no code).

What remains ON (the paper architecture itself): IO threads + execution workers, SPSC dispatch,
CDB reply reorder (auto = one CDB per worker, identity mapping), express lane, fake-client ring
(fixed depth), cross-shard scatter-gather + 2-hop + SAFE-GATE (correctness, not perf).

## Default changes vs stable (all in config.c; every knob remains runtime-overridable)

| Knob | stable | baseline | Rationale |
|---|---|---|---|
| tomokv-pin-mode | 2 (NUMA auto) | **0** | float: scheduler decides (paper had no pinning) |
| tomokv-reshard-min-ops | 20000 | **0** | EWMA auto-resharding OFF (post-paper) |
| tomokv-io-drain-userpoll (T1) | -1 auto | **0** | plain poll, controller off |
| tomokv-drain-tail-skip (T2) | -1 auto | **0** | off |
| tomokv-express-slim (T3) | -1 auto | **0** | full state move always |
| tomokv-fake-ring-depth (D3) | -1 auto | **16** | fixed full ring, no decay controller |
| tomokv-fake-buf (D1) | -1 auto | **16384** | fixed 16KB reply buffer, no demand growth |
| tomokv-pf-w-* (7 prefetch stages) | -1 auto | **0** | worker prefetch OFF (post-paper) |
| tomokv-worker-spin | 0 adaptive | **32** | fixed spin budget |
| tomokv-worker-pop-batch | 0 adaptive | **8** | fixed pop batch |
| tomokv-zerocopy-min-value | 1024 | **INT_MAX** | zero-copy replies OFF (post-paper) |
| thredis-opt-mget-coalesce | 1 | **0** | per-key subs (pre-OPT-1) |
| thredis-opt-setop-coalesce | 1 | **0** | per-key subs |
| tomokv-num-cdb | 0 auto | 0 auto (unchanged) | auto = one CDB per worker = the original identity design |
| io-uring family, os-opts, busypoll, mset-move, operand-pool | 0/off | unchanged | already off |
| thredis-xshard-guard | 1 | unchanged | correctness gate, not a perf feature |

Validation at branch creation: boots clean with zero args; xshard_corruption PASS;
xshard_intercard PASS (see branch commit message for the run evidence).
