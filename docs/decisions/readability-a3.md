# IO-loop decisions

These entries preserve rationale and historical observations removed from source comments.
Dates below are the documentation review date; they do not invent dates for the original
experiments. Historical numbers are not new measurements or throughput claims.

## 2026-11-08 — Per-IO listening sockets (`IoLoop::init`)

Use one SO_REUSEPORT listener per IO thread and transfer that listener intact during FLIP.
The previous comment records a shared-listener observation with six IO threads and 577
connections: thread 5 accepted every connection, with about 3.5 ms depth-one latency.
It also records a separate two-process reuseport incident that appeared as missing data.
The lasting requirements are kernel distribution across per-thread listeners and excluding
another server process from the listening port. Successful reuseport bind alone is insufficient.

## 2026-11-08 — Keep `IoLoop` definitions at their tool-owned locations

An interface-first split is not eligible under this lane's combined constraints. The R7
input list in `tests/r7shadow_sync.py`, `tools/source_anchors.json`, lottery hooks, and PAD
builders bind interleaved methods to `src/core/io_loop.h`. Moving the other member bodies
into a header after the class would place them after the retained definitions, changing
translation-unit definition order. Moving every body would break the path constraints.
No class split was attempted or kept; there is no DIFFERENT binary accepted as readability.
The six-file ownership partition also provides no new topic-header destination.
