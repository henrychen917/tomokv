# Documentation coverage

Counts exclude the generator-owned R7 envelope. A contract is one authored or
completed comment describing an entry point or ownership-bearing type; the
common main-entry contract counts once across its preprocessor alternatives.
File headers and phase landmarks are separate counts.

| File | Contracts added/completed | Contract subjects |
|---|---:|---|
| `core/boot_support.h` | 4 | `print_boot_presentation`, `make_exclusive_boot_listener`, `probe_boot_listener`, `print_ready_listeners` |
| `core/fused_boot_gate.h` | 1 | `FusedBootGate` |
| `core/fused_owner_turn.inc` | 0 | File/include-point and doorbell-ordering header |
| `core/genthread.cc` | 3 | `IoLoop::run_fused`, `run_fused_server`, its worker lambda |
| `core/genthread.h` | 0 | Runtime declarations and borrowing overview |
| `core/genthread_pipeline.h` | 0 | Compile-time geometry header |
| `core/reorder.cc` | 3 | `append_reorder_info`, `ExLoopT::r7_drain_tasks_impl`, `run_fused_server_selected` |
| `core/reorder.h` | 12 | Six top-level classes; `ExReorderQueues::Slot`; `ShadowReorderQueues::Node` and `Slot`; both `submit` methods; `ShadowReorderQueues::emit_queued` |
| `core/rl2s.cc` | 5 | `split_read_local_pass`, `run_split_read_local_baseline`, `run_split_read_local_server`, its worker lambda, `append_read_local_thread_info` |
| `core/shutdown.cc` | 3 | All three shutdown entry points |
| `core/shutdown_report.h` | 6 | `ShutdownReport`, `ThreadRow`, collector, both renderers, `ShutdownReportFinalLine` |
| `main.cc` | 5 | `on_signal`, `ScopedSignalHandlers`, main entry, both worker lambdas |
| **Total** | **42** | |

The handwritten functions exceeding 50 non-comment code lines all have contracts:

| Function | Non-comment code lines | Physical body lines | Phase landmarks |
|---|---:|---:|---:|
| `run_fused_server` | 161 | 193 | 6 |
| Fused worker lambda | 77 | 80 | Within the enclosing boot phases |
| `run_split_read_local_server` | 185 | 219 | 6 |
| Split read-local worker lambda | 99 | 101 | Within the enclosing boot phases |
| `shutdown_clients_after_join` | 156 | 199 | 6 |
| `collect_shutdown_report` | 101 | 111 | Below the 150-line threshold |
| `print_shutdown_report_human` | 113 | 118 | Below the 150-line threshold |
| `print_shutdown_report_json` | 134 | 137 | Below the 150-line threshold |
| `main` | 429 | 511 | 11 |
| Main's executor worker lambda | 81 | 84 | Within the enclosing boot phases |
| Main's IO worker lambda | 80 | 87 | Within the enclosing boot phases |

Code-line counts use lines containing A1 lexer tokens from opening through
closing brace, including nested lambdas. Physical lengths include comments and
blank lines. All four bodies exceeding 150 physical lines have landmarks.
Generated boot receives the six boot landmarks and the worker contract through
`tests/r7shadow_sync.py --write`; contracts for other generated methods belong
at their mainline inputs, outside this lane's ownership.

No interface-first split qualifies. The largest handwritten class is
`ShadowReorderQueues`, 226 physical lines including fields/comments, followed by
`FusedBootGate` at 181 and `ExReorderQueues` at 146. None has approximately 300
lines of in-class member bodies. The large generated demotion class is protected.
Splits attempted/kept/reverted: **0/0/0**.
