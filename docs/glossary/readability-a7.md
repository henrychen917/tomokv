# Controller terms

Definitions describe the current source. They are not performance claims.

| Term | Definition | Owning file |
|---|---|---|
| FLIP | A staged change to the IO/EX role split, including client and shard handover. The controller proposes a split; Server and the role loops execute it. | `src/core/flipctl.cc`, protocol in `src/core/server.h` and `src/core/io_loop.h` |
| LB | Load balancing that moves a client or shard between existing owners without changing role counts. | `src/core/lbplanner.cc` |
| IO / Ifid | The role that owns connection parsing, receive/send state and reply retirement. `Ifid` is the role enumerator used by these controllers. | `src/core/placement.h`, enum in `src/core/thread.h` |
| EX | The executor role that owns shard execution in split mode. | `src/core/placement.h`, enum in `src/core/thread.h` |
| Fused / split | In fused mode selected threads serve clients and execute; split mode assigns distinct IO and EX roles. Fused placement exposes the same ids in both fanout views. | `src/core/placement.h` |
| Placement | Dense thread ids, CPU/L3 facts, role lists, SMT peers and initial shard homes. Runtime role-list mutation requires FLIP quiescence. | `src/core/placement.h` |
| SMT unit | A validated reciprocal pair of CPU siblings that shares a role and moves together. | `src/core/placement.h` |
| Coordinator | The IO chosen to advance a staged ownership transaction after participants acknowledge their obligations. | `src/core/lbplanner.cc`, FLIP control in `src/core/io_loop.h` |
| Fingerprint | Sampled command-class counts, multikey key counts, value bytes and parse-pass depths used to describe workload. | `src/core/flipctl.h` |
| Sampled parse pass | A pass in which every admitted frame contributes to the fingerprint. Random gaps between sampled passes have mean W. | `src/core/flipctl.h` |
| Cumulative publication | Monotonic totals published with a release-stored window count. The reader acquires that count, then reads counters and subtracts its previous totals; fields can include later work. | `src/core/flipctl.h` |
| Signature | Normalized command mix and per-command/per-multikey averages, plus diagnostic pass-depth proportions. | `src/core/flipctl.cc` |
| Anchor | A settled split, rate reference and fingerprint against which subsequent workload changes are judged. | `src/core/flipctl.cc` |
| Maneuver | A controller episode that measures demand, proposes a target, verifies its outcome and settles an anchor; it can also hold without moving. | `src/core/flipctl.cc` |
| Demand | Role work estimated from the controller window's wall time minus the loop's booked idle time. IO/EX operation counters use different units and are not separate divisors for this estimate. | `src/core/flipctl.cc`, `src/core/flip_policy.h` |
| Headroom | A role's minimum thread idle fraction over a demand window: the idle share of its busiest thread. | `src/core/flipctl.cc` |
| Stabilized reading | The mean of two adjacent rate windows whose relative difference fits the controller's noise band. Adjacent readings can overlap. | `src/core/flipctl.cc` |
| Band | A threshold informed by observed noise and sampling resolution. Different bands judge fingerprint distance, rates and LB imbalance. | `src/core/flipctl.cc`, `src/core/weighted_lb.h` |
| Sampling floor | A statistical resolution floor derived from the number of samples and, for LB, the number of compared owner pairs. | `src/core/flipctl.cc`, `src/core/weighted_lb.h` |
| EWMA | An exponentially weighted moving average. Several controller estimates use it; their coefficients and admission rules differ. | `src/core/flipctl.cc`, `src/core/flip_policy.h` |
| Welford window | Running sample count, mean and squared-deviation accumulator used for demand/rate variance. | `src/core/flip_policy.h` |
| Hypothesis | A target split with a predicted gain, origin baseline and planned verification readings. | `src/core/flipctl.h` |
| Kappa | A calibration factor in [0,1] relating accumulated raw predicted gains to credited delivered gains. | `src/core/flip_policy.h` |
| Blackout | The cost model's interval covering flip, settling and planned target readings while the new placement remains unverified. | `src/core/flipctl.cc` |
| Cost gate | A comparison of credited commands gained over the demonstrated stationary horizon against transfer, possible return and blackout costs. | `src/core/flip_policy.h` |
| Refinement | Remeasuring demand after a delivered move and considering another verified step; visited splits and model error can stop the search. | `src/core/flipctl.cc` |
| Null maneuver | A workload-triggered episode that ends at its starting split; it increases the responsible detector's confirmation requirement. | `src/core/flipctl.cc` |
| Round trip | A failed target hypothesis that returns to its departure split, including a failed refinement returning to an earlier successful landing. | `src/core/flipctl.cc` |
| Invalidation | Discarding an automatic hypothesis after manual intervention, or declining to charge a returned miss when baseline movement would change its verdict. | `src/core/flipctl.cc` |
| Weighted partition | A largest-first assignment respecting pinned items and floor/ceil counts, with demand first and bytes as an independent secondary objective. | `src/core/weighted_lb.h` |
| Incremental move | One unpinned item reassignment that improves the active spread objective. Count spread and stable ids break ties. | `src/core/weighted_lb.h`, damped key objective in `src/core/lbplanner.cc` |
| Dominant bucket | A shard whose indivisible load limits what the single-owner placement actuator can rebalance. The key planner can refuse such evidence. | `src/core/lbplanner.cc`, evidence gathering in `src/core/server.h` |
| Hysteresis / Schmitt band | Admission requires sustained crossings of a firing threshold; a lower release threshold clears the streak. | `src/core/lbplanner.cc` |
| Damping | Recent completed key moves raise required sustain and the firing band, with bounded decay over controller time. | `src/core/lbplanner.cc` |
| Cooldown | A period that pins a recently moved/refused item against selection. Its duration covers a fresh decision window and reflects measured transfer cost. | `src/core/weighted_lb.h`, `src/core/lbstall.cc` |
| PlanReady | The LB stage publishing a completed monitor plan for its IO coordinator to consume after epoch and reader checks. | `src/core/lbplanner.cc` |
| Drain | Stop relevant new admission while completing the work and lifetime obligations required before a transfer. | `src/core/lbstall.cc`, protocols in `src/core/io_loop.h` |
| IoDrain / ExDrain | FLIP/LB stages that fence IO publications and executor work, respectively; their acknowledgements have stage-specific conditions. | `src/core/io_loop.h`, `src/core/ex_loop.h` |
| ClientPrepare / ClientCommit / ClientInstall | FLIP stages for reversible client preparation, ownership publication/transfer and destination installation/draining. | `src/core/io_loop.h`, liveness predicates in `src/cmd/flip_liveness.inc` |
| Quiesce | Establish that relevant admitted work has retired and no forbidden new publication can occur. Queue depth zero alone does not establish this. | `src/core/signal.h`, `src/core/placement.h` |
| Retired frontier | The queue position advanced after processing, distinct from the pop/head frontier. Ownership changes need completion-aware quiescence. | `src/exec/exqueue.h`, exposed by `src/core/signal.h` |
| Park | A worker's blocked wait after publishing blocked intent and rechecking work. LB can also temporarily hold a client's input behind its readiness fence. | `src/core/signal.h`, `src/core/lbstall.cc` |
| Doorbell | The process eventfd used for nonterminal save requests and a terminal shutdown wake restored by the terminal latch if a drain races it. | `src/core/signal_doorbell.h` |
| Notify mask | Producer-indexed work-summary bits taken before draining channels. Publishing a queue item requires the accompanying ordering/wake protocol. | `src/core/signal.h` |
| Ready mask | Writeback-slot completion bits mapped to clients by the owning IO. Slot reuse requires clearing after completion quiescence. | `src/core/signal.h` |
| Write-back rule | The IO eligibility rule combining bounded small-pipeline completion visits, staged/reply bytes and a contiguous Done prefix. | `src/core/wb_rule.h` |
| FIFO serve pin | `serve_pending` keeps a queued/deferred client alive until IO removes it from the ready-client FIFO. FLIP can also hold output with this pin. | `src/core/wb_rule.h`, `src/cmd/flip_liveness.inc` |
| Borrow hold | FLIP's deferral of borrowed-output release callbacks until final executor masks are installed; release uses the new shard route. | `src/cmd/flip_liveness.inc` |
| Stayer | A connection retained on a surviving IO, including blocked/TLS/non-draining cases that a converting IO cannot keep. | `src/cmd/flip_liveness.inc` |
| Listener home / owner / target | Stable listener slot id, current physical IO issuer and prepared destination issuer, respectively. | `src/core/fliplisten.cc` |
| Retained fd | A successful accept held in a bounded per-IO linked list while client admission is paused, then admitted after the epoch barrier. | `src/core/fliplisten.cc` |
| Rebind rendezvous | CONFIG's exclusive worker callback with barriers around listener/AOF preparation, cancellation and commit. | `src/core/fliplisten.cc` |
| FIN / EOF | A FIN edge can accompany positive input; actual receive EOF ends input. Deferred timers let complete frames and outstanding replies drain. | `src/core/eof.cc` |
| Tenure | One invocation of an IO loop, whose accounting interval ends before teardown and excludes executor-role time. | `src/core/signalacct.h` |
| hz | The Redis-compatible client-cron frequency, parsed/clamped to 1..500 and optionally increased according to client count. | `src/core/client_hz.h` |
| Behaviour twin / PAD-A | An offline copied-binary control that selects comparison behavior while preserving candidate text layout; it is not a runtime controller mode. | `src/core/lbplanner.cc`, `src/core/flipctl.cc`, `src/cmd/flip_liveness.inc` |
