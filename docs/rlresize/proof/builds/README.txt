PRE  : git archive 991d48f65 -> build/rlresize/pre-src; taskset -c 80-95 make -j16 all (exit 0)
       -> build/rlresize/pre-src/build/tomokv sha256 a2e29e80550370edf1538d1f5866d0467b8975582366f48af0ed88a627d9eed8
POST : taskset -c 80-95 make -j16 all at 986bd6f10 (exit 0, 0 warnings, `make -q all` fresh)
       -> build/tomokv sha256 749b696aa87febb9ebf115ac82cb0c553e9d4624c4c224a6161ff5e29afc13a5
production units: the 29 targets of tests/gate.sh job_production_units, `make -k -j16` exit 0 (221 s),
       29/29 `make -q` fresh, then `make -j16 mdbqsbr-live-arms` exit 0 (138 s). Warnings only in
       tests/atomic_survivors_unit.cc (3), tests/lbplanner_unit.cc (10) and the wbland-controls copy
       of src/core/wb_rule.h (1), all pre-existing.
