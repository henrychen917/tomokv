# 5 — QuietJitter::band default: LIVE in two tests; retained

PRE is `dab740964` (tag `deadswitch-before-20261009`). Production POST is
unchanged for this candidate. Five production call sites in `lbplanner.cc`
pass the actual owner count. `config_parser_test.cc:556,558` instead calls
`noise.band()` and explicitly compares against `sampling_floor(2)`.
These are the requested two-owner-assumption findings, not deletion permission.

The negative compile copies only `weighted_lb.h` under
`build/deadswitch/owners-probe/src/core/`, removes ` = 2` from `band`, and runs:

```
g++ -std=c++20 -O2 -fsyntax-only -Ibuild/deadswitch/owners-probe \
  -iquote src/core -I. tests/config_parser_test.cc
```

`05-default-removed.log` must contain exactly the two missing-argument errors.
The same compile without the overlay succeeds (`05-default-retained.log`).
Other `.band()` calls belong to the flip detector, not QuietJitter; they are
not claimed as consumers of this default. `text-before.txt` retains the grep.

No source or gate row changed: +0 quick / +0 full. No performance claim.
