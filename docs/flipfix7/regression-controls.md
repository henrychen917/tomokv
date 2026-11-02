# Regression controls

The first final-arm regression run, `gate-run.ksydPR`, rejected two stale
structural expectations. The failed ledger is retained; it is not a green run.
Neither correction changes the production binary.

`wbland_units` completed its initial 48 behavioural outcomes, then rejected the
old inline `flip_io_drained` source anchor. The coordinator drain check now lives
in `src/cmd/flip_liveness.inc`, and the timer check uses `flip_timers_drained`.
The envelope now scans that helper too, requires every serve-pin reference at an
exact owning-method site, and retains all existing policy-call and hot-path
constraints. Four new disposable source controls remove the send fence, remove
the adoption pin guard, remove the coordinator serve fence, or inject a stray
policy call. Each must fail at the corresponding assertion.

`reorder_identity` rejected the frozen wave14 symbol inventory. Diagnosis found
all 325 previous physical bodies plus exactly one ordinary DB0 `xshard_execute`
scan callback; no body disappeared. See `reorder-inventory-diagnosis.json`.
The explicit `flipfix7` inventory requires all 326 bodies, preserving the
historical wave14 option. The FIFO behaviour twin comparison includes the added
callback's full instructions and literal pools. New negative controls remove
that exact callback and change its opcode; neither is permitted to pass.

The corrected jobs are rerun through `tests/gate.sh` using the `controls` phase
of `tools/flipfix7_proof.py`. Their separate receipt determines the outcome.

The native run also exposed an overbroad proof-only exclusion: omitting
`stream.py --release-build` skipped its three memory assertions, despite those
assertions containing no timing measurement. The original release flag is
restored for both stream battery call sites. The `controls` phase repeats all
four split/armed atomic feature jobs with those assertions enabled; the epoll
regression selection also includes them. Only the separate `xmove` size-ratio
timing subtest remains excluded by the proof-only flag.

Corrected result: `gate-run.IWv7UP`, **144 passed / 0 failed**. Writeback clauses
passed 95/95 strict outcomes and paths passed 16/16; all four new FLIP source
mutants failed with the required assertion and exit 1. The FIFO twin matched
326/326 required bodies and passed the identity negative controls. All twelve
stream memory assertions passed across the four repeated feature batteries.
See `gate-controls-uring-delivery.ledger`, its evidence archive, and
`stream-memory-verification.json`.
