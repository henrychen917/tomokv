#!/bin/bash
# RE-ARM AFTER THE OWNER TAKES THE BOX BACK, AND DO NOT REDO WHAT IS ALREADY DONE.
#
# run_when_clear.sh gives the box back the moment quiet.done disappears, which is right, and then it
# exits -- which leaves the lane idle until somebody notices. On a contested box that is most of the
# night. This loops it: wait, run, and if the owner reclaims the box (rc=2) go back to waiting.
#
# The phase list SHRINKS as phases finish. Each phase's rendered .txt is written only after its last
# visit, so its presence is the completion marker -- which is why the pre-fix copies of those files
# were quarantined first: a stale artifact would mark a phase done that this run never ran.
#
#   keep_running.sh <phase> [phase ...]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/ringsize}"
DEADLINE=$(( $(date +%s) + ${TOTAL_S:-25200} ))

# A PHASE IS DONE WHEN IT HAS ENOUGH BALANCED VISITS, NOT WHEN ITS SCRIPT HAPPENS TO REACH THE END.
# On a box whose windows are shorter than a phase, "the .txt exists" never becomes true and the
# lane collects rows forever without ever rendering one. The bar instead is the DATA: at least
# MIN_VISITS distinct visits for each arm, which for the ABBA order means at least one complete
# round's worth on both sides. Rendering happens after every attempt regardless, so a table exists
# from the first cell onward and gets better rather than appearing all at once.
MIN_VISITS=${MIN_VISITS:-2}

csv_for(){
  case "$1" in
    null) echo "$OUT/ab_null.csv";;    rate) echo "$OUT/ab_triad.csv";;
    matched) echo "$OUT/ab_matched.csv";; ovf) echo "$OUT/ab_ovf.csv";;
    conn) echo "$OUT/regimes_conn.csv";;  mset) echo "$OUT/regimes_mset.csv";;
    rlvalue) echo "$OUT/rl_value.csv";;   *) echo "";;
  esac
}

# visits per arm, from the csv's own round/visit/arm columns
visits_ok(){ # visits_ok <csv> <min>
  [ -s "$1" ] || return 1
  python3 - "$1" "$2" <<'PYEOF'
import csv, sys
try:
    rows = list(csv.DictReader(open(sys.argv[1])))
except OSError:
    sys.exit(1)
per = {}
for r in rows:
    per.setdefault(r.get('arm', '?'), set()).add((r.get('round'), r.get('visit')))
need = int(sys.argv[2])
sys.exit(0 if per and len(per) >= 2 and all(len(v) >= need for v in per.values()) else 1)
PYEOF
}

render(){ # render <phase>
  local c; c=$(csv_for "$1"); [ -n "$c" ] && [ -s "$c" ] || return 0
  case "$1" in
    null)    python3 "$HERE/ab_triad_report.py"  "$c" > "$OUT/ab_null.txt" 2>/dev/null;;
    rate)    python3 "$HERE/ab_triad_report.py"  "$c" > "$OUT/ab_triad.txt" 2>/dev/null;;
    matched) python3 "$HERE/ab_triad_report.py"  "$c" > "$OUT/ab_matched.txt" 2>/dev/null;;
    ovf)     python3 "$HERE/ab_triad_report.py"  "$c" > "$OUT/ab_ovf.txt" 2>/dev/null;;
    conn)    python3 "$HERE/regimes_report.py"   "$c" > "$OUT/regimes_conn.txt" 2>/dev/null;;
    mset)    python3 "$HERE/regimes_report.py"   "$c" > "$OUT/regimes_mset.txt" 2>/dev/null;;
  esac
}

artifact_for(){
  case "$1" in
    null)    echo "$OUT/ab_null.txt";;
    rate)    echo "$OUT/ab_triad.txt";;
    matched) echo "$OUT/ab_matched.txt";;
    ovf)     echo "$OUT/ab_ovf.txt";;
    conn)    echo "$OUT/regimes_conn.txt";;
    mset)    echo "$OUT/regimes_mset.txt";;
    rlvalue) echo "$OUT/rl_value.txt";;
    probe)   echo "$OUT/probe_cost.txt";;
    *)       echo "";;
  esac
}

remaining(){
  local p c out=""
  for p in "$@"; do
    c=$(csv_for "$p")
    if [ -n "$c" ] && visits_ok "$c" "$MIN_VISITS"; then continue; fi
    out="$out $p"
  done
  echo "${out# }"
}

render_all(){ local p; for p in "$@"; do render "$p"; done; }

attempt=0
while :; do
  todo=$(remaining "$@")
  [ -n "$todo" ] || { echo "$(date +%T) ALL PHASES HAVE THEIR ARTIFACT: $*"; exit 0; }
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "$(date +%T) GIVING UP with '$todo' unfinished"; exit 1
  fi
  attempt=$((attempt+1))
  echo "$(date +%T) attempt $attempt, remaining: $todo"
  "$HERE/run_when_clear.sh" $todo
  rc=$?
  # Render whatever landed, every time, so a table exists from the first completed cell onward.
  render_all "$@"
  echo "$(date +%T) attempt $attempt ended rc=$rc"
  case "$rc" in
    0) ;;                                  # finished; loop re-checks and exits if nothing is left
    2) echo "  owner took the box; waiting again";;
    1) echo "  gave up waiting or a phase failed; re-checking anyway";;
    *) echo "  unexpected rc=$rc; re-checking anyway";;
  esac
  # A phase that fails without producing its artifact would spin this loop. One idle minute between
  # attempts keeps a broken phase from becoming a busy loop on a shared box.
  sleep 60
done
