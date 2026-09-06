#!/bin/bash
# FALSIFIABILITY. Each mutation below breaks one thing the new cases claim to police; the unit
# binary must FAIL for each, and the tree is restored after every arm. Run from the worktree root.
#
# A mutation table only means something beside a control: M0 is the unmutated tree, which must pass
# every case. A suite that fails for every mutation but also fails clean is measuring nothing.
set -u
CXXF="-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -I."
ORIG=$(mktemp /tmp/rob.h.orig.XXXXXX)
cp src/net/rob.h "$ORIG"
# The tree is restored even if this script is interrupted: leaving a mutated header behind is how a
# lane commits a mutation.
restore(){ cp "$ORIG" src/net/rob.h; }
trap 'restore; rm -f "$ORIG"' EXIT INT TERM

run(){ # run <name> <python-mutation>   ("" = the unmutated control)
  if [ -n "$2" ]; then
    local before after
    before=$(md5sum src/net/rob.h | cut -d" " -f1)
    python3 -c "$2" || { restore; echo "== $1 =="; echo "  PATCH FAILED (the mutation no longer applies -- fix it, do not skip it)"; return; }
    after=$(md5sum src/net/rob.h | cut -d" " -f1)
    # A MUTATION THAT DID NOT MUTATE IS THE WORST ROW IN THE TABLE: it compiles the unmutated tree,
    # passes, and reads as a survived mutation. Digested rather than trusted, so that a pattern
    # which goes stale (as three did when the ring capacity stopped being a literal) is loud.
    if [ "$before" = "$after" ]; then
      restore; echo "== $1 =="
      echo "  PATCH MATCHED NOTHING (the file is unchanged -- this row would have been vacuous)"
      return
    fi
  fi
  if ! g++ $CXXF tests/read_local_write_ring_unit.cc -o /tmp/rlwru-mut 2>/tmp/rlwru-mut.log; then
    echo "== $1 =="; echo "  DID NOT COMPILE (the static_assert caught it first):"
    grep -m2 "static assertion failed" /tmp/rlwru-mut.log | sed 's/^/    /'
    restore; return
  fi
  echo "== $1 =="
  /tmp/rlwru-mut | grep -E "^  FAIL|^read_local write ring unit" | sed 's/^/  /'
  restore
}

run "M0 CONTROL: the unmutated tree" ""
run "M1 ring back to sixteen slots" "
s=open('src/net/rob.h').read()
s=s.replace('static constexpr uint32_t kWriteRingCapacity = kRobWindow;','static constexpr uint32_t kWriteRingCapacity = 16;',1)
open('src/net/rob.h','w').write(s)"

run "M1b ring back to sixteen, sizeof lock removed" "
s=open('src/net/rob.h').read()
s=s.replace('static constexpr uint32_t kWriteRingCapacity = kRobWindow;','static constexpr uint32_t kWriteRingCapacity = 16;',1)
s=s.replace('''static_assert(sizeof(ReadLocalRobState) == 1216,
              \"the armed read-local sidecar grew: re-measure RSS per armed connection\");''','',1)
open('src/net/rob.h','w').write(s)"

run "M1c ring back to sixteen, BOTH structural locks removed" "
s=open('src/net/rob.h').read()
s=s.replace('static constexpr uint32_t kWriteRingCapacity = kRobWindow;','static constexpr uint32_t kWriteRingCapacity = 16;',1)
s=s.replace('''static_assert(sizeof(ReadLocalRobState) == 1216,
              \"the armed read-local sidecar grew: re-measure RSS per armed connection\");''','',1)
s=s.replace('''    static_assert(ReadLocalRobState::kWriteRingCapacity >= Capacity,
                  \"the RYOW write ring must cover the whole ROB window\");''','',1)
open('src/net/rob.h','w').write(s)"

run "M2 tag sweep stops after the first live group" "
s=open('src/net/rob.h').read()
old='        } while (rest);'
assert old in s, 'M2: sweep loop tail not found'
s=s.replace(old,'        } while (false);',1)
open('src/net/rob.h','w').write(s)"

run "M2b group walk clears two groups a step, skipping every other one" "
s=open('src/net/rob.h').read()
old='            rest &= ~(uint64_t{0xFFFF} << shift);'
assert old in s, 'M2b: group-clear not found'
s=s.replace(old,'            rest &= ~(uint64_t{0xFFFFFFFF} << shift);',1)
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

# ---------------------------------------------------------------------------------------------
# D1 IS NOT A FALSIFICATION ROW, IT IS THE DERIVATION CHECK. kWriteRingCapacity = kRobWindow is a
# claim that the ring follows the window; the way to test that claim is to move the window and see
# whether the ring moved with it. If the ring still carried its own literal 64, shrinking the
# window to 32 would leave sizeof(ReadLocalRobState) at 1216 and the build would be silent. It is
# not silent: the sidecar's own cost lock fires (the ring really did shrink), and so does the Rob's
# structural assert (Rob<64> still exists, and a 32-slot ring cannot cover a 64-wide window). Two
# independent locks noticing is the evidence that the two numbers are one number.
run "D1 DERIVATION: shrink the ROB window to 32 -- does the ring follow?" "
s=open('src/net/rob.h').read()
old='inline constexpr uint32_t kRobWindow = 64;'
assert old in s, 'D1: kRobWindow definition not found'
s=s.replace(old,'inline constexpr uint32_t kRobWindow = 32;',1)
open('src/net/rob.h','w').write(s)"
