#!/bin/bash
# wave3: the serverless self-test set, CPUs 80-95.
#  A. On this tree: python3 tests/gates_test.py (all), tests/abbagate.py --self-test, and the
#     nullpublish4 set (gate_receipt.py --self-test, abba_instrument.py --self-test,
#     nullpublish4_test.py, nullpublish_refreeze_test.py, _nullrefresh_test.py), each logged with
#     its exit code.
#  B. The gate's abba_selftest row chain, exactly as job_abba_selftest runs it, twice: on this tree
#     (EXPECT stays 637/654, so gate_receipt.py's ledger-fixture control must refuse: fixture 681 vs
#     EXPECT_FULL 654) and on a disposable snapshot of HEAD (git archive + a throwaway git repo under
#     build/wave3/) whose only change is EXPECT_QUICK=664 / EXPECT_FULL=681, the counts this branch
#     declares. Never edits this tree's EXPECT.
# usage: selftests.sh <out-dir>
set -u
WT=/home/user/Projects/cx-wave3
OUT=$(realpath -m "$1"); mkdir -p "$OUT"
cd "$WT"
: > "$OUT/exits.txt"
run(){ local name=$1; shift; local start=$(date +%s); taskset -c 80-95 "$@" > "$OUT/$name.log" 2>&1; echo "$name rc=$? seconds=$(( $(date +%s) - start ))" | tee -a "$OUT/exits.txt"; }
run gates_test python3 tests/gates_test.py
run abbagate_selftest python3 tests/abbagate.py --self-test
run gate_receipt_selftest python3 tests/gate_receipt.py --self-test
run abba_instrument_selftest python3 tests/abba_instrument.py --self-test
run nullpublish4_test python3 tests/nullpublish4_test.py
run nullpublish_refreeze_test python3 tests/nullpublish_refreeze_test.py
run nullrefresh_test python3 tests/_nullrefresh_test.py
chain(){ # dir label
  ( cd "$1" && for t in "tests/abbagate.py --self-test" "tests/gate_quiet.py --self-test" \
      "tests/gate_measurements.py --self-test" "tests/gate_receipt.py --self-test" \
      "tests/abba_instrument.py --self-test" tests/background_environment_test.py \
      "tests/gate_history.py self-test" tests/gate_process_test.py tests/gates_test.py \
      tests/gate_subset_test.py "tests/wb_policy.py --self-test" "tests/lb_stationary.py --self-test" \
      "tests/netio.py --self-test" "tests/gateprod.py --self-test" "tests/tailgen_stall.py --self-test"; do
      taskset -c 80-95 python3 $t >> "$OUT/$2.log" 2>&1 || { echo "$2 FAILED AT: $t" | tee -a "$OUT/exits.txt"; exit 1; }
    done; echo "$2 chain PASS" | tee -a "$OUT/exits.txt" )
}
chain "$WT" abba-chain-tree
COPY=$WT/build/wave3/expect-copy
[ ! -e "$COPY" ] || { echo "refusing existing $COPY" >&2; exit 2; }
mkdir -p "$COPY" && git -C "$WT" archive HEAD | tar -x -C "$COPY"
sed -i 's/^EXPECT_QUICK=637$/EXPECT_QUICK=664/; s/^EXPECT_FULL=654 /EXPECT_FULL=681 /' "$COPY/tests/gate.sh"
diff <(git -C "$WT" show HEAD:tests/gate.sh) "$COPY/tests/gate.sh" > "$OUT/expect-copy.diff"
( cd "$COPY" && git init -q && git add -A && git -c user.name=wave3 -c user.email=wave3@localhost commit -q -m 'wave3 EXPECT-only snapshot' )
chain "$COPY" abba-chain-expect-664-681
