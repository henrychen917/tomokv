#!/bin/bash
# ver2.sh -- the rows ver.sh got wrong, re-run. tests/spinprobe.py takes the server's PID as its
# second argument (gate.sh passes $SRV, which is a pid, not a path); ver.sh handed it the binary
# path and the row died on argument parsing in both thread modes. This is the row that most
# directly guards the ex-loop accounting change, so it does not get to stay unmeasured.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
cd "$WT"
LG(){ echo "$(date +%T) $*"; }
wait_gate(){ local n=0; while ! gate_ok; do [ $((n%10)) = 0 ] && LG "paused"; n=$((n+1)); sleep 30; done; }
SRV8=52,53,54,55,180,181,182,183; LG8=56,57,184,185
boot8(){ local SRV_CPUS=$SRV8; boot "$@"; }
run(){ # run TAG PID ARGS...
  local tag=$1 spid=$2; shift 2
  local out; out=$SP/fd-spin-$tag.txt
  taskset -c "$LG8" python3 tests/spinprobe.py "$PORT_BAT" "$spid" "$@" >"$out" 2>&1
  LG "SPINPROBE $tag rc=$? :: $(tail -1 "$out" | cut -c1-160)"
}
if [ ! -s "$SP/fd-spin-2s.txt" ]; then
  wait_gate
  pid=$(boot8 "$FIX_BIN" "$PORT_BAT" spin2s --ratio 6:2 --enable-debug-command yes) && {
    run 2s "$pid"; run 2s-idle "$pid" --idle-only; stop "$pid" "$PORT_BAT"; }
fi
for AT in 0 1; do
  [ -s "$SP/fd-spin-1s-$AT.txt" ] && continue
  wait_gate
  pid=$(boot8 "$FIX_BIN" "$PORT_BAT" "spin1s-$AT" --thread-mode 1s --atomic "$AT" --enable-debug-command yes) && {
    run "1s-$AT" "$pid"; run "1s-$AT-idle" "$pid" --idle-only; stop "$pid" "$PORT_BAT"; }
done
# Same rows on the BASE binary: an idle-loop ceiling is only evidence about the change if the
# unchanged server clears the same bar on the same box.
if [ ! -s "$SP/fd-spin-base-2s.txt" ]; then
  wait_gate
  pid=$(boot8 "$BASE_BIN" "$PORT_BAT" spinbase --ratio 6:2 --enable-debug-command yes) && {
    run base-2s "$pid"; run base-2s-idle "$pid" --idle-only; stop "$pid" "$PORT_BAT"; }
fi
python3 scratch/report.py "$SP/fd-report.html" 2>&1 | tail -1
LG "VER2 DONE"; touch "$SP/fd-ver2.done"
