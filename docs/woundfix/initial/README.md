# Superseded diagnostic runs

These records describe the first implementation of DEFECT §6, before
`f90cfa1f3` closed the additional independent-abort/wound overlap. They are
retained diagnostics, not proof of the final binary.

- `abort-gap.log`: a placement OOM in the phase/epoch gap still accepted a ticket.
  The combined regression was committed before the extra production correction.
- `instructions/`, PAD controls and the partial live records concern that
  superseded binary; final results live one directory above.
- `units-gate-interrupted.log`: intentionally stopped when production code
  needed the combined-abort correction; no passing gate claim.
- `gates_test-busy.log`: 12 scheduler fixture timeouts while builds, traces and
  intentional CPU stress shared the lane. The final idle-lane run is
  `../gates_test.log` (72 tests passed at unchanged deadlines).
