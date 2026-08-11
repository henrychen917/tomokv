HARNESS/GATE COVERAGE for the FINAL knob surface (owner decision). The
surviving knobs below must each have REAL cells in tools/preflight — the
drift-guard principle: a live knob with no cell is "LIVE BUT UNTESTED".
AUDIT tools/preflight/knob_matrix.sh (and where noted, the other suites) for
existing coverage of each survivor, then ADD what is missing, following the
file's existing try()/must_refuse() patterns exactly:
1. tomokv-key-lb: cells for 0 (balancer off — assert no reshard log lines
   under a short skewed load) and the default 20000 (echo + serve). The
   BEHAVIOR gate already exists (keylb_veto.sh, reshard_suite.sh) — just
   verify they run under the current default and reference them in a comment.
2. tomokv-client-lb: yes/no boot cells; for "no", assert the rebalance log
   line does NOT appear under a brief unbalanced connect pattern; for "yes"
   (default) echo + serve is enough (the balancer's own suite covers depth).
3. tomokv-thread-mode: explicit static AND auto boot cells (auto is the
   default the whole matrix runs under — add the static cell if missing, and
   in the static cell assert no flip-ctl lines appear).
4. tomokv-cores-per-node: 0 (derive) and an explicit value equal to
   thread-io+thread-ex; a mismatched explicit value must boot-refuse if the
   code enforces it (check the boot validation and encode whichever contract
   exists).
5. tomokv-reshard-fence-timeout: echo cell + one out-of-range must_refuse.
6. tomokv-zerocopy-min-value: cells 0 (off), default 1024, and 65536; add a
   VALUE-CORRECTNESS smoke: SET a 32KB value, GET it back byte-identical at
   each setting (the zero-copy forwarding path's contract).
7. tomokv-reorder: cells 0..3 (echo+serve); if any are missing add them; the
   RYOW behavior gate lives in client_correctness (referenced by the ownread
   gauntlet) — comment-reference it.
8. tomokv-strict-order: cells 0, 1, and one eps value (e.g. 50); echo+serve.
9. tomokv-os-opts / tomokv-os-busypoll: boot cells yes/no (immutable bools);
   busypoll=yes may need privileges — if boot fails from lack of privilege,
   accept refusal WITH the privilege message as a pass (encode that).
10. tomokv-io-uring: keep the existing 0 cell; extend the comment that
    nonzero requires USE_URING (already the case).
11. tomokv-atomic / tomokv-atomic-window: cells exist from 2026-08-10 —
    verify, do not duplicate.
DO NOT touch the prefetch knob cells (another agent owns those) and do not
touch deleted-knob cells (a third agent adds their must_refuse lines).
HARNESS CODE ONLY — no src/ changes. Never run make/compile/servers/benches.
git add -A + commit with a per-knob coverage table in the message.
