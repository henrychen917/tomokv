# Known issues — epyc-hardening-dev (2026-08-15)

1. Small-pool auto-flip p32-SET regression (bisected to the thread-identity
   commit; grow-back direction only). 8-thread-pool `thread-mode auto` under
   sustained p32 SET: anti-thrash 9 flips (baseline <=1), long-hold 13-19 late
   flips (baseline 2), auto lands ~16-18% below best-static (baseline 0.2%).
   Unaffected: p1/GET workloads (clean), grow-front, static mode, pools >16
   (episode-validated io60/ex4 @3.2-3.5M). An explicit grow-back LANDED-edge
   delay was implemented and probe-validated NOT to be the mechanism (kept out).
   Suspect: dormant-drain service cadence changed by the adoption rework.
   Tracking: controller_sweep 1-flip p32 cells.
2. Bergamo calibration class (fails on EVERY binary incl. pre-regression):
   controller convergence-p32 settle window (321s vs 320s ladder) and EXBOUND
   grow-back-to-floor. Suite expectations were tuned on the 7700X.
3. shared_refcount_race / numcmd discrimination arms need the archived
   defect-reintroduced binaries (old box); INCONCLUSIVE here by construction.
4. ASAN-timing-only io-thread starvation residual: not reproduced since the
   identity merge (240s + cycling clean); evidence archived in session notes.
