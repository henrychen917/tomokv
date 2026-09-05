#!/bin/bash
# THE TWO SHAPES OF THE SWEEP, DISASSEMBLED SIDE BY SIDE.
#
# Sizing the ring to the ROB window quadruples the number of tags a disjoint read may have to
# reject, and how much that costs is a codegen question, not an algorithmic one. This script answers
# the SHAPE half of it: whether GCC vectorises the sweep. It deliberately does not answer the cost
# half, because a static listing cannot -- the rejected flat form compiles to a compact 64-trip
# scalar loop and therefore looks SMALLER here while costing eight times more to run. Read this for
# "is there a vpcmpeqw", and probe_cost.sh for instructions per rejected probe.
#
# The tree is patched in place and restored by a trap, exactly as mutate.sh does. Nothing is
# stashed.
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/scratchpad/ringsize"
CXXF="-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -I."
cd "$ROOT"
KEEP=$(mktemp /tmp/ringsize-rob-keep.XXXXXX.h)
cp src/net/rob.h "$KEEP"
trap 'cp "$KEEP" src/net/rob.h; rm -f "$KEEP"' EXIT INT TERM

report(){ # report <label>
  g++ $CXXF -c "$HERE/codegen.cc" -o /tmp/ringsize-codegen.o
  objdump -d --no-show-raw-insn /tmp/ringsize-codegen.o \
    | awk '/<ringsize_probe>:/,/^$/' > "/tmp/ringsize-probe-$1.asm"
  printf '%-28s %4s instructions, %2s vector compares (%s)\n' "$1" \
    "$(grep -cE '^\s+[0-9a-f]+:' "/tmp/ringsize-probe-$1.asm")" \
    "$(grep -cE 'vpcmpeq' "/tmp/ringsize-probe-$1.asm" || true)" \
    "/tmp/ringsize-probe-$1.asm"
}

report "grouped (shipped)"

python3 - <<'PY'
s = open('src/net/rob.h').read()
start = s.index('        uint64_t rest = live;')
end = s.index('        return false;\n    }', start)
naive = '''        uint64_t hits = 0;
        for (uint32_t i = 0; i < ReadLocalRobState::kWriteRingCapacity; i++)
            hits |= static_cast<uint64_t>(tags[i] == tag) << i;
        if (hits & live) return true;
'''
open('src/net/rob.h', 'w').write(s[:start] + naive + s[end:])
PY
report "flat 64-lane (rejected)"
