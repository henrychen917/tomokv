# N1/N2 identity restoration attempt

Source at `dd5a6ff6c`, reference `567d3b8e3`. No production function was edited
for this attempt. `docs/ntfix/budget.py` uses the PRE production compiler commands,
changes only `large-unit-insns`, and compiles on CPUs 96–111 with at most 16
compiler children. Each receipt contains the command, source digest, object
digest, initial IPA unit size, and every changed emitted body with both sizes.
The canonical byte/relocation comparison is `tools/ccfix_audit.py`'s.

`units/jobs.json` covers PRE and POST for the four units responsible for the
11 selected hot-body differences. All four grow by 40 initial IPA instructions.
Recompiling PRE reproduces every reference body (zero differences).
`round1/jobs.json` scans budget increments 24, 36, 40 and 52 for all four units.
`round2/jobs.json` refines db0 reorder at 148395–148407 (148398 was in round 1).

| Object | Previous budget | Chosen budget | Hot bodies changed before → after |
|---|---:|---:|---:|
| `src/core/genthread.o` | 129447 | 129487 | 2 → 0 |
| `db0/src/core/genthread.o` | 129704 | 129744 | 2 → 0 |
| `src/core/rl2s.o` | 162305 | 162357 | 2 → 0 |
| `db0/src/core/reorder.o` | 148358 | 148398 | 5 → 1 |

Selection: fewest changed hot bodies, then fewest other bodies, then nearest
the headroom-preserving increment (+40). The remaining hot difference is
`tomo_db0::ExLoopT<true>::r7_fused_sweep_impl<32u, true, false, false>()`,
796 → 729 bytes. The changed header alters GCC's inline/codegen decisions;
the sweep retains the same named calls but changes instruction/control-flow
placement (`sweep-pre.asm` and `sweep-post.asm`). It was not edited by this
lane. This residual difference is admitted for merit review by ntfix2's rule.
N3/N4 have not yet been applied to this identity-attempt snapshot.

The additional changed `IoLoop::close_client` copies include the N2 TLS pump.
The db0 reorder receipt also lists `FlatStore::budget_admit` (register/codegen),
`FlatStore::scan_home` and `IoLoop::flip_io_drained` (inline/codegen), and the
newly outlined `Rob<64u>::quiesced` body. These changes are fully inventoried,
not hidden by changing the comparison tools.
