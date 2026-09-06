#!/bin/bash
# splits.sh WORKLOAD SECS RATIO... -- controller OFF at each static split: the true optimum on this rig.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
WL=$1; SECS=$2; shift 2
for sp in "$@"; do
  require_gate || exit 3
  pid=$(boot "$FIX_BIN" "$PORT_SPLIT" "split-$sp" --ratio "$sp" --shards 64 --atomic 1 --flip-auto 0) || exit 2
  preload "$PORT_SPLIT"
  lbsnap "$PORT_SPLIT" >"$SP/fd-lbs0.txt"
  case "$WL" in mk) out=$(./scratch/mk.sh "$PORT_SPLIT" "$SECS" 2>/dev/null);; *) out=$(./scratch/sk.sh "$PORT_SPLIT" "$SECS" "$WL" 2>/dev/null);; esac
  lbsnap "$PORT_SPLIT" >"$SP/fd-lbs1.txt"
  echo "split $WL ratio=$sp rate=$(echo "$out" | awk '/^Totals/{print $2}') busy=$(lbbusy "$SP/fd-lbs0.txt" "$SP/fd-lbs1.txt")"
  stop "$pid" "$PORT_SPLIT"
done
