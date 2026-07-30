# Refactor risk register

This list is ordered for reviewer attention, not to make the branch look complete. “Builds” below
means compilation/linking only; no runtime evidence was permitted.

## Ranked risks

| Rank | Risk | Why it may be wrong | What settles it |
|---:|---|---|---|
| 1 | Cross-IO meaning of same-key arrival order | The scheduler preserves each producer FIFO and never crosses rings, but the default transport already rotates independent IO-producer rings without a global wall-clock sequence. If “arrival” means a total order before worker admission, the product invariant is not implemented by the baseline or this refactor. | Specify the linearization point. Run synchronized same-key clients on different IO owners with operation IDs. If wall-clock ordering is required, review a sequencing design before enabling reorder; do not infer it from latency tests. |
| 2 | IO fired-event consumer equivalence | Level 2+ replaces AE's ordinary fired-array loop. It reproduces generic barrier order and custom-IO order in bounded ranges, but an omitted callback/barrier/TLS rebinding case could skip or double-dispatch an event. | Stress socket and TLS clients, listener/notifier/module-like fds, disconnect during callback, migration, and sparse polls. Compare callback counts and protocol transcripts at levels 0 and 2. |
| 3 | Value-interior lifetime under hints | QSBR protects the flat table and kvobj shell, not an SDS/listpack interior. EX uses exact-key/owner qualification; IO follows the existing `bulkStrRef` held by reply construction rather than adding a new pin. A missed in-place mutation, reply teardown, or freeback exception would turn a hint address into a freed line. | Review every RAW-hint eligibility path against copy-on-write/refcount rules. Stress delete, overwrite, APPEND, first TTL, hash/listpack realloc, flat resize, disconnect/teardown, and MGET while sampling sanitizer builds in both engines. |
| 4 | Scheduler benefit versus early-signal cost | HEAD GET opportunities may be sparse at deep pipelines. Up to 15 distinct selected parents can cause early release RMWs that would otherwise be coalesced with the suffix, and socket batching may erase the service-time win. | Use large BITCOUNT plus distinct-client HEAD GET, not MGET/SCAN. Measure opportunity/promoted/early-RMW counters, throughput, p99/p99.9, and packets/writes at reorder 0/-1/1. |
| 5 | Role-transfer and listener state machine | Startup adoption, retired frontiers, cancellation, live counts, and listener admission were changed together. Notifier creation failure, cancellation racing EX adoption, or an unusual bind/TLS shape is hard to establish by inspection. | Repeated grow-front/back, cancellation, connection migration, FLUSH, shutdown, notifier-failure injection, and IPv4/IPv6/TLS/plaintext boot matrices. Check pool conservation and no stuck role. |
| 6 | 96-core performance and footprint | Bounds are safe, but 64 workers x 32 producer rings means 2,048 header visits per logical pass. Static queues are ~33.4 MiB, freeback rings ~16.8 MiB, and multi-L3 CDB state is 4 KiB per real client. Full width also has no flip actuator. | Measure empty-pass cycles, LLC/remote-NUMA traffic, memory per connection, and throughput on the target topology. Treat full-width auto as static until headroom is redesigned. |
| 7 | Dependency classifier coverage | GET/BITCOUNT/SET are intentionally narrow. A command-table flag, argv rewrite, fake reuse, scatter request, or sentinel misclassification could permit an unsafe pass. Pointer identity and fences are defenses, but the route table is a high-value review point. | Audit every assignment of `tomo_route`, every fake reset/move path, and every producer of `CLIENT_TOMO_SCHED_HEAD`. Add same-key negative controls for SET options, BITCOUNT ranges, disconnect/reuse, FLUSH, and migration. |
| 8 | Early-completion lifetime/bookkeeping | The prefix duplicates normal post-command work and captures parent/slot before the release. A future suffix obligation added in only one path will silently diverge. | Side-by-side review of `tomoExecuteShortPrefix()` and the normal loop after every command-accounting change. Assert reply/order/accounting parity under mixed clients and disconnects. |
| 9 | Cross-shard inline argv escape | Current group ownership closes the known free paths, but a future rewrite, block, propagation, or module path could retain an inline vector after its group dies. | Audit all `csGroup`/subfake ownership transitions and measure inline/spill counters. Require any new escape to copy or take independent ownership. |
| 10 | Cleanup compatibility | Dynamic loading code and private helpers were source-unreachable, but only compilation was checked. Out-of-tree private-symbol users or an unexpected bundled module origin path could depend on them. | Build relevant conditional variants and inspect `COMMAND DOCS`, CONFIG rewrite, bundled Vector Sets, and existing config-file diagnostics. The accepted config/command/schema surfaces must remain unchanged. |
| 11 | Diagnostic snapshot coherence | Counters are owner-local and individual atomic fields are safe, but INFO can combine neighboring generations across subsystems or fields. It is observability, not a transaction. | Poll INFO during load/flip and verify monotonic counters and zero bound violations. Do not use cross-field equality as a correctness predicate unless a sequence protects that group. |
| 12 | HOTKEYS compatibility | START now fails explicitly. That is safer than racing global sketches and omitting worker commands, but it is an intentional feature refusal visible to clients. | Product decision: keep the refusal, or fund owner-local IO+EX sketches, immutable snapshots, final-publish/stop handshake, and deferred session reclamation. Do not reapply the partial patch. |

## High-severity source areas not claimed fixed

These are outside the coherent changes above and must not be inferred fixed merely because the
branch builds:

- background persistence and some flush/save ordering still need a shard-aware quiescence audit;
- runtime notification configuration and other stock `call()`-maintained facilities can still
  disagree with worker-direct execution;
- migration notifier failure and several worker/reclaim/flush waits remain capable of waiting
  without a bounded recovery path;
- support gates for AOF, replication, transactions, eviction, dynamic modules, and HOTKEYS are
  refusals, not implementations; and
- consumer-side worker polling remains dense even though producer publication is sparse.

## Review stop conditions

Do not measure performance until:

- `tomokv_reorder_bound_violations` is demonstrably zero under the same-key controls;
- IO ingress/reply counters prove the enabled level is issuing rather than merely entered;
- EX counters prove both DICT and FLAT stages issue on data larger than cache;
- role-transfer loops show conserved IO+EX live counts and no stuck retired frontier; and
- a reviewer accepts worker admission as the same-key linearization point, or the cross-IO ordering
  requirement is resolved another way.

The branch's least-supported claims are scheduler usefulness, level-4 IO payload value, level-3 EX
RAW value, and 96-core polling cost. Compilation cannot answer any of them.
