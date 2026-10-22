# Tracking assertion sweep

The source search is retained in `tracking-assertions.txt`. Final gate receipts
use `GATE_ONLY_JOBS` through the actual gate dispatcher, not reimplementations
of its batteries. Every declared leg in each selected job runs.

| Assertion source | Gate job / proof |
|---|---|
| `tests/trackfix.py` | `trackfix_order`, `trackfix_accounting`: PRE and final POST, 16 boots per row, 10 protocol/option cases per boot; PAD-A accounting too |
| `tests/tracking.py`, `climon.py`, `climon2.py`, `pushtear.py`, `netcmd.py` | Whole `feature-split-0/1` and `feature-armed-0/1`, both epoll and uring; the latter exercise fused read-local mode |
| `tests/clientfix.py` | Whole `clientfix`, both modes, both engines, all seven cases per mode |
| `tests/netcmd_unit.cc` | Whole `netcmd_units`; `config` calls `tracking_eviction`, and `output` includes suppressed-read retirement assertions |
| `tests/climon_mask_unit.cc` | Whole `ring_unit`, including the deliberately broken old-mask negative control |
| `tests/notify.py` | Whole `notify` on split and supplementary fused boots for both engines; both atomic modes inside its notification row |
| `tests/notify_order.py` | Whole `notify_order` and `notify_aof`, which declare their own engine/mode/atomic/read-local legs |
| `tests/notify_order_checks.inc` | Whole `netcmd_units`; its `notify-oom` case calls `check_notify_order_failures` |
| `tests/differ.py` | Unchanged standard `tests/differ_gate.sh`, both geometries and engines, PRE-final and POST-final; fresh seed-19 repeats separately |
| `tests/cmdmeta.py` | Whole `cmd_metadata`, plus standard differential command metadata |

`core_concurrency`, `rlfix`, `execatomic`, `execiso`, and script-cache references
to tracking/invalidation describe other mechanisms; they are not CLIENT
TRACKING frame assertions. Feature/debug jobs also retain the existing unrelated
batteries they declare. No existing tracking expected frame was changed.

Explicit limitations:

* `climon_128.py`: **NOT RUN**. It needs two live IO owners separated by 64 and
  has no registered gate job. The required eight-server-CPU lane geometry cannot
  supply that topology. The registered 128-owner mask arithmetic row did run.
* `replyschema.py`: **NOT RUN**. It has tracking command-shape cases but no
  registered gate job. Tracking commands are covered by the existing feature,
  command-metadata and differential jobs; this standalone schema census is not
  claimed as run.
* `clientfix_widths.py` and benchmark/ABBA helpers: **NOT RUN**. They are
  performance probes reserved for the maintainer.

For each final job's precise row count and status, see `gate-results.json` and
its canonical partial ledger. Earlier fixture failures and earlier-binary jobs
remain in those receipts with distinct labels.
