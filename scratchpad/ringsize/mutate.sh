#!/bin/bash
# FALSIFIABILITY. Each mutation below breaks one thing the new cases claim to police; the unit
# binary must FAIL for each, and the tree is restored after every arm. Run from the worktree root.
set -u
CXXF="-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -I."
run(){ # run <name> <python-mutation>
  cp src/net/rob.h /tmp/rob.h.orig
  python3 -c "$2" || { cp /tmp/rob.h.orig src/net/rob.h; echo "MUTATE $1: patch failed"; return; }
  if ! g++ $CXXF tests/read_local_write_ring_unit.cc -o /tmp/rlwru-mut 2>/tmp/rlwru-mut.log; then
    echo "== $1 =="; echo "  DID NOT COMPILE (the static_assert caught it first):"
    grep -m2 "static assertion failed" /tmp/rlwru-mut.log | sed 's/^/    /'
    cp /tmp/rob.h.orig src/net/rob.h; return
  fi
  echo "== $1 =="
  /tmp/rlwru-mut | grep -E "^  FAIL|^read_local write ring unit" | sed 's/^/  /'
  cp /tmp/rob.h.orig src/net/rob.h
}

run "M1 ring back to sixteen slots" "
import re
s=open('src/net/rob.h').read()
s=s.replace('static constexpr uint32_t kWriteRingCapacity = 64;','static constexpr uint32_t kWriteRingCapacity = 16;',1)
open('src/net/rob.h','w').write(s)"

run "M1b ring back to sixteen, structural assert also removed" "
s=open('src/net/rob.h').read()
s=s.replace('static constexpr uint32_t kWriteRingCapacity = 64;','static constexpr uint32_t kWriteRingCapacity = 16;',1)
s=s.replace('''    static_assert(ReadLocalRobState::kWriteRingCapacity >= Capacity,
                  \"the RYOW write ring must cover the whole ROB window\");''','',1)
open('src/net/rob.h','w').write(s)"

run "M2 tag scan covers only the first sixteen slots" "
s=open('src/net/rob.h').read()
s=s.replace('''        for (uint32_t i = 0; i < ReadLocalRobState::kWriteRingCapacity; i++)
            hits |= static_cast<uint64_t>(tags[i] == tag) << i;''','''        for (uint32_t i = 0; i < 16; i++)
            hits |= static_cast<uint64_t>(tags[i] == tag) << i;''',1)
open('src/net/rob.h','w').write(s)"

run "M3 conservative generation stops forcing the exact path" "
s=open('src/net/rob.h').read()
s=s.replace('''        read_local_write_reset_slots();
        read_local_write_force_ = 1;''','''        read_local_write_reset_slots();''',1)
open('src/net/rob.h','w').write(s)"

run "M4 tag store dropped on ring insert (the base lane's mutation)" "
s=open('src/net/rob.h').read()
s=s.replace('        state.write_tags[tail] = static_cast<uint16_t>(hash);','',1)
open('src/net/rob.h','w').write(s)"
